"""CLI entry point for the Landlord Framework."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

import typer

from landlord.config import LandlordConfig
from landlord.event_bus import EventBus
from landlord.llm_client import LLMClient
from landlord.landlord import Landlord
from landlord.renderer import Renderer
from landlord.validator import Validator

app = typer.Typer(
    name="landlord",
    help="An agentic AI framework with contract-based orchestration",
)


@app.command()
def main(
    prompt: Annotated[str, typer.Argument(help="The task to accomplish")],
    model: Annotated[Optional[str], typer.Option("--model", "-m", help="Override LLM model for all roles")] = None,
    landlord_model: Annotated[Optional[str], typer.Option("--landlord-model", help="Model for the Landlord")] = None,
    tenant_model: Annotated[Optional[str], typer.Option("--tenant-model", help="Default model for tenants")] = None,
    output: Annotated[str, typer.Option("--output", "-o", help="Output directory")] = "./output",
    max_retries: Annotated[int, typer.Option("--max-retries", help="Global default retry limit")] = 3,
    config: Annotated[Optional[str], typer.Option("--config", help="Path to YAML config file")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show full LLM exchanges")] = False,
    auto_approve: Annotated[bool, typer.Option("--auto-approve", help="Skip user approval gate")] = False,
) -> None:
    """Run the Landlord Framework with the given prompt."""
    effective_landlord_model = landlord_model or model
    effective_tenant_model = tenant_model or model

    cfg = LandlordConfig.load(
        config_path=config,
        landlord_model=effective_landlord_model,
        tenant_model=effective_tenant_model,
        output_dir=output,
        max_retries=max_retries,
        verbose=verbose,
        auto_approve=auto_approve,
    )

    llm_client = LLMClient(model=cfg.landlord_model)
    event_bus = EventBus()
    validator = Validator(llm_client=llm_client)
    renderer = Renderer(verbose=cfg.verbose)

    landlord = Landlord(
        config=cfg,
        llm_client=llm_client,
        event_bus=event_bus,
        validator=validator,
        renderer=renderer,
    )

    asyncio.run(landlord.run(prompt))
