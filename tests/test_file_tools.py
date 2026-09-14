import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stella.tools import (
    AmbiguousMatchError,
    FileToolError,
    FileTools,
    LLMFileUtility,
    SecurityError,
    TargetNotFoundError,
    ToolResult,
)


class FileToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)
        self.tools = FileTools(self.workspace_root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # read_file tests
    # -------------------------------------------------------------------------
    def test_read_file_whole_with_and_without_line_numbers(self) -> None:
        sample_file = self.workspace_root / "hello.py"
        sample_file.write_text("def foo():\n    return 42\n", encoding="utf-8")

        # Default line_numbers=True
        numbered = self.tools.read_file("hello.py")
        self.assertEqual(numbered, "1: def foo():\n2:     return 42")

        # line_numbers=False
        plain = self.tools.read_file("hello.py", line_numbers=False)
        self.assertEqual(plain, "def foo():\n    return 42")

    def test_read_file_line_slices(self) -> None:
        sample_file = self.workspace_root / "lines.txt"
        sample_file.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

        sliced = self.tools.read_file("lines.txt", start_line=2, end_line=4, line_numbers=True)
        self.assertEqual(sliced, "2: line2\n3: line3\n4: line4")

        sliced_plain = self.tools.read_file("lines.txt", start_line=3, end_line=3, line_numbers=False)
        self.assertEqual(sliced_plain, "line3")

    def test_read_file_empty_and_out_of_bounds(self) -> None:
        empty_file = self.workspace_root / "empty.txt"
        empty_file.write_text("", encoding="utf-8")
        self.assertEqual(self.tools.read_file("empty.txt"), "")

        content_file = self.workspace_root / "test.txt"
        content_file.write_text("only one line\n", encoding="utf-8")

        with self.assertRaises(FileToolError):
            self.tools.read_file("test.txt", start_line=5)

        with self.assertRaises(FileToolError):
            self.tools.read_file("test.txt", start_line=3, end_line=2)

    def test_read_file_detects_binary(self) -> None:
        binary_file = self.workspace_root / "binary.bin"
        binary_file.write_bytes(b"hello\x00world\x01\x02")

        with self.assertRaisesRegex(FileToolError, "binary file detected"):
            self.tools.read_file("binary.bin")

    def test_read_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.tools.read_file("nonexistent.py")

    # -------------------------------------------------------------------------
    # create_file tests
    # -------------------------------------------------------------------------
    def test_create_file_nested_directories(self) -> None:
        msg = self.tools.create_file("nested/pkg/module.py", "print('nested')\n")
        self.assertIn("Successfully created", msg)
        created = self.workspace_root / "nested" / "pkg" / "module.py"
        self.assertTrue(created.is_file())
        self.assertEqual(created.read_text(encoding="utf-8"), "print('nested')\n")

    def test_create_file_overwrite_behavior(self) -> None:
        self.tools.create_file("existing.txt", "v1")
        with self.assertRaises(FileExistsError):
            self.tools.create_file("existing.txt", "v2", overwrite=False)

        # Overwrite allowed
        self.tools.create_file("existing.txt", "v2", overwrite=True)
        self.assertEqual((self.workspace_root / "existing.txt").read_text(encoding="utf-8"), "v2")

    # -------------------------------------------------------------------------
    # delete_file tests
    # -------------------------------------------------------------------------
    def test_delete_file_success_and_missing_ok(self) -> None:
        target = self.workspace_root / "to_delete.py"
        target.write_text("x = 1", encoding="utf-8")
        self.assertTrue(target.exists())

        res = self.tools.delete_file("to_delete.py")
        self.assertIn("Successfully deleted file", res)
        self.assertFalse(target.exists())

        # missing_ok=False raises
        with self.assertRaises(FileNotFoundError):
            self.tools.delete_file("to_delete.py", missing_ok=False)

        # missing_ok=True succeeds
        msg = self.tools.delete_file("to_delete.py", missing_ok=True)
        self.assertIn("missing_ok=True", msg)

    def test_delete_directory_rejected(self) -> None:
        dir_path = self.workspace_root / "subdir"
        dir_path.mkdir()
        with self.assertRaisesRegex(FileToolError, "is a directory"):
            self.tools.delete_file("subdir")

    # -------------------------------------------------------------------------
    # update_file tests
    # -------------------------------------------------------------------------
    def test_update_file_overwrite_and_append(self) -> None:
        self.tools.update_file("log.txt", "Initial line\n")
        self.assertEqual((self.workspace_root / "log.txt").read_text(encoding="utf-8"), "Initial line\n")

        # Overwrite
        self.tools.update_file("log.txt", "Overwritten line\n")
        self.assertEqual((self.workspace_root / "log.txt").read_text(encoding="utf-8"), "Overwritten line\n")

        # Append
        self.tools.update_file("log.txt", "Second line\n", append=True)
        self.assertEqual(
            (self.workspace_root / "log.txt").read_text(encoding="utf-8"),
            "Overwritten line\nSecond line\n",
        )

    # -------------------------------------------------------------------------
    # replace_code tests
    # -------------------------------------------------------------------------
    def test_replace_code_exact_match(self) -> None:
        code_file = self.workspace_root / "app.py"
        code_file.write_text(
            "def calculate(a, b):\n"
            "    # Old logic\n"
            "    return a - b\n",
            encoding="utf-8",
        )

        self.tools.replace_code(
            path="app.py",
            target_content="    # Old logic\n    return a - b",
            replacement_content="    # New logic\n    return a + b",
        )

        expected = (
            "def calculate(a, b):\n"
            "    # New logic\n"
            "    return a + b\n"
        )
        self.assertEqual(code_file.read_text(encoding="utf-8"), expected)

    def test_replace_code_scoped_by_lines(self) -> None:
        code_file = self.workspace_root / "scoped.py"
        code_file.write_text(
            "value = 1\n"
            "value = 1\n"
            "value = 1\n",
            encoding="utf-8",
        )

        # Replace only the second line using line scoping
        self.tools.replace_code(
            path="scoped.py",
            target_content="value = 1",
            replacement_content="value = 2",
            start_line=2,
            end_line=2,
        )

        expected = "value = 1\nvalue = 2\nvalue = 1\n"
        self.assertEqual(code_file.read_text(encoding="utf-8"), expected)

    def test_replace_code_ambiguous_matches_rejected_without_allow_multiple(self) -> None:
        code_file = self.workspace_root / "duplicate.py"
        code_file.write_text("item = 'val'\nitem = 'val'\n", encoding="utf-8")

        with self.assertRaises(AmbiguousMatchError):
            self.tools.replace_code(
                path="duplicate.py",
                target_content="item = 'val'",
                replacement_content="item = 'new'",
                allow_multiple=False,
            )

        # allow_multiple=True replaces all
        self.tools.replace_code(
            path="duplicate.py",
            target_content="item = 'val'",
            replacement_content="item = 'new'",
            allow_multiple=True,
        )
        self.assertEqual(code_file.read_text(encoding="utf-8"), "item = 'new'\nitem = 'new'\n")

    def test_replace_code_target_not_found(self) -> None:
        code_file = self.workspace_root / "test.py"
        code_file.write_text("x = 10\n", encoding="utf-8")

        with self.assertRaises(TargetNotFoundError):
            self.tools.replace_code(
                path="test.py",
                target_content="y = 20",
                replacement_content="y = 30",
            )

    # -------------------------------------------------------------------------
    # Security tests
    # -------------------------------------------------------------------------
    def test_path_traversal_prevention(self) -> None:
        with self.assertRaisesRegex(SecurityError, "resolves outside workspace"):
            self.tools.read_file("../../etc/passwd")

        with self.assertRaisesRegex(SecurityError, "resolves outside workspace"):
            self.tools.create_file("../outside.txt", "data")

    def test_git_directory_protection(self) -> None:
        with self.assertRaisesRegex(SecurityError, "Access to git internal path"):
            self.tools.create_file(".git/config", "[core]")

        with self.assertRaisesRegex(SecurityError, "Access to git internal path"):
            self.tools.read_file(".git/HEAD")

    def test_symlink_escape_protection(self) -> None:
        with TemporaryDirectory() as outside_dir:
            outside_file = Path(outside_dir) / "secret.txt"
            outside_file.write_text("secret_data", encoding="utf-8")

            link_file = self.workspace_root / "symlink_escape.txt"
            try:
                link_file.symlink_to(outside_file)
            except OSError as err:
                self.skipTest(f"Symlinks not supported: {err}")

            with self.assertRaisesRegex(SecurityError, "unsafe symlink_escape.txt"):
                self.tools.read_file("symlink_escape.txt")

    # -------------------------------------------------------------------------
    # execute_tool dispatcher tests
    # -------------------------------------------------------------------------
    def test_execute_tool_success_and_failure(self) -> None:
        # Create
        res_create = self.tools.execute_tool(
            "create_file", {"path": "dispatcher.txt", "content": "hello dispatcher"}
        )
        self.assertTrue(res_create.success)
        self.assertIn("Successfully created file", res_create.output)

        # Read
        res_read = self.tools.execute_tool("read_file", {"path": "dispatcher.txt"})
        self.assertTrue(res_read.success)
        self.assertIn("hello dispatcher", res_read.output)

        # Tool failure handled gracefully in ToolResult
        res_fail = self.tools.execute_tool("read_file", {"path": "does_not_exist.txt"})
        self.assertFalse(res_fail.success)
        self.assertIn("FileNotFoundError", res_fail.error)

        # Unknown tool
        res_unknown = self.tools.execute_tool("nonexistent_tool", {})
        self.assertFalse(res_unknown.success)
        self.assertIn("Unknown tool", res_unknown.error)

    # -------------------------------------------------------------------------
    # Tool schemas tests
    # -------------------------------------------------------------------------
    def test_tool_schemas_structure(self) -> None:
        schemas = self.tools.get_tool_schemas()
        self.assertIsInstance(schemas, list)
        self.assertEqual(len(schemas), 5)

        names = {s["function"]["name"] for s in schemas}
        expected_names = {"read_file", "create_file", "delete_file", "update_file", "replace_code"}
        self.assertEqual(names, expected_names)

        for s in schemas:
            func = s["function"]
            self.assertIn("description", func)
            self.assertIn("parameters", func)
            params = func["parameters"]
            self.assertEqual(params["type"], "object")
            self.assertIn("properties", params)
            self.assertIn("required", params)

    def test_alias_equivalence(self) -> None:
        self.assertIs(LLMFileUtility, FileTools)


if __name__ == "__main__":
    unittest.main()
