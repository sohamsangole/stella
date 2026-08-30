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

    def test_reuses_existing_open_pull_request(self) -> None:
        requests_module.get.reset_mock()
        requests_module.post.reset_mock()
        response = Mock()
        response.json.return_value = [
            {"number": 17, "html_url": "https://github.com/example/repo/pull/17"}
        ]
        requests_module.get.return_value = response

        result = GitHubClient(token="installation-token").ensure_pull_request(
            repository_api_url="https://api.github.com/repos/example/repo",
            owner="example",
            head_branch="stella/issue-7",
            base_branch="master",
            title="Stella: resolve issue #7",
            body="Automated change for #7.",
        )

        self.assertEqual(
            result,
            {"number": 17, "html_url": "https://github.com/example/repo/pull/17"},
        )
        requests_module.post.assert_not_called()

    def test_creates_pull_request_when_no_open_one_exists(self) -> None:
        requests_module.get.reset_mock()
        requests_module.post.reset_mock()
        list_response = Mock()
        list_response.json.return_value = []
        create_response = Mock()
        create_response.json.return_value = {
            "number": 18,
            "html_url": "https://github.com/example/repo/pull/18",
        }
        requests_module.get.return_value = list_response
        requests_module.post.return_value = create_response

        result = GitHubClient(token="installation-token").ensure_pull_request(
            repository_api_url="https://api.github.com/repos/example/repo",
            owner="example",
            head_branch="stella/issue-7",
            base_branch="main",
            title="Stella: resolve issue #7",
            body="Automated change for #7.",
        )

        self.assertEqual(result["number"], 18)
        self.assertEqual(result["html_url"], "https://github.com/example/repo/pull/18")
        requests_module.post.assert_called_once_with(
            "https://api.github.com/repos/example/repo/pulls",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Authorization": "Bearer installation-token",
            },
            json={
                "title": "Stella: resolve issue #7",
                "head": "stella/issue-7",
                "base": "main",
                "body": "Automated change for #7.",
            },
            timeout=30,
        )
        create_response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
