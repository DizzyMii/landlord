# Interactive CLI — Design Spec

## Overview

Transform the Landlord CLI from a one-shot command into an interactive REPL with real-time streaming, stacked tenant panels, a persistent status dashboard, and interrupt support — inspired by Claude Code's UX.

## Entry Modes

### Interactive Mode (new)

```
landlord
```

Launches a persistent REPL session. Shows a branded welcome header with model/config info, then presents a `>` prompt. User types tasks naturally. Session persists until `/quit` or Ctrl+C at idle.

### One-Shot Mode (existing, preserved)

```
landlord "Build a REST API with auth"
```

Runs the task to completion and exits. Current behavior unchanged. All existing flags work in both modes.

### Mode Detection

If a positional `prompt` argument is provided, run one-shot. Otherwise, enter interactive mode. The `cli.py` entry point handles this with an optional argument.

## Startup Screen

On entering interactive mode, display:

```
╭─ Landlord Framework v0.1.0 ─────────────────────────╮
│  Model: gpt-4o  │  Output: ./output  │  Retries: 3  │
╰──────────────────────────────────────────────────────╯
  Tip: Type your task, or /help for commands

>
```

Built with Rich `Panel`. The model, output dir, and retries are pulled from the resolved `LandlordConfig`. The version comes from `landlord.__version__`.

## Persistent Status Bar

A single-line status bar rendered at the bottom of the terminal during execution. Always visible, updates in real-time.

```
 Tenants: ● backend(running) ● frontend(waiting) ○ tester(pending)  │  Tokens: 2.4k  │  Cost: ~$0.03
```

### Contents

- **Tenant status indicators**: `●` active (green), `●` waiting (yellow), `○` pending (dim), `✓` complete (green), `✗` failed (red)
- **Token count**: cumulative across all LLMClient instances in the session
- **Cost estimate**: calculated from model + token counts using a simple pricing table

### Implementation

A `Dashboard` class that:
- Holds references to all active `LLMClient` instances to sum token usage
- Maintains a `dict[str, str]` of tenant_id → status
- Exposes a `render() -> RenderableType` method that produces the status line
- Updated by the Landlord via method calls (not events — the dashboard is a display concern, not a domain object)

## Tenant Execution Display

### Stacked Panels

Each tenant gets its own Rich `Panel`, all visible simultaneously. Panels are rendered inside a `rich.live.Live` context that refreshes on updates.

```
╭─ backend_engineer (running) ─────────────────────────╮
│ ▸ Writing REST API routes...                         │
│ ✓ file_write src/server.js                           │
│ ▸ Setting up auth middleware...                      │
╰──────────────────────────────────────────────────────╯
╭─ frontend_engineer (waiting on backend_engineer) ────╮
│ ⏳ Blocked by dependency                             │
╰──────────────────────────────────────────────────────╯
```

### Panel Content

Each panel shows a rolling buffer of the last 8 activity lines (configurable). Activity lines include:

- **LLM text** (when verbose): streamed token-by-token, shown as the current line being written
- **Tool calls**: `✓ file_write src/server.js` (success) or `✗ shell_exec "npm test" — exit code 1` (failure)
- **Checkpoint events**: `✓ Checkpoint routes_defined passed` (green) or `✗ Checkpoint routes_defined failed: reason` (red)
- **Status changes**: `⏳ Waiting on backend_engineer`, `🔄 Retry 2/3 — tighter contract`, `⚠ Escalated — needs input`

### Panel Header

Shows: `role (status)` where status is one of: `running`, `waiting on <role>`, `retrying 2/3`, `complete`, `failed`, `escalated`.

### Panel Border Colors

- Running: blue
- Waiting: yellow
- Complete: green
- Failed/Evicted: red
- Escalated: bold yellow

## Live Rendering Architecture

The renderer uses `rich.live.Live` with a `Group` of panels + the status bar at the bottom. The Live context is entered when tenant execution begins and exited when all tenants complete (or on interrupt).

```python
class LiveRenderer:
    def __init__(self, console, dashboard, verbose):
        self._console = console
        self._dashboard = dashboard
        self._verbose = verbose
        self._tenant_panels: dict[str, TenantPanel] = {}
        self._live: Live | None = None

    def start(self): ...      # Enter Live context
    def stop(self): ...       # Exit Live context
    def update(self): ...     # Refresh the Live display

class TenantPanel:
    def __init__(self, contract):
        self.contract = contract
        self.status = "pending"
        self.lines: deque[str] = deque(maxlen=8)

    def add_line(self, line: str): ...
    def render(self) -> Panel: ...
```

The `LiveRenderer` composes all `TenantPanel.render()` outputs plus `Dashboard.render()` into a single renderable that `Live` refreshes.

## Interrupt Support

### During Execution (Ctrl+C)

1. Catch `KeyboardInterrupt` in the REPL's execution loop
2. Cancel all active tenant `asyncio.Task`s
3. Print a summary of what was completed vs interrupted
4. Return to the `>` prompt (do NOT exit the process)

### At Idle Prompt (Ctrl+C)

Exit cleanly with a goodbye message.

### Implementation

The REPL loop wraps each `landlord.run()` call in a try/except for `KeyboardInterrupt`. The Landlord's `run()` method needs to handle `asyncio.CancelledError` gracefully on its tasks and return partial results. Tenant output files on disk are preserved — partial work is still useful.

## REPL & Slash Commands

### REPL Loop

```python
class Repl:
    def __init__(self, config, console):
        self._config = config
        self._console = console

    async def run(self):
        self._show_welcome()
        while True:
            user_input = self._prompt()
            if user_input is None:  # Ctrl+C at idle
                break
            if user_input.startswith("/"):
                self._handle_command(user_input)
            else:
                await self._execute(user_input)
```

### Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/status` | Show all tenant statuses from last run |
| `/cost` | Show token usage breakdown by tenant |
| `/plan` | Re-display the last execution plan |
| `/quit` | Exit the session |

Commands are simple — no argument parsing. Each prints output and returns to the prompt.

### Prompt

Use `console.input("❯ ")` for the prompt character. The `❯` chevron matches Claude Code's style.

## Cost Estimation

### Pricing Table

A simple dict mapping model name prefixes to per-token costs:

```python
MODEL_PRICING = {
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "claude-sonnet": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "claude-haiku": {"input": 0.25 / 1_000_000, "output": 1.25 / 1_000_000},
    "claude-opus": {"input": 15.00 / 1_000_000, "output": 75.00 / 1_000_000},
}
```

Match by longest prefix. Unknown models show tokens only, no cost.

### Tracking

The `LLMClient` already tracks `TokenUsage`. The `Dashboard` collects all client instances and sums usage. Cost = `prompt_tokens * input_price + completion_tokens * output_price`.

## File Structure Changes

```
landlord/
├── cli.py              # Modified: detect interactive vs one-shot
├── repl.py             # New: REPL loop, welcome screen, command dispatch
├── dashboard.py        # New: status bar, cost tracking
├── renderer.py         # Rewritten: LiveRenderer with TenantPanel
├── llm_client.py       # Modified: add model name to usage tracking
└── ...
```

## Dependencies

No new dependencies. Everything uses `rich` (already installed):
- `rich.live.Live` for real-time display
- `rich.panel.Panel` for tenant panels
- `rich.console.Console` for prompt input
- `rich.table.Table` for cost breakdown display

## What Stays the Same

- All backend logic: Landlord, Tenant, Contract, EventBus, Validator, Tools
- Config system and YAML loading
- All existing CLI flags
- One-shot mode behavior
- Test suite (67 tests) — existing tests are unaffected since they mock the Renderer
