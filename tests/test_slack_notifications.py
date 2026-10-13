import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import slack_notifications


class SlackNotificationTest(unittest.TestCase):
    def test_success_requires_http200_and_ok(self):
        response = Mock(status_code=200, text="ok")
        with patch.object(slack_notifications.requests, "post", return_value=response) as post:
            self.assertTrue(slack_notifications.send_slack_message("공시", "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "C0C9LQN7A64"))
        self.assertEqual(post.call_args.args, ("https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret",))
        self.assertNotIn("channel", post.call_args.kwargs["json"])
        self.assertNotIn("headers", post.call_args.kwargs)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_http200_without_ok_is_failure(self):
        for body in ("invalid_payload", "secret-detail", "{\"ok\":true}"):
            response = Mock(status_code=200, text=body)
            with patch.object(slack_notifications.requests, "post", return_value=response):
                self.assertFalse(slack_notifications.send_slack_message("공시", "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "C0C9LQN7A64"))

    def test_other_workspace_host_and_redirect_urls_never_send(self):
        for url in ("https://evil.test/services/T054M7CUG/BTEST/fakeSecret", "https://hooks.slack.com/services/TOTHER/BTEST/fakeSecret", "http://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret?extra=1"):
            with patch.object(slack_notifications.requests, "post") as post:
                self.assertFalse(slack_notifications.send_slack_message("공시", url, "C0C9LQN7A64"))
            post.assert_not_called()

    def test_missing_credentials_or_named_destination_never_sends(self):
        for token, channel in (("", "C0C9LQN7A64"), ("https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", ""), ("https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "#fss-monitor"), ("https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "DTEST")):
            with patch.object(slack_notifications.requests, "post") as post:
                self.assertFalse(slack_notifications.send_slack_message("공시", token, channel))
            post.assert_not_called()

    def test_rate_limit_and_exception_fail_without_leaking_or_retry(self):
        for result in (Mock(status_code=429, text="secret-detail"), RuntimeError("https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret secret-detail")):
            capture = io.StringIO()
            mock = patch.object(slack_notifications.requests, "post", side_effect=result) if isinstance(result, Exception) else patch.object(slack_notifications.requests, "post", return_value=result)
            with mock as post, contextlib.redirect_stdout(capture):
                self.assertFalse(slack_notifications.send_slack_message("공시", "https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", "C0C9LQN7A64"))
            post.assert_called_once()
            self.assertNotIn("https://hooks.slack.com/services/T054M7CUG/BTEST/fakeSecret", capture.getvalue())
            self.assertNotIn("secret-detail", capture.getvalue())
