import pytest
from typer.testing import CliRunner
from unittest.mock import patch, AsyncMock, MagicMock
from landlord.cli import app


runner = CliRunner()


class TestCLI:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "prompt" in result.output.lower() or "Usage" in result.output

    def test_missing_prompt(self):
        result = runner.invoke(app, [])
        assert result.exit_code != 0

    @patch("landlord.cli.asyncio.run")
    @patch("landlord.cli.Landlord")
    @patch("landlord.cli.LLMClient")
    @patch("landlord.cli.Validator")
    def test_basic_invocation(self, mock_validator_cls, mock_llm_cls, mock_landlord_cls, mock_run):
        mock_landlord = MagicMock()
        mock_landlord.run = AsyncMock(return_value={})
        mock_landlord_cls.return_value = mock_landlord
        mock_run.side_effect = lambda coro: None

        result = runner.invoke(app, ["Build a REST API"])
        assert result.exit_code == 0

    @patch("landlord.cli.asyncio.run")
    @patch("landlord.cli.Landlord")
    @patch("landlord.cli.LLMClient")
    @patch("landlord.cli.Validator")
    def test_flags_parsed(self, mock_validator_cls, mock_llm_cls, mock_landlord_cls, mock_run):
        mock_run.side_effect = lambda coro: None

        result = runner.invoke(app, [
            "Build something",
            "--landlord-model", "gpt-4o",
            "--output", "/tmp/out",
            "--max-retries", "5",
            "--verbose",
            "--auto-approve",
        ])
        assert result.exit_code == 0
