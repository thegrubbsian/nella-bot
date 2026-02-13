"""Tests for Slack app factory."""

from unittest.mock import AsyncMock, MagicMock, patch


def test_create_slack_app_returns_app() -> None:
    with patch("src.bot.slack.app.App") as MockApp, \
         patch("src.bot.slack.app.AsyncWebClient") as MockClient, \
         patch("src.bot.slack.app.settings") as mock_settings:
        mock_settings.slack_bot_token = "xoxb-test"
        mock_settings.default_notification_channel = "slack"
        mock_app = MagicMock()
        MockApp.return_value = mock_app
        MockClient.return_value = AsyncMock()

        from src.bot.slack.app import create_slack_app

        app = create_slack_app()
        assert app is mock_app
        MockApp.assert_called_once()
