import json
import os
import unittest
from unittest import mock

from scripts.collect_papers import load_issue_config


class IssueConfigSecurityTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "GITHUB_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "sekire4/paper-daily",
            "CONFIG_ISSUE_TITLE": "Research Interests",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.defaults = {"sources": [{"type": "arxiv"}], "topics": [{"id": "default"}]}

    def issue(self, author, config):
        return {"title": "Research Interests", "user": {"login": author},
                "body": "```json\n" + json.dumps(config) + "\n```"}

    @mock.patch("scripts.collect_papers.github_request")
    def test_public_issue_cannot_override_sources_or_reference_credentials(self, request):
        request.return_value = [self.issue("untrusted-user", {
            "sources": [{"type": "feed", "url": "https://example.invalid/feed",
                         "bearer_token_env": "DEEPSEEK_API_KEY"}],
            "topics": [{"id": "injected"}],
        })]
        self.assertIs(load_issue_config(self.defaults), self.defaults)

    @mock.patch("scripts.collect_papers.github_request")
    def test_untrusted_newer_issue_does_not_shadow_owner_configuration(self, request):
        request.return_value = [
            self.issue("untrusted-user", {"topics": [{"id": "injected"}]}),
            self.issue("SeKiRe4", {"topics": [{"id": "agent_memory"}]}),
        ]
        self.assertEqual(load_issue_config(self.defaults)["topics"], [{"id": "agent_memory"}])

    @mock.patch("scripts.collect_papers.github_request")
    def test_missing_author_is_not_trusted(self, request):
        issue = self.issue("sekire4", {"topics": [{"id": "injected"}]})
        issue.pop("user")
        request.return_value = [issue]
        self.assertIs(load_issue_config(self.defaults), self.defaults)


if __name__ == "__main__":
    unittest.main()
