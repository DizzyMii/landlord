from typer.testing import CliRunner
from unittest.mock import patch
from landlord.legacy.cli import app


runner = CliRunner()


class TestCLI:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    @patch("landlord.legacy.cli.asyncio.run")
    @patch("landlord.legacy.cli.Landlord")
    @patch("landlord.legacy.cli.LLMClient")
    @patch("landlord.legacy.cli.Validator")
    def test_one_shot_mode(self, mock_val, mock_llm, mock_landlord_cls, mock_run):
        mock_run.side_effect = lambda coro: None
        result = runner.invoke(app, ["Build a REST API"])
        assert result.exit_code == 0

    @patch("landlord.legacy.cli.asyncio.run")
    @patch("landlord.legacy.cli.Landlord")
    @patch("landlord.legacy.cli.LLMClient")
    @patch("landlord.legacy.cli.Validator")
    def test_one_shot_with_flags(self, mock_val, mock_llm, mock_landlord_cls, mock_run):
        mock_run.side_effect = lambda coro: None
        result = runner.invoke(app, [
            "Build something",
            "--model", "gpt-4o",
            "--output", "/tmp/out",
            "--verbose",
            "--auto-approve",
        ])
        assert result.exit_code == 0

    @patch("landlord.legacy.cli.asyncio.run")
    def test_interactive_mode_no_prompt(self, mock_run):
        mock_run.side_effect = lambda coro: None
        result = runner.invoke(app, [])
        # Should enter interactive mode (no prompt arg) — not an error
        assert result.exit_code == 0
