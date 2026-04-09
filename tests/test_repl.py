import pytest
from io import StringIO
from rich.console import Console

from landlord.repl import Repl
from landlord.config import LandlordConfig


class TestRepl:
    @pytest.fixture
    def config(self):
        return LandlordConfig(auto_approve=True)

    @pytest.fixture
    def console_buf(self):
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        return console, buf

    def test_show_welcome(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        repl.show_welcome()
        output = buf.getvalue()
        assert "Landlord Framework" in output
        assert config.landlord_model in output

    def test_handle_help(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        repl.handle_command("/help")
        output = buf.getvalue()
        assert "/help" in output
        assert "/quit" in output

    def test_handle_quit_returns_true(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        result = repl.handle_command("/quit")
        assert result is True

    def test_handle_unknown_command(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        result = repl.handle_command("/bogus")
        assert result is False
        output = buf.getvalue()
        assert "Unknown command" in output

    def test_handle_status_no_run(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        repl.handle_command("/status")
        output = buf.getvalue()
        assert "No tenants" in output or "no run" in output.lower()

    def test_handle_cost_no_run(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        repl.handle_command("/cost")
        output = buf.getvalue()
        assert "0" in output or "No" in output

    def test_is_command(self, config, console_buf):
        console, _ = console_buf
        repl = Repl(config=config, console=console)
        assert repl.is_command("/help") is True
        assert repl.is_command("Build a REST API") is False
        assert repl.is_command("") is False
