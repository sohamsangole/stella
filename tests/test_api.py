import hashlib
import hmac
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from stella.api.main import (
    get_allowed_author_associations,
    github_webhook,
    verify_github_signature,
)


class WebhookApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.secret = "test-secret"
        self.patcher = patch("stella.api.main.settings")
        self.mock_settings = self.patcher.start()
        self.mock_settings.github_webhook_secret = self.secret
        self.mock_settings.github_app_name = "coding-agent-stella"
        self.mock_settings.allowed_author_associations = "OWNER,MEMBER,COLLABORATOR"

    def tearDown(self) -> None:
        self.patcher.stop()

    def _sign_payload(self, body_bytes: bytes) -> str:
        hash_object = hmac.new(
            self.secret.encode("utf-8"),
            msg=body_bytes,
            digestmod=hashlib.sha256,
        )
        return "sha256=" + hash_object.hexdigest()

    def _create_mock_request(
        self,
        payload: dict,
        event: str = "issue_comment",
    ) -> tuple[MagicMock, str]:
        body_bytes = json.dumps(payload).encode("utf-8")
        signature = self._sign_payload(body_bytes)

        request = MagicMock()
        request.body = AsyncMock(return_value=body_bytes)
        request.json = AsyncMock(return_value=payload)
        request.headers = {"X-GitHub-Event": event}
        return request, signature

    def test_verify_github_signature(self) -> None:
        body = b'{"hello": "world"}'
        valid_sig = self._sign_payload(body)
        self.assertTrue(verify_github_signature(body, valid_sig))
        self.assertFalse(verify_github_signature(body, "sha256=invalid"))
        self.assertFalse(verify_github_signature(body, ""))

    def test_get_allowed_author_associations(self) -> None:
        self.mock_settings.allowed_author_associations = "OWNER, MEMBER, collaborator"
        self.assertEqual(
            get_allowed_author_associations(),
            {"OWNER", "MEMBER", "COLLABORATOR"},
        )

        self.mock_settings.allowed_author_associations = ["owner", "member"]
        self.assertEqual(
            get_allowed_author_associations(),
            {"OWNER", "MEMBER"},
        )

    @patch("stella.api.main.process_stella_task")
    async def test_enqueues_task_for_authorized_owner(
        self, mock_process_task
    ) -> None:
        payload = {
            "action": "created",
            "comment": {
                "body": "Hey @coding-agent-stella please fix this bug",
                "author_association": "OWNER",
                "user": {"type": "User", "login": "sohamsangole"},
            },
        }
        request, signature = self._create_mock_request(payload)

        response = await github_webhook(request, x_hub_signature_256=signature)

        self.assertEqual(response.get("status"), "success")
        mock_process_task.delay.assert_called_once_with(payload)

    @patch("stella.api.main.process_stella_task")
    async def test_enqueues_task_for_collaborator(
        self, mock_process_task
    ) -> None:
        payload = {
            "action": "created",
            "comment": {
                "body": "Hey @coding-agent-stella check this",
                "author_association": "COLLABORATOR",
                "user": {"type": "User", "login": "collab-user"},
            },
        }
        request, signature = self._create_mock_request(payload)

        response = await github_webhook(request, x_hub_signature_256=signature)

        self.assertEqual(response.get("status"), "success")
        mock_process_task.delay.assert_called_once_with(payload)

    @patch("stella.api.main.process_stella_task")
    async def test_rejects_unauthorized_contributor(
        self, mock_process_task
    ) -> None:
        payload = {
            "action": "created",
            "comment": {
                "body": "Hey @coding-agent-stella run some tests",
                "author_association": "CONTRIBUTOR",
                "user": {"type": "User", "login": "random-user"},
            },
        }
        request, signature = self._create_mock_request(payload)

        response = await github_webhook(request, x_hub_signature_256=signature)

        self.assertEqual(response.get("status"), "ignored")
        self.assertEqual(response.get("reason"), "unauthorized_author_association")
        mock_process_task.delay.assert_not_called()

    @patch("stella.api.main.process_stella_task")
    async def test_rejects_none_author_association(
        self, mock_process_task
    ) -> None:
        payload = {
            "action": "created",
            "comment": {
                "body": "@coding-agent-stella hello",
                "author_association": "NONE",
                "user": {"type": "User", "login": "attacker"},
            },
        }
        request, signature = self._create_mock_request(payload)

        response = await github_webhook(request, x_hub_signature_256=signature)

        self.assertEqual(response.get("status"), "ignored")
        self.assertEqual(response.get("reason"), "unauthorized_author_association")
        mock_process_task.delay.assert_not_called()

    @patch("stella.api.main.process_stella_task")
    async def test_ignores_bot_comment(self, mock_process_task) -> None:
        payload = {
            "action": "created",
            "comment": {
                "body": "@coding-agent-stella hello",
                "author_association": "OWNER",
                "user": {"type": "Bot", "login": "github-actions[bot]"},
            },
        }
        request, signature = self._create_mock_request(payload)

        response = await github_webhook(request, x_hub_signature_256=signature)

        self.assertEqual(response.get("status"), "ignored")
        mock_process_task.delay.assert_not_called()


if __name__ == "__main__":
    unittest.main()
