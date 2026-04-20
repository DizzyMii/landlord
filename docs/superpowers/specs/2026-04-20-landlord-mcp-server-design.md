# Landlord MCP Server — Design Spec

## Overview

A local-first MCP server that exposes Landlord orchestration as a small async job API. A calling LLM (Claude Code, Cursor, Cline, etc.) can decompose a user request into a plan of parallel tenants, have the plan reviewed, launch tenants as concurrent Claude Agent SDK sessions, and collect their artifacts — all through five MCP tools over stdio.

This is the v1 foundation for the strategic plan: ship a standalone local MCP server first, layer a free subagent/plugin acquisition surface on top later, and evolve into a hosted paid service as the monetization surface.

## Scope

### In scope (v1)

- stdio MCP transport
- Five-tool async job API (start, approve, status, artifacts, cancel)
- Plan approval gate — caller must explicitly approve before tenants launch
- Claude Agent SDK-backed tenants, one `asyncio.Task` per tenant
- Per-checkpoint synthetic tool pattern for structured output
- Two-tier checkpoint validation: JSON Schema + structured LLM judge
- Eviction + retry with clean-slate context
- Dependency ordering via topo sort with cycle detection
- Per-job working directory, per-tenant subdirectory
- In-memory job registry with JSON sidecar for post-mortem inspection
- Prompt caching on the decomposition prompt, tenant system prompts, and tool schemas

### Out of scope (v1)

- HTTP/SSE transport
- Authentication, multi-tenant isolation across users, billing
- Subagent plugin / `/landlord` slash command for Claude Code
- Persistence across server restarts beyond the JSON sidecar
- MCP progress notifications (poll-based `get_status` only for v1)
- Migration tooling for users of the existing Landlord CLI — the CLI survives under `landlord/legacy/`

## Architecture

### Tool Surface

Five MCP tools. All follow an async-job pattern: state lives in the server, tools are thin accessors.

| Tool | Input | Output | Preconditions |
|---|---|---|---|
| `start_orchestration` | `{ prompt: str, output_dir?: str }` | `{ job_id: str, plan: Contract[], status: "awaiting_approval" }` | — |
| `approve_plan` | `{ job_id: str, edits?: Contract[] }` | `{ job_id: str, status: "running" }` | Job must be in `awaiting_approval`. Optional `edits` replaces the plan wholesale; edited plan must parse as valid Contracts and form a cycle-free DAG. |
| `get_status` | `{ job_id: str }` | `{ status: str, plan: Contract[], tenants: TenantStatus[] }` | Job must exist. |
| `get_artifacts` | `{ job_id: str }` | `{ artifacts: {role: json}, files: {role: [relpath]} }` | Job must be `complete`, `partial`, or `cancelled`. |
| `cancel` | `{ job_id: str }` | `{ job_id: str, status: "cancelled" }` | Job must be `awaiting_approval` or `running`. |

`TenantStatus` shape: `{ role: str, tenant_id: str, status: "pending"|"running"|"complete"|"evicted"|"escalated", checkpoints_passed: str[], retry_count: int, last_error?: str }`.

Job status progression: `awaiting_approval` → `running` → (`complete` | `partial` | `cancelled`). `partial` means some tenants escalated after exhausting retries.

### Execution Model

Tenants run as `claude_agent_sdk.ClaudeSDKClient` sessions, one `asyncio.Task` each, inside the MCP server process. Each session is configured with:

- **System prompt:** built from the tenant's `Contract` — role, objective, checkpoint descriptions with references to their synthetic tools, optional shared-artifact context from dependencies, optional retry context (reason for previous eviction).
- **Allowed tools:** Agent SDK filesystem + bash tools, scoped to the tenant's working directory; *plus* per-checkpoint synthetic tools (`emit_checkpoint__<sanitized_name>`) whose parameter schemas are the checkpoint's JSON Schema. The tenant calling a checkpoint tool is how it declares checkpoint completion with structured output forced by the tool-calling protocol.
- **Working directory:** `{output_dir}/{job_id}/{tenant_id}/`. Tenants cannot see each other's directories.

When a tenant calls a checkpoint synthetic tool, the SDK's tool-handler hook routes the call to the orchestrator, which validates and returns a synthetic tool result ("Checkpoint X passed/failed: reason"). On pass, the tenant continues. On fail, the tenant is evicted (see below).

### Orchestrator logic

The `Landlord` class (ported to the new runtime) does the following:

1. **Decompose.** `decompose(prompt) -> Contract[]` issues an Anthropic Messages API call with the decomposition system prompt and user prompt. Prompt caching is applied to the system prompt so decomposition costs amortize across runs. JSON-mode via Anthropic tool use to force a well-formed `Contract[]` output instead of parsing freeform JSON. See **Configuration** below for model selection.
2. **Approval gate.** The job sits in `awaiting_approval` with the decomposed plan. Tenants do not launch. If `approve_plan` is called with `edits`, the edits wholesale replace the plan after Contract validation + DAG cycle check.
3. **Launch.** On approval, the orchestrator computes topo order, creates an `asyncio.Event` per role, and spawns each tenant as a task. Each task waits on its dependencies' events before starting its SDK session.
4. **Checkpoint validation.** Each checkpoint tool call passes through `Validator`:
   - Tier 1: JSON Schema validation against the checkpoint's schema.
   - Tier 2: Anthropic API call with a structured tool (`judge_checkpoint`) returning `{ passed: bool, reason: str }`. The judge's system prompt is cached.
5. **Eviction + retry.** On checkpoint failure, the tenant's task is cancelled, retry count is incremented, a fresh tenant is spawned with the same Contract plus an additional `context` field containing the failure reason. When `retry_count >= contract.max_retries`, the tenant is marked `escalated` and orchestration continues for other tenants.
6. **Shared artifacts.** On checkpoint pass, the output is stored in `job.artifacts[role]` and the role's `asyncio.Event` is set — this is what unblocks downstream tenants waiting on the dependency. Dependents wait on the *first* passing checkpoint of each of their dependencies, not on the dependency's overall completion. A dependent tenant's system prompt is augmented with the serialized dependency artifacts captured at the moment the dependent starts, *and* those artifacts are also written to `{job_id}/shared/{role}.json` in read-only form so the dependent can `cat` or grep them through the bash tool.
7. **Completion.** When all tenants have finished (complete or escalated), the job status transitions to `complete` if every tenant is complete, else `partial`. The JSON sidecar is written.

### State model

```
JobRegistry
├── jobs: dict[job_id, Job]
└── lock: asyncio.Lock

Job
├── job_id: str (uuid4 hex, 8 chars)
├── prompt: str
├── plan: Contract[]
├── status: str
├── tenants: dict[tenant_id, TenantState]
├── artifacts: dict[role, dict]
├── output_dir: Path
├── created_at: float
└── approved_at: float | None

TenantState
├── contract: Contract
├── task: asyncio.Task | None
├── status: str
├── checkpoints_passed: list[str]
├── retry_count: int
└── last_error: str | None
```

The registry is purely in-memory for v1. A JSON sidecar (`{output_dir}/{job_id}/job.json`) is written on every state transition for crash-time inspection but is **not** used for recovery in v1.

## Data Flow

```
Caller                 MCP Server               Anthropic API
  │                        │                          │
  ├─ start_orchestration ──>                          │
  │                        ├── decompose (cached) ───>│
  │                        │<──── Contract[] ─────────┤
  │<── plan + job_id ──────┤                          │
  │                        │                          │
  ├─ approve_plan ─────────>                          │
  │<── running ────────────┤                          │
  │                        │                          │
  │                        ├─ topo sort, launch tasks
  │                        │                          │
  │                        ├─┬─ Tenant A ─────────────>  (SDK session, tools)
  │                        │ ├── checkpoint_tool_call ─┤
  │                        │ ├── Validator (T1)         │
  │                        │ ├── Validator (T2, cached)>│
  │                        │ │<── judge result ────────┤
  │                        │ └── artifact stored
  │                        │
  │                        └─┬─ Tenant B (waits on A)
  │                          └── ...
  │                        │
  ├─ get_status ──────────>│
  │<── status + tenants ───┤
  │                        │
  │                        └── all tasks done, status=complete
  │                        │
  ├─ get_artifacts ───────>│
  │<── artifacts + files ──┤
```

## Validation Pipeline

Tier 1 (JSON Schema) and Tier 2 (LLM judge) only. The original design's Tier 2 "static analysis" tier was never implemented and is dropped — tenants with bash access can run their own linters and report the result through their checkpoints if that matters for a given contract.

**Tier 1 — JSON Schema.** Uses `jsonschema.validate`. Schemas are deliberately lenient (no `enum`/`const`/`pattern`/`minItems` — content semantics belong in Tier 2) and must have at least one required property.

**Tier 2 — Structured LLM judge.** An Anthropic API call with a tool definition `judge_checkpoint(passed: bool, reason: str)`. The model is forced into tool-use mode for that tool, so output is always structured — no substring matching. System prompt is cached. Model is Opus 4.7 (same as landlord); downgrading to Sonnet for cheaper judgments is a post-v1 tuning knob.

If Tier 1 fails, the checkpoint fails immediately and Tier 2 is skipped.

## Prompt Caching Strategy

Anthropic's prompt caching has a 5-minute TTL and saves ~90% of input-token costs on cache hits. Apply `cache_control: {type: "ephemeral"}` to:

- The decomposition system prompt (stable across runs).
- Each tenant's system prompt prefix through the checkpoint descriptions (stable across the tenant's retry cycle).
- The judge's system prompt (stable across all judgments in a run).
- Tool definitions passed to tenants (stable across the tenant's retry cycle).

The retry scenario is the biggest win: if a tenant is evicted 2-3 times, the second and third launches read the tenant system prompt from cache.

## Configuration

The server reads configuration at startup from environment variables. No YAML, no CLI flags — the MCP server is launched by the client (e.g., Claude Code via `.claude/mcp.json`), so any configuration must pass through the `env` block of that launch definition.

| Variable | Default | Description |
|---|---|---|
| `LANDLORD_LANDLORD_MODEL` | `claude-opus-4-7` | Model used for decomposition and the Tier 2 judge. |
| `LANDLORD_TENANT_MODEL` | `claude-sonnet-4-6` | Default model for tenant SDK sessions. Individual Contracts can override via a future `model` field — out of scope for v1. |
| `LANDLORD_OUTPUT_DIR` | `./landlord-output` | Default base directory for job output. Can be overridden per-call via the `output_dir` argument to `start_orchestration`. |
| `LANDLORD_MAX_RETRIES` | `3` | Default max retries per tenant. Individual Contracts can override. |
| `ANTHROPIC_API_KEY` | — | Required. Read by both the `anthropic` SDK (for decomposition and judging) and the `claude-agent-sdk` (for tenants). |

`output_dir` passed to `start_orchestration` is resolved as follows: if absolute, used as-is; if relative, resolved against the server process's current working directory (typically the user's project root when Claude Code spawns the server via stdio).

## Repo Changes

Continue in the existing repo at `C:/Users/KadeHeglin/Downloads/Projects/AI-and-Agents/Landlord Framework/`. Move the litellm-based runtime into `landlord/legacy/` so the CLI still works and existing output is still readable, but it's out of the critical path.

New layout:

```
landlord-framework/
├── pyproject.toml            # updated dependencies, add mcp-server entry point
├── docs/
├── tests/
└── landlord/
    ├── __init__.py
    ├── mcp_server.py         # MCP server: tool definitions, server startup, routing
    ├── orchestrator.py       # Landlord class — decompose, approve, launch, evict, retry
    ├── tenant.py             # Agent SDK-backed tenant runner, checkpoint tool hooks
    ├── contract.py           # UNCHANGED — Contract, Checkpoint models
    ├── validator.py          # Rewritten — 2-tier, structured judge, prompt caching
    ├── jobs.py               # JobRegistry, Job, TenantState
    ├── anthropic_client.py   # Thin Anthropic SDK wrapper with cache_control helper
    └── legacy/               # Old litellm runtime parked here, unchanged
        ├── cli.py
        ├── repl.py
        ├── renderer.py
        ├── dashboard.py
        ├── event_bus.py
        ├── llm_client.py
        ├── tenant.py         # old tenant (not used by new runtime)
        └── tools/            # old sandboxed tools (file_read/write/shell/web)
```

The `landlord.py` top-level module from the old runtime becomes `landlord/legacy/landlord.py` to avoid shadowing the package. The new orchestrator lives at `landlord/orchestrator.py`.

## Dependencies

Add:
- `mcp` — Anthropic's Python MCP SDK (server side)
- `anthropic` — direct SDK (replaces litellm for cache_control support)
- `claude-agent-sdk` — tenant runtime

Keep:
- `pydantic` — Contract + Checkpoint models
- `jsonschema` — Tier 1 validation

Drop from critical path (remain only for the legacy CLI):
- `litellm`
- `typer`
- `rich`
- `pyyaml`
- `httpx`

`pyproject.toml` gets a new optional extra `legacy` that bundles typer/rich/pyyaml/httpx/litellm for anyone who still wants the old CLI. The default install is MCP-server-only.

## Testing Plan

**Carry over:**
- `test_contract.py` — Contract/Checkpoint validation (unchanged model).

**Rewrite:**
- `test_validator.py` — covers Tier 1 pass/fail, Tier 2 structured-tool pass/fail, Tier 1 short-circuit.

**New:**
- `test_jobs.py` — registry lifecycle, state transitions, status enum invariants, cycle detection on `approve_plan` edits, JSON sidecar write.
- `test_orchestrator.py` — decompose with mocked Anthropic client, dependency ordering via `asyncio.Event`, eviction + retry counter increments, escalation when retries exhausted, shared-artifact injection.
- `test_tenant.py` (new) — synthetic checkpoint tool routing through the SDK tool hook (mocked SDK), work-directory sandbox, retry context merging.
- `test_mcp_server.py` — tool contract (each tool's input/output schema), precondition enforcement, error shapes.

**Drop:**
- `test_cli.py`, `test_repl.py`, `test_dashboard.py`, `test_renderer.py`, `test_event_bus.py`, `test_llm_client.py`, `test_tools.py`, `test_integration.py` — all exercise legacy modules. Legacy tests can stay under `tests/legacy/` if desired, but they aren't run by the default `pytest`.

## Non-goals for v1

Already stated under Scope. Enumerated here for clarity at the design decision level:

1. **No hosted deployment.** The MCP server runs locally, spawned by Claude Code (or another MCP client) via stdio. Hosted HTTP MCP is v2 and requires auth, multi-user job isolation, and persistence — all separate concerns.
2. **No subagent plugin.** `.claude/agents/*.md` files and a `/landlord` slash command are the free acquisition surface, shipped after the server surface is stable.
3. **No recovery.** Server restart discards jobs. The JSON sidecar is inspection-only.
4. **No streaming.** `get_status` polling is enough. Progress notifications are a v1.5 add-on.
5. **No provider-agnostic LLM layer.** Anthropic-only in v1. LiteLLM support can return as an optional backend if needed, but every design decision here (caching, SDK, structured tools) leans Anthropic.

## Success Criteria

v1 is done when all of the following are demonstrable:

1. Adding the server to a user's `.claude/mcp.json` and restarting Claude Code results in all five tools being discoverable by the model.
2. `start_orchestration` on a two-tenant prompt (e.g., "design and implement a simple TODO API") returns a well-formed plan under 30 seconds.
3. `approve_plan` launches tenants; a tenant declaring a dependency on another tenant's role does not start SDK work until the dependency's first checkpoint has passed.
4. A tenant producing output that fails its JSON Schema is evicted and retried with the failure reason in its context. A tenant that passes Tier 1 but fails Tier 2's semantic judge is also evicted.
5. `get_artifacts` returns the expected per-role JSON plus the list of files each tenant wrote to its subdirectory.
6. Measuring input tokens on a run with two eviction cycles shows the second and third tenant launches reading the cached prefix (visible via the Anthropic API's `cache_read_input_tokens` field).
7. `cancel` on a running job terminates in-flight SDK sessions and reflects `cancelled` in `get_status` within 2 seconds.

## Design Decisions

1. **Five tools, not one.** A single synchronous `orchestrate` would hit MCP tool-call timeouts on any real work. Five small tools keep each call under a second and let the calling Claude interleave orchestration with other work in the same session.
2. **Approval gate preserved.** The decomposition step is high-risk (a wrong plan burns tokens on the wrong tenants). Forcing an explicit `approve_plan` step lets the calling Claude present the plan to the user before anything launches — same UX as today's CLI, adapted to the MCP transport.
3. **Agent SDK over raw Anthropic SDK.** The SDK gives us the tool loop, streaming, permission hooks, and context management we'd otherwise reimplement. Landlord's value is in the *orchestration* layer — contracts, checkpoints, eviction — not in another tool loop.
4. **Agent SDK over Claude Code CLI headless.** Subprocesses-per-tenant make tenants inherit the full Claude Code setup (Skills, user MCPs, hooks) but can't easily run in a hosted environment. We bias toward a path that extends to the hosted v2.
5. **Structured judge over substring match.** The current `validator.py` checks if the judge's response `.startswith("PASS")`. That's fragile. Using Anthropic's tool-use feature gives a typed `{passed, reason}` result with no string parsing.
6. **Two tiers, not three.** The original third tier (static analysis) was never implemented and is the wrong abstraction anyway — static analysis is a concern for the tenant's contract (the tenant runs its own linter), not for the validator.
7. **stdio first, HTTP later.** All MCP clients speak stdio; most local users will never need HTTP. Deferring HTTP means we don't have to answer auth, CORS, and deployment questions in v1.
8. **Legacy preserved, not deleted.** Users of the existing CLI shouldn't break. Moving the old runtime to `landlord/legacy/` is near-zero cost and lets us delete it cleanly once the MCP surface has parity.
