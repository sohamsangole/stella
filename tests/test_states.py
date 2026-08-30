import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from stella.core.state_machine import StateContext, TaskEvent, TaskState
from stella.states import (
    CodeStateRunner,
    PlanStateRunner,
    ReviewStateRunner,
    TestStateRunner,
)


class StateRunnersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = StateContext(
            task_id="test-task-states",
            issue_url="https://github.com/example/repo/issues/10",
            repository_path=Path("/tmp/fake_repo"),
        )

    def test_plan_runner(self) -> None:
        runner = PlanStateRunner()
        self.assertEqual(runner.state, TaskState.PLAN)
        event, message = runner.execute(self.context)
        self.assertEqual(event, TaskEvent.PLAN_APPROVED)
        self.assertIn("plan", self.context.data)

    def test_code_runner(self) -> None:
        with TemporaryDirectory() as directory:
            repository = Path(directory)
            main_file = repository / "main.py"
            main_file.write_text('print("existing code")\n', encoding="utf-8")
            self.context.repository_path = repository
            runner = CodeStateRunner(
                clock=lambda: datetime(2026, 8, 31, 12, 34, 56, tzinfo=timezone.utc)
            )

            event, message = runner.execute(self.context)

            self.assertEqual(runner.state, TaskState.CODE)
            self.assertEqual(event, TaskEvent.CODE_COMPLETED)
            self.assertEqual(
                main_file.read_text(encoding="utf-8"),
                'print("existing code")\n'
                'print("Updated automatically by Stella")\n'
                "# Stella update: 2026-08-31T12:34:56Z\n",
            )
            self.assertEqual(
                self.context.get_data("code_changes")["modified_files"],
                ["main.py"],
            )

    def test_code_runner_keeps_print_idempotent_and_adds_each_timestamp(self) -> None:
        timestamps = iter(
            [
                datetime(2026, 8, 31, 12, 34, 56, tzinfo=timezone.utc),
                datetime(2026, 8, 31, 12, 35, 57, tzinfo=timezone.utc),
            ]
        )
        with TemporaryDirectory() as directory:
            repository = Path(directory)
            self.context.repository_path = repository
            runner = CodeStateRunner(clock=lambda: next(timestamps))

            runner.execute(self.context)
            runner.execute(self.context)

            self.assertEqual(
                (repository / "main.py").read_text(encoding="utf-8"),
                'print("Updated automatically by Stella")\n'
                "# Stella update: 2026-08-31T12:34:56Z\n"
                "# Stella update: 2026-08-31T12:35:57Z\n",
            )

    def test_code_runner_rejects_symlinked_main_file(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            repository = Path(directory)
            outside_file = Path(outside) / "protected.py"
            outside_file.write_text('print("protected")\n', encoding="utf-8")
            try:
                (repository / "main.py").symlink_to(outside_file)
            except OSError as error:
                self.skipTest(f"Symlinks are unavailable in this environment: {error}")
            self.context.repository_path = repository

            with self.assertRaisesRegex(RuntimeError, "unsafe main.py"):
                CodeStateRunner().execute(self.context)

            self.assertEqual(
                outside_file.read_text(encoding="utf-8"),
                'print("protected")\n',
            )

    def test_review_runner(self) -> None:
        runner = ReviewStateRunner()
        self.assertEqual(runner.state, TaskState.REVIEW)
        event, message = runner.execute(self.context)
        self.assertEqual(event, TaskEvent.REVIEW_PASSED)
        self.assertIn("review_result", self.context.data)

    def test_test_runner(self) -> None:
        runner = TestStateRunner()
        self.assertEqual(runner.state, TaskState.TEST)
        event, message = runner.execute(self.context)
        self.assertEqual(event, TaskEvent.TEST_PASSED)
        self.assertIn("test_result", self.context.data)


if __name__ == "__main__":
    unittest.main()
