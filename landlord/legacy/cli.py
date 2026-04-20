"""CLI entry point for the Landlord Framework."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

import typer
from rich.console import Console

from landlord.legacy.config import LandlordConfig
from landlord.legacy.dashboard import Dashboard
from landlord.legacy.event_bus import EventBus
from landlord.legacy.llm_client import LLMClient
from landlord.legacy.landlord import Landlord
from landlord.legacy.renderer import LiveRenderer
from landlord.legacy.repl import Repl
from landlord.legacy.validator import Validator

app = typer.Typer(
    name="landlord",
    help="An agentic AI framework with contract-based orchestration",
    invoke_without_command=True,
)


def _build_config(
    model: str | None,
    landlord_model: str | None,
    tenant_model: str | None,
    output: str,
    max_retries: int,
    config: str | None,
    verbose: bool,
    auto_approve: bool,
) -> LandlordConfig:
    effective_landlord = landlord_model or model
    effective_tenant = tenant_model or model
    return LandlordConfig.load(
        config_path=config,
        landlord_model=effective_landlord,
        tenant_model=effective_tenant,
        output_dir=output,
        max_retries=max_retries,
        verbose=verbose,
        auto_approve=auto_approve,
    )


def _run_one_shot(cfg: LandlordConfig, prompt: str) -> None:
    """Run a single prompt to completion."""
    dashboard = Dashboard(model=cfg.landlord_model)
    llm_client = LLMClient(model=cfg.landlord_model)
    event_bus = EventBus()
    validator = Validator(llm_client=llm_client)
    renderer = LiveRenderer(dashboard=dashboard, verbose=cfg.verbose)

    landlord = Landlord(
        config=cfg,
        llm_client=llm_client,
        event_bus=event_bus,
        validator=validator,
        renderer=renderer,
    )

    asyncio.run(landlord.run(prompt))


async def _interactive_loop(cfg: LandlordConfig) -> None:
    """Run the interactive REPL."""
    console = Console()
    repl = Repl(config=cfg, console=console)
    repl.show_welcome()

    while True:
        user_input = repl.prompt()
        if user_input is None:
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if repl.is_command(user_input):
            should_exit = repl.handle_command(user_input)
            if should_exit:
                break
            continue

        # Run a task
        dashboard = repl.dashboard
        llm_client = LLMClient(model=cfg.landlord_model)
        event_bus = EventBus()
        validator = Validator(llm_client=llm_client)
        renderer = LiveRenderer(
            console=console,
            dashboard=dashboard,
            verbose=cfg.verbose,
        )

        landlord = Landlord(
            config=cfg,
            llm_client=llm_client,
            event_bus=event_bus,
            validator=validator,
            renderer=renderer,
        )

        try:
            renderer.start_live()
            await landlord.run(user_input)
            renderer.stop_live()
            repl.set_last_contracts(list(landlord._active_contracts.values()))
            dashboard.update_tokens(
                prompt_tokens=llm_client.usage.prompt_tokens,
                completion_tokens=llm_client.usage.completion_tokens,
            )
        except KeyboardInterrupt:
            renderer.stop_live()
            console.print("\n[yellow]Interrupted.[/yellow] Returning to prompt.\n")
        except Exception as e:
            renderer.stop_live()
            console.print(f"[red]Error:[/red] {e}\n")


@app.command()
def main(
    prompt: Annotated[Optional[str], typer.Argument(help="The task to accomplish")] = None,
    model: Annotated[Optional[str], typer.Option("--model", "-m", help="Override LLM model")] = None,
    landlord_model: Annotated[Optional[str], typer.Option("--landlord-model")] = None,
    tenant_model: Annotated[Optional[str], typer.Option("--tenant-model")] = None,
    output: Annotated[str, typer.Option("--output", "-o")] = "./output",
    max_retries: Annotated[int, typer.Option("--max-retries")] = 3,
    config: Annotated[Optional[str], typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    auto_approve: Annotated[bool, typer.Option("--auto-approve")] = False,
) -> None:
    """Run the Landlord Framework. Pass a prompt for one-shot mode, or omit for interactive."""
    cfg = _build_config(model, landlord_model, tenant_model, output, max_retries, config, verbose, auto_approve)

    if prompt:
        _run_one_shot(cfg, prompt)
    else:
        asyncio.run(_interactive_loop(cfg))
