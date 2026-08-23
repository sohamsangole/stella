import unittest
from unittest.mock import Mock, patch


requests_module = Mock()
with patch.dict("sys.modules", {"requests": requests_module}):
    from stella.clients.github_client import GitHubClient


class GitHubClientTests(unittest.TestCase):
    def test_posts_authenticated_issue_comment(self) -> None:
        post = requests_module.post
        post.reset_mock()
        response = Mock()
        post.return_value = response

        GitHubClient(token="installation-token").post_issue_comment(
            "https://api.github.com/repos/example/repo/issues/7/comments",
            "Stella is working.",
        )

        post.assert_called_once_with(
            "https://api.github.com/repos/example/repo/issues/7/comments",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Authorization": "Bearer installation-token",
            },
            json={"body": "Stella is working."},
            timeout=30,
        )
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
