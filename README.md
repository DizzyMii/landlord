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

### Trust model

Tenants run with `permission_mode="bypassPermissions"` — the orchestrator is
autonomous, no human is present to approve prompts. Each tenant has:

- **Write/execute** access to its own sandbox: `<output_dir>/<job_id>/<tenant_id>/`
- **Read** access to the directory the MCP server was launched from (typically
  your project root) via `add_dirs=[cwd]`
- **Inherit-only** access to the rest of your filesystem — tenants can't leave
  their sandbox for writes unless they target absolute paths inside your project
  root, in which case writes go through. Claude Code's built-in sensitive-file
  protection (`.claude/`, system paths) still applies; tenants cannot
  self-authorize by editing `.claude/settings.json`.

In practice: for tasks that mutate your project code, tenants can do it. For
tasks that should stay sandboxed, point the MCP server at a scratch directory
via `LANDLORD_OUTPUT_DIR` and the blast radius is contained there.

### Watch it work

The fastest way is to type `landlord` in any terminal. You'll get a sleek
table of recent jobs with status, age, and prompt; pick one by row number
or id prefix and you drop straight into the live watch UI.

```bash
landlord                           # interactive launcher (jobs list → pick → watch)
landlord ls                        # one-shot list, no prompt
landlord watch <job_id>            # jump straight to a specific job
landlord rm <job_id>               # delete a job's output directory
```

For `landlord` to find your jobs from any directory, set:

```bash
setx LANDLORD_OUTPUT_DIR "C:/Users/<you>/Downloads/Projects/landlord-output"
```

The MCP server reads the same env var, so both writer and reader stay in sync.

For a direct invocation that skips the launcher:

```bash
landlord-watch <job_id>
```

You'll get rounded-border panels for each tenant with status glyphs, the most
recent checkpoint events, and a header showing the overall job status and
elapsed time. It auto-quits when the job reaches a terminal state. The UI
reads the job's `events.jsonl` + `job.json` + per-tenant `session.log` files
— no IPC with the MCP server, just tailing files. You can run multiple
watchers against the same job.

For the raw view, the underlying files are always readable:

```bash
tail -f ./landlord-output/<job_id>/job.json                   # orchestration state
tail -f ./landlord-output/<job_id>/events.jsonl                # structured event stream
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
