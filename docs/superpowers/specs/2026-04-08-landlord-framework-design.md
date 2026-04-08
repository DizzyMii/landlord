# Landlord Framework — Design Spec

## Overview

The Landlord Framework is a Python CLI agentic AI framework. A user gives the "Landlord" a prompt. The Landlord decomposes it into sub-tasks, creates "Tenant" sub-agents bound by "Contracts," and orchestrates their parallel execution. If a tenant violates its contract, the Landlord evaluates the violation — if invalid, it evicts the tenant and spins up a fresh one with a tighter contract and violation context.

## Core Domain Model

### Landlord

The orchestrator. Takes a user prompt, decomposes it into a plan of sub-tasks, presents the plan for user approval, then creates tenants with contracts and monitors their execution.

- Makes LLM calls to decompose prompts, generate contracts, and judge violations.
- Subscribes to the EventBus for checkpoint events from all tenants.
- Can evict tenants (cancel async tasks) and spin up replacements.
- Combines final outputs from all tenants into the deliverable.

### Contract

A Pydantic model defining everything a tenant needs and is bound by:

- `role: str` — what the tenant is (e.g., "backend engineer", "data analyst").
- `objective: str` — what it must accomplish.
- `sub_prompt: str` — the actual prompt sent to the LLM.
- `checkpoints: list[Checkpoint]` — ordered validation points the tenant must hit.
- `output_schema: dict` — JSON Schema defining expected final output structure.
- `tools_allowed: list[str] | None` — whitelist of tools (if set, only these are available).
- `tools_denied: list[str] | None` — blacklist of tools (if set, everything except these).
- `depends_on: list[str] | None` — roles whose checkpoint artifacts this tenant needs before launching.
- `max_retries: int` — how many eviction/retry cycles before escalating to user.
- `context: str | None` — additional context (e.g., violation info on retry).

### Checkpoint

A Pydantic model for each validation point:

- `name: str` — human-readable checkpoint name.
- `description: str` — what should be true at this point.
- `schema: dict` — JSON Schema the tenant's output must conform to at this checkpoint.

### Tenant

An isolated async worker:

- Receives a contract and an LLMClient instance.
- Runs an LLM conversation loop, calling tools as needed.
- Emits events at checkpoints via the EventBus.
- Writes artifacts to its own isolated subdirectory.
- Has no awareness of other tenants.
- Can receive **read-only shared artifacts** injected by the Landlord from other tenants' verified checkpoint outputs (e.g., a DB schema produced by Tenant A can be shared into Tenant B's context). Tenants never access each other directly — the Landlord curates what gets shared and when.

### EventBus

Async pub/sub system for tenant-to-landlord communication:

- Events: `checkpoint_reached`, `artifact_produced`, `task_complete`, `task_failed`.
- Tenants publish. Landlord subscribes.
- Each event includes: `tenant_id`, `event_type`, `payload`, `timestamp`.

## Execution Flow

1. **User prompt** → Landlord receives it.
2. **Decomposition** → Landlord makes an LLM call to analyze the prompt and produce a structured plan (list of contracts).
3. **User approval gate** → Plan is printed to the terminal. User can approve, modify, or reject.
4. **Tenant launch** → All approved tenants launch as concurrent `asyncio.Task`s.
5. **Checkpoint validation** → When a tenant hits a checkpoint, it emits an event. The output is validated through a tiered pipeline (see Tiered Validation below).
6. **Violation judgment** → If Tier 1+2 validation fails but the failure is ambiguous, the Landlord makes an LLM call (Tier 3) to judge whether the deviation is acceptable or a real violation.
7. **Eviction** → On invalid violation, the tenant task is cancelled. A new contract is generated with the original objective, what went wrong, and tighter constraints. A fresh tenant spins up with a clean slate.
8. **Retry limit** → If retries are exhausted, the Landlord escalates to the user for guidance.
9. **Completion** → Tenant artifacts are written to disk. Progress streams to the terminal in real-time.

```
User Prompt
    │
    ▼
┌─────────┐   1. Decompose prompt into sub-tasks
│ Landlord │   2. Generate contracts for each
│          │   3. Present plan to user for approval
└────┬─────┘
     │  user approves (or tweaks)
     ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ Tenant A │  │ Tenant B │  │ Tenant C │
│ (async)  │  │ (async)  │  │ (async)  │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │              │              │
     ▼              ▼              ▼
  EventBus ◄────────────────────────
     │
     ▼
  Landlord validates each checkpoint event:
     ├─ PASS → tenant continues
     ├─ VIOLATION (valid) → tenant continues, contract note updated
     └─ VIOLATION (invalid) → evict tenant
                                  │
                                  ▼
                          retry < max_retries?
                          ├─ YES → new tenant, tighter contract,
                          │        clean slate + violation context
                          └─ NO  → escalate to user
```

## Tiered Validation Pipeline

Checkpoint validation runs through three tiers. Each tier is cheaper/faster than the next. Only escalate when the current tier can't determine validity.

| Tier | Mechanism | Cost | When it fires |
|------|-----------|------|---------------|
| **Tier 1** | Pydantic schema validation | Free, instant | Always — every checkpoint output is validated against its JSON Schema |
| **Tier 2** | Static analysis (linting, type checking, custom rules) | Cheap, local | When the checkpoint involves code artifacts — runs language-appropriate linters/type checkers via `shell_exec` |
| **Tier 3** | LLM judgment | Expensive | Only when Tier 1+2 pass structurally but the Landlord needs to assess semantic correctness, or when Tier 1+2 fail ambiguously |

- Tier 1 failures are always violations (wrong structure = wrong output).
- Tier 2 failures are always violations (code that doesn't lint/typecheck is broken).
- Tier 3 is the only tier that can rule a deviation "acceptable" — e.g., the tenant used a different but valid approach.

The validator module manages tier progression and short-circuits early when possible.

## Shared Artifacts

Tenants are isolated but real tasks have dependencies. The Landlord manages artifact sharing:

- When a tenant passes a checkpoint, the Landlord can mark specific outputs as **shared artifacts**.
- Shared artifacts are copied read-only into dependent tenants' context (not their working directory — injected into the LLM conversation).
- The contract can declare `depends_on: list[str]` — a list of other contract roles whose checkpoint artifacts this tenant needs.
- The Landlord ensures dependent tenants don't launch until their dependencies have produced the required artifacts.
- Tenants never access each other's directories directly. The Landlord is always the intermediary.

This preserves isolation while enabling collaboration on complex multi-part tasks.

## Provider Abstraction & LLM Layer

**LiteLLM** as the backbone for provider-agnostic LLM calls. Supports Anthropic (Claude) and OpenAI out of the box, with extensibility to 100+ providers.

### LLMClient

A thin wrapper around litellm:

- Model selection per role (Landlord can use a different model than tenants).
- Streaming support for real-time terminal output.
- Token usage tracking per tenant for cost visibility.
- Each Landlord and tenant gets its own `LLMClient` instance — no shared state.

### Configuration Hierarchy

```
CLI flags  →  override  →  config file (YAML)  →  override  →  defaults
```

Default models:
- Landlord: `claude-sonnet-4-20250514`
- Tenants: configurable per contract, defaults to landlord model.

## Tool System

### Standard Toolkit

Available to all tenants by default:

| Tool | Description |
|------|-------------|
| `file_write` | Write content to a file in the tenant's output directory |
| `file_read` | Read a file from the tenant's output directory |
| `shell_exec` | Run a shell command (sandboxed to output directory) |
| `web_search` | Search the web for information |
| `web_fetch` | Fetch a URL's content |

### Tool Interface

```python
class Tool(Protocol):
    name: str
    description: str
    parameters: dict  # JSON Schema

    async def execute(self, **kwargs) -> ToolResult: ...
```

### Contract-Level Tool Control

- `tools_allowed: ["file_write", "file_read"]` — whitelist mode, only these available.
- `tools_denied: ["shell_exec"]` — blacklist mode, everything except these.
- If neither is set, all standard tools are available.
- If both are set, `tools_allowed` takes precedence and `tools_denied` is ignored.

### Tenant Isolation

Each tenant gets its own subdirectory within the output folder. Tenant A cannot read Tenant B's files. The Landlord combines outputs after completion.

## CLI Interface

### Entry Point

```
landlord "Build a REST API with auth and a React dashboard"
```

### Flags

| Flag | Short | Description | Default |
|------|-------|-------------|---------|
| `--model` | `-m` | Override LLM model for all roles | — |
| `--landlord-model` | | Model for the Landlord | `claude-sonnet-4-20250514` |
| `--tenant-model` | | Default model for tenants | landlord model |
| `--output` | `-o` | Output directory | `./output` |
| `--max-retries` | | Global default retry limit | `3` |
| `--config` | | Path to YAML config file | — |
| `--verbose` | `-v` | Show full LLM exchanges | `false` |
| `--auto-approve` | | Skip user approval gate | `false` |

### Terminal Output

Uses `rich` for rendering. Streams tenant progress in real-time with panels showing status, checkpoints, and eviction/retry events.

## Project Structure

```
landlord-framework/
├── pyproject.toml
├── README.md
├── landlord/
│   ├── __init__.py
│   ├── cli.py                  # Typer CLI entry point
│   ├── config.py               # Config loading
│   ├── landlord.py             # Landlord orchestrator
│   ├── tenant.py               # Tenant worker
│   ├── contract.py             # Contract + Checkpoint Pydantic models
│   ├── event_bus.py            # Async event pub/sub
│   ├── llm_client.py           # LiteLLM wrapper
│   ├── validator.py            # Schema validation + LLM judgment
│   ├── renderer.py             # Terminal output (rich)
│   └── tools/
│       ├── __init__.py
│       ├── base.py             # Tool protocol + ToolResult
│       ├── file_write.py
│       ├── file_read.py
│       ├── shell_exec.py
│       ├── web_search.py
│       └── web_fetch.py
└── tests/
    ├── __init__.py
    ├── test_landlord.py
    ├── test_tenant.py
    ├── test_contract.py
    ├── test_event_bus.py
    └── test_validator.py
```

## Dependencies

- `litellm` — provider-agnostic LLM calls
- `pydantic` — contract schemas, validation
- `typer` — CLI framework
- `rich` — terminal rendering
- `pyyaml` — config file parsing

## Design Decisions

1. **Event-driven over process-based isolation** — Async tasks provide logical isolation with lower overhead than subprocesses. True OS-level isolation is overkill for LLM conversation workers.
2. **Checkpoint-based validation over step-by-step** — Balances oversight with efficiency. Avoids excessive LLM calls for validation.
3. **Clean slate on eviction** — Prevents contamination from bad output. The new tenant only gets violation context, not partial work.
4. **LiteLLM over custom abstraction** — No need to reinvent provider switching. LiteLLM is battle-tested and covers our needs.
5. **Pydantic for contracts** — Gets us schema validation, serialization, and type safety for free.
6. **Hybrid decomposition** — Landlord proposes, user approves. Gives oversight without requiring users to define agent architecture manually.
