# Landlord

**Parallel Claude agents with contracts, not prompts.**

Landlord turns a single natural-language task into a plan of parallel Claude Agent
SDK sessions — each bound by a *contract* (objective, checkpoints, JSON-schema
outputs). Tenants that violate their contract get evicted and retried with fresh
context. Every checkpoint output is validated against a JSON Schema *and* a
structured LLM judge (via tool-use — no substring matching). Everything runs as
an MCP server over stdio, so any MCP client (Claude Code, Cursor, Cline) can
drive it.

### Why

- **No API credits required.** Drives `claude_agent_sdk.query()`, which honors
  `CLAUDE_CODE_OAUTH_TOKEN`. Your Claude Pro/Max subscription runs decompose,
  tenants, and the judge.
- **Contracts, not prompts.** Structured output enforced by JSON Schema + LLM
  judge on every checkpoint. No "I hope the model said PASS."
- **Tenants inherit your Claude Code config.** Skills, `CLAUDE.md`, hooks, user
  MCP servers — all available inside every tenant via `setting_sources=["user"]`
  and `skills="all"`.
- **5-tool MCP surface** — `start_orchestration`, `approve_plan`, `get_status`,
  `get_artifacts`, `cancel`. That's the whole API.
- **~1,200 LOC runtime, 52 tests.** Readable in an afternoon.

### 60-second install

```bash
pip install -e .
claude setup-token                       # one-time: get your OAuth token
setx CLAUDE_CODE_OAUTH_TOKEN "<paste>"   # Windows. Unix: export CLAUDE_CODE_OAUTH_TOKEN=...
claude mcp add -s user landlord landlord-mcp
```

Restart Claude Code. The five Landlord tools become discoverable; ask the model
to orchestrate something.

### Watch it work

Every tenant's SDK chatter streams to a tailable log:

```bash
tail -f ./landlord-output/<job_id>/job.json                   # orchestration state
tail -f ./landlord-output/<job_id>/<tenant_id>/session.log    # tenant model activity
ls  ./landlord-output/<job_id>/shared/                         # dependency artifacts
```

---

## Auth details

Authenticate against your Claude Pro/Max subscription (no API credits needed):

```bash
claude setup-token
```

Set the resulting token in your environment:

```bash
# Windows (persistent)
setx CLAUDE_CODE_OAUTH_TOKEN "<token>"

# bash/zsh
export CLAUDE_CODE_OAUTH_TOKEN=<token>
```

(Advanced: if you'd rather pay per-token API usage, set `ANTHROPIC_API_KEY`
instead — the underlying `claude-agent-sdk` accepts either.)

## Run the MCP server

```bash
landlord-mcp
```

This speaks MCP over stdio. Normally you don't run it directly — you point an MCP
client at it. Easiest is the `claude` CLI:

```bash
claude mcp add -s user landlord <path-to-landlord-mcp-executable>
```

Or add this to `~/.claude.json` (user scope) manually:

```json
{
  "mcpServers": {
    "landlord": {
      "command": "landlord-mcp"
    }
  }
}
```

Restart Claude Code; the five Landlord tools will be discoverable to the model.

## Tenant inheritance

Tenants spawned by the orchestrator run as Claude Agent SDK sessions with
`setting_sources=["user"]` and `skills="all"`. That means each tenant inherits:

- All user-level **skills** (invokable via the `Skill` tool)
- Your user `CLAUDE.md` (instructions/preferences)
- Your user-level MCP servers and hooks
- User memory

So a tenant can, for example, invoke `/superpowers:writing-plans` itself if
your orchestrator decomposes "build feature X" into a tenant that needs to
plan before coding. Per-contract skill allowlisting is a v2 feature; today
it's all-or-nothing.

## Tool surface

| Tool | Purpose |
|---|---|
| `start_orchestration(prompt, output_dir?)` | Decompose the prompt into a plan. Returns `job_id` and the plan awaiting approval. |
| `approve_plan(job_id, edits?)` | Approve (or replace with edits) the plan. Launches tenants. |
| `get_status(job_id)` | Poll overall status plus per-tenant state. |
| `get_artifacts(job_id)` | Retrieve final artifacts and file listings once the job is done/cancelled. |
| `cancel(job_id)` | Cancel a running or pending job. |

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | — | Required for Pro/Max users (from `claude setup-token`). |
| `ANTHROPIC_API_KEY` | — | Alternative to OAuth token; pay-per-use API billing. |
| `LANDLORD_LANDLORD_MODEL` | `claude-opus-4-7` | Decomposition + judge model. |
| `LANDLORD_TENANT_MODEL` | `claude-sonnet-4-6` | Tenant SDK session model. |
| `LANDLORD_OUTPUT_DIR` | `./landlord-output` | Root directory for job outputs. |
| `LANDLORD_MAX_RETRIES` | `3` | Default max retries per tenant. |

## Legacy CLI

The old litellm-based CLI is preserved as `landlord`:

```bash
pip install -e ".[legacy]"
landlord "your task"
```

See `landlord/legacy/` for source.

## Development

```bash
pip install -e ".[dev]"
pytest
```
