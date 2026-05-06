# Landlord on Flint — Design Spec

## Overview

Migrate Landlord from Python to TypeScript as `packages/landlord` inside the Flint monorepo. Landlord's LLM calls, tenant execution, and validation all run through Flint primitives. Tenants use Flint's `agent()` function with a manually-wired tool set. A `landlord/tools` subpath ships standard tools (bash, file, web) as plain Flint `tool()` definitions.

## Architecture

`packages/landlord` lives alongside `packages/flint`, `packages/graph`, and the adapters. It depends on `flint` as a workspace peer.

### Flint Primitive Mapping

| Flint primitive | Landlord use |
|---|---|
| `call()` | `decompose()` — forced `emit_plan` tool to get `Contract[]` from the LLM |
| `agent()` | `runTenant()` — agentic loop per tenant with checkpoint + user tools |
| `tool()` | Checkpoint tools auto-generated from Contract; standard tools |
| `validate()` | `validateCheckpoint()` — Zod tier + LLM semantic tier |
| `ProviderAdapter` | Passed through config — Landlord is provider-agnostic |
| `Budget` | Optional per-tenant spend limits |
| `Result<T>` | All return types throughout |

### File Layout

```
packages/landlord/
  src/
    contract.ts       # Contract, Checkpoint — Zod schemas + inferred types
    decompose.ts      # decompose(prompt, ctx) → Result<Contract[]>
    tenant.ts         # runTenant(contract, tools, ctx, ...) → Result<TenantResult>
    validate.ts       # validateCheckpoint(output, checkpoint, ctx) → Result<ValidationVerdict>
    orchestrate.ts    # orchestrate() — topological sort, parallel dispatch, retry
    tools/
      bash.ts         # bashTool
      file.ts         # fileReadTool, fileWriteTool
      web.ts          # webFetchTool
      index.ts        # standardTools barrel
    index.ts          # public API barrel
  package.json
  tsconfig.json
```

## Data Model

Zod schemas replace Pydantic. Zod implements `StandardSchemaV1` so checkpoint schemas plug directly into Flint's `validate()`.

```ts
const Checkpoint = z.object({
  name: z.string(),
  description: z.string(),
  schema: z.record(z.unknown()),  // JSON Schema passed to validate()
});

const Contract = z.object({
  tenantId: z.string().default(() => crypto.randomUUID().slice(0, 8)),
  role: z.string(),
  objective: z.string(),
  subPrompt: z.string(),
  checkpoints: z.array(Checkpoint),
  outputSchema: z.record(z.unknown()),
  toolsAllowed: z.array(z.string()).optional(),
  toolsDenied: z.array(z.string()).optional(),
  dependsOn: z.array(z.string()).default([]),
  maxRetries: z.number().default(3),
});

type Contract = z.infer<typeof Contract>;
type Checkpoint = z.infer<typeof Checkpoint>;
```

## Core Function Signatures

```ts
// decompose.ts
function decompose(
  prompt: string,
  ctx: { adapter: ProviderAdapter; model: string; budget?: Budget }
): Promise<Result<Contract[]>>

// tenant.ts — tools already resolved for this workDir
function runTenant(
  contract: Contract,
  tools: Tool[],
  ctx: { adapter: ProviderAdapter; model: string; budget?: Budget; workDir: string },
  retryContext?: string,
  sharedArtifacts?: Record<string, unknown>,
): Promise<Result<TenantResult>>

// orchestrate.ts
function orchestrate(
  prompt: string,
  tools: (workDir: string) => Tool[],
  config: OrchestratorConfig,
): Promise<Result<OrchestrateResult>>

type OrchestrateResult = {
  status: 'complete' | 'partial';
  tenants: Record<string, TenantResult>;
  artifacts: Record<string, Record<string, unknown>>;
}
```

```ts
type OrchestratorConfig = {
  adapter: ProviderAdapter;
  landlordModel: string;
  tenantModel: string;
  budget?: Budget;
  outputDir?: string;
  onEvent?: (event: LandlordEvent) => void;
};

type TenantResult =
  | { status: 'complete'; artifacts: Record<string, unknown> }
  | { status: 'escalated'; lastError: string; retriesExhausted: number };

type LandlordEvent =
  | { type: 'tenant_started'; role: string }
  | { type: 'checkpoint_passed'; role: string; checkpoint: string }
  | { type: 'checkpoint_failed'; role: string; checkpoint: string; reason: string }
  | { type: 'tenant_complete'; role: string }
  | { type: 'tenant_evicted'; role: string; reason: string; retry: number }
  | { type: 'tenant_escalated'; role: string }
  | { type: 'job_complete'; artifacts: Record<string, Record<string, unknown>> };
```

The Python `EventBus` pub/sub system is replaced by a simple `onEvent` callback — no separate machinery needed in a single-process TypeScript runtime.

## Orchestration Flow

### Dependency Gates

Each contract role gets a `Promise` that resolves when that tenant completes its final checkpoint. Dependents await the promises for their `dependsOn` roles before starting:

```ts
const gates = new Map<string, { resolve: (artifacts: unknown) => void; promise: Promise<unknown> }>();
for (const contract of plan) {
  let resolve!: (v: unknown) => void;
  const promise = new Promise(r => { resolve = r; });
  gates.set(contract.role, { resolve, promise });
}
```

### Retry Loop

Each contract runs through `runWithRetry()`, which owns the eviction/retry cycle:

```ts
async function runWithRetry(contract: Contract): Promise<TenantResult> {
  const sharedArtifacts = await collectDependencyArtifacts(contract.dependsOn, gates);
  let retryContext: string | undefined;

  for (let attempt = 0; attempt < contract.maxRetries; attempt++) {
    const result = await runTenant(contract, tools, ctx, retryContext, sharedArtifacts);
    if (result.ok && result.value.status === 'complete') {
      gates.get(contract.role)!.resolve(result.value.artifacts);
      return result.value;
    }
    retryContext = result.ok ? result.value.lastError : result.error.message;
    config.onEvent?.({ type: 'tenant_evicted', role: contract.role, reason: retryContext ?? 'unknown', retry: attempt + 1 });
  }

  config.onEvent?.({ type: 'tenant_escalated', role: contract.role });
  return { status: 'escalated', lastError: retryContext ?? 'unknown', retriesExhausted: contract.maxRetries };
}

const results = await Promise.all(plan.map(runWithRetry));
```

### Checkpoint Tool Loop

Inside `runTenant()`, checkpoint tools are auto-generated from `contract.checkpoints`. Each becomes a Flint `tool()` whose handler calls `validateCheckpoint()`. On pass, the artifact is recorded and the tool returns success. On fail, the tool returns the failure reason back into the `agent()` loop — the tenant self-corrects within the current attempt before any eviction occurs.

```
agent() loop
  → calls emit_checkpoint__data_ready({ rows: 42 })
    → validateCheckpoint() → fail: "missing schema field"
    → tool returns error string → agent self-corrects in next turn
  → calls emit_checkpoint__data_ready({ rows: 42, schema: {...} })
    → validateCheckpoint() → pass → artifact recorded
  → no more tool calls → agent returns → TenantResult: complete
```

## Validation

`validateCheckpoint()` is two-tier:

1. **Zod/JSON Schema** — parse the checkpoint output against `checkpoint.schema`
2. **LLM semantic judge** — if schema passes but correctness is ambiguous, a `call()` with a judge prompt returns pass/fail with explanation

Both tiers produce `Result<ValidationVerdict>` where `ValidationVerdict = { passed: boolean; explanation: string }`.

## Standard Tools

`landlord/tools` exports plain Flint `tool()` definitions. WorkDir is injected at runtime by `orchestrate()` — not baked into the tool definition.

Standard tools are factory functions — they receive `workDir` and return a `Tool`. The `standardTools` export is a convenience factory matching the `(workDir: string) => Tool[]` signature expected by `orchestrate()`:

```ts
export function bashTool(workDir: string): Tool       // shell commands, cwd = workDir
export function fileReadTool(workDir: string): Tool   // reads files relative to workDir
export function fileWriteTool(workDir: string): Tool  // writes files relative to workDir
export function webFetchTool(workDir: string): Tool   // HTTP GET, returns text body

export function standardTools(workDir: string): Tool[] {
  return [bashTool(workDir), fileReadTool(workDir), fileWriteTool(workDir), webFetchTool(workDir)];
}
```

`orchestrate()` creates a per-tenant subdirectory and calls `tools(tenantWorkDir)` when launching each tenant, so each agent gets a workDir-scoped tool set automatically.

File tools reject paths that escape workDir via path traversal check. `bashTool` sets `cwd` to workDir but does not further sandbox execution.

## Package Exports

```json
{
  "name": "landlord",
  "exports": {
    ".": "./src/index.ts",
    "./tools": "./src/tools/index.ts"
  }
}
```

## Usage Example

```ts
import { orchestrate } from 'landlord';
import { standardTools } from 'landlord/tools';
import { AnthropicAdapter } from '@flint/adapter-anthropic';

// standardTools matches (workDir: string) => Tool[] — orchestrate calls it per tenant
const result = await orchestrate(
  'Build a REST API with authentication and a test suite',
  standardTools,
  {
    adapter: new AnthropicAdapter({ apiKey: process.env.ANTHROPIC_API_KEY }),
    landlordModel: 'claude-opus-4-7',
    tenantModel: 'claude-sonnet-4-6',
    onEvent: (e) => console.log(e.type, e.role),
  }
);
```

## What's Not Included

- **CLI** — no CLI in this package. The Python CLI stays in the legacy repo. A `packages/landlord-cli` can be added later.
- **MCP server** — not ported in this iteration; can be added as `packages/landlord-mcp`.
- **REPL mode** — deferred.
- **Rich dashboard / renderer** — `onEvent` callback is the hook; a terminal UI is a separate consumer.
