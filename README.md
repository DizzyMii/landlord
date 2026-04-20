# Landlord Framework

Contract-based agent orchestration, exposed as an MCP server.

A calling LLM (Claude Code, Cursor, Cline, or any MCP client) can hand Landlord a
natural-language task; Landlord decomposes it into a plan of parallel tenant agents,
returns the plan for review, launches the tenants as concurrent Claude Agent SDK
sessions, validates their checkpoints, evicts and retries misbehaving tenants, and
returns the per-role artifacts.

## Install

```bash
pip install -e .
```

Set the required environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Run the MCP server

```bash
landlord-mcp
```

This speaks MCP over stdio. Normally you don't run it directly — you point an MCP
client at it. For Claude Code, add this to your `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "landlord": {
      "command": "landlord-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "LANDLORD_OUTPUT_DIR": "./landlord-output"
      }
    }
  }
}
```

Restart Claude Code; the five Landlord tools will be discoverable to the model.

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
| `ANTHROPIC_API_KEY` | — | Required. |
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
