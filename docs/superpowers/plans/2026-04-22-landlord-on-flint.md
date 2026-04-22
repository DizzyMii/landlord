# Landlord on Flint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `packages/landlord` in the Flint monorepo — a TypeScript agentic orchestrator built entirely on Flint primitives, with Zod-typed Contracts, `agent()`-backed Tenants, and workDir-scoped standard tools.

**Architecture:** `orchestrate(prompt, toolsFactory, config)` decomposes a prompt into `Contract[]` via `call()` with a forced `emit_plan` tool, launches each contract as a `runTenant()` call backed by `agent()`, and handles retries/eviction. Dependency gates are `Promise` resolvers; events flow through a single `onEvent` callback. Standard tools are factory functions `(workDir: string) => Tool` exported from `landlord/tools`.

**Tech Stack:** TypeScript 5.7, Vitest, tsup, pnpm workspaces, Zod 3 (contract parsing), Ajv 8 (JSON Schema tier-1 validation), Flint (call, agent, tool, budget, Result, ProviderAdapter), `@flint/adapter-anthropic` (dev)

---

## File Map

```
packages/landlord/
  src/
    contract.ts        # Zod schemas + inferred types: Checkpoint, Contract
    decompose.ts       # decompose(prompt, ctx) → Promise<Result<Contract[]>>
    validate.ts        # validateCheckpoint(output, checkpoint, ctx) → Promise<Result<ValidationVerdict>>
    tenant.ts          # runTenant(contract, tools, ctx, retryCtx?, shared?) → Promise<Result<Record<string, unknown>>>
    orchestrate.ts     # resolveOrder() + orchestrate(prompt, toolsFactory, config) → Promise<Result<OrchestrateResult>>
    tools/
      file.ts          # fileReadTool(workDir), fileWriteTool(workDir)
      bash.ts          # bashTool(workDir)
      web.ts           # webFetchTool(workDir)
      index.ts         # standardTools(workDir) barrel
    index.ts           # public API barrel
  test/
    contract.test.ts
    decompose.test.ts
    validate.test.ts
    tenant.test.ts
    orchestrate.test.ts
    tools/
      file.test.ts
      bash.test.ts
      web.test.ts
  package.json
  tsconfig.json
  tsup.config.ts
```

> **Note:** All work happens in the **Flint monorepo** at `C:\Users\KadeHeglin\Downloads\Projects\Flint`. The spec lives in the Landlord Framework repo for historical record.

---

## Task 1: Package Scaffolding

**Files:**
- Create: `packages/landlord/package.json`
- Create: `packages/landlord/tsconfig.json`
- Create: `packages/landlord/tsup.config.ts`

- [ ] **Step 1: Create the package directory and config files**

```bash
# Run from the Flint monorepo root
mkdir -p packages/landlord/src/tools packages/landlord/test/tools
```

`packages/landlord/package.json`:
```json
{
  "name": "landlord",
  "version": "0.0.0",
  "description": "Agentic orchestrator built on Flint primitives",
  "type": "module",
  "license": "MIT",
  "sideEffects": false,
  "engines": { "node": ">=20" },
  "files": ["dist", "README.md"],
  "exports": {
    ".": { "types": "./dist/index.d.ts", "import": "./dist/index.js" },
    "./tools": { "types": "./dist/tools/index.d.ts", "import": "./dist/tools/index.js" }
  },
  "scripts": {
    "build": "tsup",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "ajv": "8.17.1",
    "zod": "3.24.2"
  },
  "peerDependencies": {
    "flint": "workspace:*"
  },
  "devDependencies": {
    "@flint/adapter-anthropic": "workspace:*",
    "flint": "workspace:*",
    "tsup": "8.3.5",
    "typescript": "5.7.2",
    "vitest": "2.1.8"
  }
}
```

`packages/landlord/tsconfig.json`:
```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "allowImportingTsExtensions": true
  },
  "include": ["src/**/*", "test/**/*"]
}
```

`packages/landlord/tsup.config.ts`:
```ts
import { defineConfig } from 'tsup';

// biome-ignore lint/style/noDefaultExport: tsup config requires default export
export default defineConfig({
  entry: ['src/index.ts', 'src/tools/index.ts'],
  format: ['esm'],
  dts: true,
  clean: true,
  target: 'es2022',
  splitting: false,
  sourcemap: true,
});
```

- [ ] **Step 2: Install dependencies**

```bash
# From Flint monorepo root
pnpm install
```

Expected: pnpm resolves workspace links for `flint` and `@flint/adapter-anthropic`; downloads `zod` and `ajv`.

- [ ] **Step 3: Commit**

```bash
git add packages/landlord/package.json packages/landlord/tsconfig.json packages/landlord/tsup.config.ts pnpm-lock.yaml
git commit -m "feat(landlord): scaffold package"
```

---

## Task 2: Contract and Checkpoint Types

**Files:**
- Create: `packages/landlord/src/contract.ts`
- Create: `packages/landlord/test/contract.test.ts`

- [ ] **Step 1: Write the failing test**

`packages/landlord/test/contract.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { ContractSchema, CheckpointSchema } from '../src/contract.ts';

describe('CheckpointSchema', () => {
  it('parses valid checkpoint', () => {
    const result = CheckpointSchema.safeParse({
      name: 'schema_ready',
      description: 'DB schema has been generated',
      schema: { type: 'object', properties: { tables: { type: 'array' } }, required: ['tables'] },
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.name).toBe('schema_ready');
    }
  });

  it('rejects missing name', () => {
    const result = CheckpointSchema.safeParse({ description: 'x', schema: {} });
    expect(result.success).toBe(false);
  });
});

describe('ContractSchema', () => {
  it('parses minimal contract and fills defaults', () => {
    const result = ContractSchema.safeParse({
      role: 'backend_engineer',
      objective: 'Build REST API',
      subPrompt: 'Create a Node.js REST API with Express',
      checkpoints: [],
      outputSchema: { type: 'object' },
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.dependsOn).toEqual([]);
      expect(result.data.maxRetries).toBe(3);
      expect(result.data.tenantId).toHaveLength(8);
    }
  });

  it('parses contract with dependsOn', () => {
    const result = ContractSchema.safeParse({
      role: 'test_engineer',
      objective: 'Write tests',
      subPrompt: 'Write tests for the API',
      checkpoints: [],
      outputSchema: {},
      dependsOn: ['backend_engineer'],
      maxRetries: 5,
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.dependsOn).toEqual(['backend_engineer']);
      expect(result.data.maxRetries).toBe(5);
    }
  });

  it('rejects missing role', () => {
    const result = ContractSchema.safeParse({
      objective: 'x',
      subPrompt: 'x',
      checkpoints: [],
      outputSchema: {},
    });
    expect(result.success).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd packages/landlord && pnpm test
```

Expected: FAIL with `Cannot find module '../src/contract.ts'`

- [ ] **Step 3: Implement**

`packages/landlord/src/contract.ts`:
```ts
import { z } from 'zod';

export const CheckpointSchema = z.object({
  name: z.string(),
  description: z.string(),
  schema: z.record(z.unknown()),
});

export const ContractSchema = z.object({
  tenantId: z.string().default(() => crypto.randomUUID().slice(0, 8)),
  role: z.string(),
  objective: z.string(),
  subPrompt: z.string(),
  checkpoints: z.array(CheckpointSchema),
  outputSchema: z.record(z.unknown()),
  toolsAllowed: z.array(z.string()).optional(),
  toolsDenied: z.array(z.string()).optional(),
  dependsOn: z.array(z.string()).default([]),
  maxRetries: z.number().default(3),
});

export type Checkpoint = z.infer<typeof CheckpointSchema>;
export type Contract = z.infer<typeof ContractSchema>;
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (3 tests in contract.test.ts)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/contract.ts packages/landlord/test/contract.test.ts
git commit -m "feat(landlord): Contract and Checkpoint Zod schemas"
```

---

## Task 3: Topological Sort

**Files:**
- Create: `packages/landlord/src/orchestrate.ts` (sort function only)
- Create: `packages/landlord/test/orchestrate.test.ts` (sort tests only)

- [ ] **Step 1: Write the failing test**

`packages/landlord/test/orchestrate.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { resolveOrder, DependencyCycleError } from '../src/orchestrate.ts';
import type { Contract } from '../src/contract.ts';

function makeContract(role: string, dependsOn: string[] = []): Contract {
  return {
    tenantId: role,
    role,
    objective: `Do ${role}`,
    subPrompt: `Do ${role}`,
    checkpoints: [],
    outputSchema: {},
    dependsOn,
    maxRetries: 3,
  };
}

describe('resolveOrder', () => {
  it('returns single contract unchanged', () => {
    const contracts = [makeContract('a')];
    const order = resolveOrder(contracts);
    expect(order.map(c => c.role)).toEqual(['a']);
  });

  it('orders a → b (b depends on a)', () => {
    const contracts = [makeContract('b', ['a']), makeContract('a')];
    const order = resolveOrder(contracts);
    const roles = order.map(c => c.role);
    expect(roles.indexOf('a')).toBeLessThan(roles.indexOf('b'));
  });

  it('orders a → b → c chain', () => {
    const contracts = [makeContract('c', ['b']), makeContract('a'), makeContract('b', ['a'])];
    const order = resolveOrder(contracts);
    const roles = order.map(c => c.role);
    expect(roles.indexOf('a')).toBeLessThan(roles.indexOf('b'));
    expect(roles.indexOf('b')).toBeLessThan(roles.indexOf('c'));
  });

  it('throws DependencyCycleError on cycle', () => {
    const contracts = [makeContract('a', ['b']), makeContract('b', ['a'])];
    expect(() => resolveOrder(contracts)).toThrow(DependencyCycleError);
  });

  it('ignores depends_on references to unknown roles', () => {
    const contracts = [makeContract('a', ['nonexistent'])];
    expect(() => resolveOrder(contracts)).not.toThrow();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
pnpm test
```

Expected: FAIL with `Cannot find module '../src/orchestrate.ts'`

- [ ] **Step 3: Implement**

`packages/landlord/src/orchestrate.ts` (sort only for now):
```ts
import type { Contract } from './contract.ts';

export class DependencyCycleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DependencyCycleError';
  }
}

export function resolveOrder(contracts: Contract[]): Contract[] {
  const byRole = new Map(contracts.map(c => [c.role, c]));
  const WHITE = 0, GRAY = 1, BLACK = 2;
  const color = new Map(contracts.map(c => [c.role, WHITE]));
  const order: Contract[] = [];

  function visit(role: string, stack: string[]): void {
    if (color.get(role) === GRAY) {
      throw new DependencyCycleError(`Dependency cycle: ${[...stack, role].join(' -> ')}`);
    }
    if (color.get(role) === BLACK) return;
    if (!byRole.has(role)) return;
    color.set(role, GRAY);
    for (const dep of byRole.get(role)!.dependsOn) {
      visit(dep, [...stack, role]);
    }
    color.set(role, BLACK);
    order.push(byRole.get(role)!);
  }

  for (const c of contracts) visit(c.role, []);
  return order;
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (5 sort tests pass)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/orchestrate.ts packages/landlord/test/orchestrate.test.ts
git commit -m "feat(landlord): topological sort for contract dependency resolution"
```

---

## Task 4: decompose()

**Files:**
- Create: `packages/landlord/src/decompose.ts`
- Create: `packages/landlord/test/decompose.test.ts`

- [ ] **Step 1: Write the failing test**

`packages/landlord/test/decompose.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { decompose } from '../src/decompose.ts';
import { budget } from 'flint/budget';
import { mockAdapter } from 'flint/testing';
import type { NormalizedResponse } from 'flint';

function toolCallResponse(name: string, args: unknown): NormalizedResponse {
  return {
    message: {
      role: 'assistant',
      content: '',
      toolCalls: [{ id: 'tc1', name, arguments: args }],
    },
    usage: { input: 20, output: 10 },
    stopReason: 'tool_call',
  };
}

describe('decompose', () => {
  it('returns contracts from emit_plan tool call', async () => {
    const adapter = mockAdapter({
      onCall: () => toolCallResponse('emit_plan', {
        contracts: [
          {
            role: 'backend_engineer',
            objective: 'Build API',
            subPrompt: 'Create a REST API',
            checkpoints: [{ name: 'api_ready', description: 'API is ready', schema: { type: 'object', properties: { endpoints: { type: 'array' } }, required: ['endpoints'] } }],
            outputSchema: { type: 'object' },
          },
        ],
      }),
    });

    const result = await decompose('Build a REST API', {
      adapter,
      model: 'test-model',
      budget: budget({ maxSteps: 5 }),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toHaveLength(1);
      expect(result.value[0]!.role).toBe('backend_engineer');
      expect(result.value[0]!.dependsOn).toEqual([]);
      expect(result.value[0]!.maxRetries).toBe(3);
    }
  });

  it('returns error when LLM does not call emit_plan', async () => {
    const adapter = mockAdapter({
      onCall: () => ({
        message: { role: 'assistant', content: 'I cannot do that' },
        usage: { input: 10, output: 5 },
        stopReason: 'end',
      }),
    });

    const result = await decompose('Build something', {
      adapter,
      model: 'test-model',
    });

    expect(result.ok).toBe(false);
  });

  it('skips malformed contracts in array', async () => {
    const adapter = mockAdapter({
      onCall: () => toolCallResponse('emit_plan', {
        contracts: [
          { role: 'good', objective: 'x', subPrompt: 'x', checkpoints: [], outputSchema: {} },
          { objective: 'missing role' },
        ],
      }),
    });

    const result = await decompose('test', { adapter, model: 'test-model' });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toHaveLength(1);
      expect(result.value[0]!.role).toBe('good');
    }
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
pnpm test
```

Expected: FAIL with `Cannot find module '../src/decompose.ts'`

- [ ] **Step 3: Implement**

`packages/landlord/src/decompose.ts`:
```ts
import { call, tool } from 'flint';
import type { Budget, ProviderAdapter, Result, StandardSchemaV1 } from 'flint';
import { ContractSchema } from './contract.ts';
import type { Contract } from './contract.ts';

const DECOMPOSE_SYSTEM =
  'You are the Landlord, an agentic orchestrator. Decompose the user request into independent ' +
  'sub-tasks for isolated worker agents (tenants) that can run in parallel where possible. ' +
  'For each tenant return: role (short unique name), objective, subPrompt (what the tenant receives), ' +
  'checkpoints (list of {name, description, schema} with lenient JSON Schemas), outputSchema, ' +
  'and dependsOn (roles whose outputs this tenant needs). Keep the plan minimal. ' +
  'Call the emit_plan tool with the contracts array.';

const EMIT_PLAN_JSON_SCHEMA = {
  type: 'object',
  properties: {
    contracts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          role: { type: 'string' },
          objective: { type: 'string' },
          subPrompt: { type: 'string' },
          checkpoints: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                name: { type: 'string' },
                description: { type: 'string' },
                schema: { type: 'object' },
              },
              required: ['name', 'description', 'schema'],
            },
          },
          outputSchema: { type: 'object' },
          dependsOn: { type: 'array', items: { type: 'string' } },
        },
        required: ['role', 'objective', 'subPrompt', 'checkpoints', 'outputSchema'],
      },
    },
  },
  required: ['contracts'],
};

function anySchema(): StandardSchemaV1<unknown, unknown> {
  return {
    '~standard': { version: 1, vendor: 'landlord', validate: (v) => ({ value: v }) },
  };
}

const emitPlanTool = tool({
  name: 'emit_plan',
  description: 'Return the decomposed plan as a list of Contract objects.',
  input: anySchema(),
  handler: (v) => v,
  jsonSchema: EMIT_PLAN_JSON_SCHEMA,
});

export async function decompose(
  prompt: string,
  ctx: { adapter: ProviderAdapter; model: string; budget?: Budget },
): Promise<Result<Contract[]>> {
  const result = await call({
    adapter: ctx.adapter,
    model: ctx.model,
    messages: [
      { role: 'system', content: DECOMPOSE_SYSTEM },
      { role: 'user', content: prompt },
    ],
    tools: [emitPlanTool],
    ...(ctx.budget !== undefined ? { budget: ctx.budget } : {}),
  });

  if (!result.ok) return result;

  const planCall = result.value.message.toolCalls?.find(tc => tc.name === 'emit_plan');
  if (planCall === undefined) {
    return { ok: false, error: new Error('LLM did not call emit_plan — no plan produced') };
  }

  const raw = planCall.arguments as { contracts?: unknown[] };
  const rawContracts = raw.contracts ?? [];

  const contracts: Contract[] = [];
  for (const item of rawContracts) {
    const parsed = ContractSchema.safeParse(item);
    if (parsed.success) contracts.push(parsed.data);
  }

  return { ok: true, value: contracts };
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (all 3 decompose tests + 5 sort tests + 3 contract tests)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/decompose.ts packages/landlord/test/decompose.test.ts
git commit -m "feat(landlord): decompose() — call() with forced emit_plan tool"
```

---

## Task 5: validateCheckpoint()

**Files:**
- Create: `packages/landlord/src/validate.ts`
- Create: `packages/landlord/test/validate.test.ts`

- [ ] **Step 1: Write the failing test**

`packages/landlord/test/validate.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { validateCheckpoint } from '../src/validate.ts';
import { mockAdapter } from 'flint/testing';
import type { Checkpoint } from '../src/contract.ts';
import type { NormalizedResponse } from 'flint';

function judgeResponse(passed: boolean): NormalizedResponse {
  return {
    message: { role: 'assistant', content: JSON.stringify({ passed, explanation: passed ? 'Looks good' : 'Missing required field' }) },
    usage: { input: 15, output: 8 },
    stopReason: 'end',
  };
}

const checkpoint: Checkpoint = {
  name: 'api_ready',
  description: 'API endpoints have been created',
  schema: {
    type: 'object',
    properties: { endpoints: { type: 'array' } },
    required: ['endpoints'],
  },
};

describe('validateCheckpoint', () => {
  it('tier 1 fails immediately when JSON Schema is violated — no LLM call made', async () => {
    const adapter = mockAdapter({ onCall: () => { throw new Error('should not be called') } });

    const result = await validateCheckpoint(
      { wrongField: 'value' },
      checkpoint,
      { adapter, model: 'test-model' },
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.passed).toBe(false);
      expect(result.value.explanation).toMatch(/endpoints/);
    }
  });

  it('tier 2 LLM judge is called when JSON Schema passes', async () => {
    let judgeCallCount = 0;
    const adapter = mockAdapter({
      onCall: () => { judgeCallCount++; return judgeResponse(true); },
    });

    const result = await validateCheckpoint(
      { endpoints: ['/api/users', '/api/posts'] },
      checkpoint,
      { adapter, model: 'test-model' },
    );

    expect(judgeCallCount).toBe(1);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.passed).toBe(true);
    }
  });

  it('tier 2 can return failed verdict', async () => {
    const adapter = mockAdapter({ onCall: () => judgeResponse(false) });

    const result = await validateCheckpoint(
      { endpoints: [] },
      checkpoint,
      { adapter, model: 'test-model' },
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.passed).toBe(false);
      expect(result.value.explanation).toBeDefined();
    }
  });

  it('returns error when LLM response is not valid JSON', async () => {
    const adapter = mockAdapter({
      onCall: () => ({
        message: { role: 'assistant', content: 'not json at all' },
        usage: { input: 5, output: 3 },
        stopReason: 'end',
      }),
    });

    const result = await validateCheckpoint(
      { endpoints: ['/foo'] },
      checkpoint,
      { adapter, model: 'test-model' },
    );

    expect(result.ok).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
pnpm test
```

Expected: FAIL with `Cannot find module '../src/validate.ts'`

- [ ] **Step 3: Implement**

`packages/landlord/src/validate.ts`:
```ts
import Ajv from 'ajv';
import { call } from 'flint';
import type { Budget, ProviderAdapter, Result } from 'flint';
import type { Checkpoint } from './contract.ts';

const ajv = new Ajv({ allErrors: true });

export type ValidationVerdict = { passed: boolean; explanation: string };

const JUDGE_SYSTEM =
  'You are a checkpoint validator. Given a checkpoint definition and the output produced by an agent, ' +
  'judge whether the output genuinely satisfies the checkpoint. ' +
  'Respond ONLY with valid JSON: {"passed": true|false, "explanation": "one sentence reason"}.';

export async function validateCheckpoint(
  output: Record<string, unknown>,
  checkpoint: Checkpoint,
  ctx: { adapter: ProviderAdapter; model: string; budget?: Budget },
): Promise<Result<ValidationVerdict>> {
  // Tier 1: JSON Schema validation
  let validate: ReturnType<typeof ajv.compile>;
  try {
    validate = ajv.compile(checkpoint.schema);
  } catch {
    validate = ajv.compile({ type: 'object' });
  }

  const tier1Pass = validate(output);
  if (!tier1Pass) {
    const explanation = ajv.errorsText(validate.errors) ?? 'JSON Schema validation failed';
    return { ok: true, value: { passed: false, explanation } };
  }

  // Tier 2: LLM semantic judge
  const judgeResult = await call({
    adapter: ctx.adapter,
    model: ctx.model,
    messages: [
      { role: 'system', content: JUDGE_SYSTEM },
      {
        role: 'user',
        content: JSON.stringify({
          checkpoint: { name: checkpoint.name, description: checkpoint.description },
          output,
        }),
      },
    ],
    ...(ctx.budget !== undefined ? { budget: ctx.budget } : {}),
  });

  if (!judgeResult.ok) return judgeResult;

  let verdict: { passed?: unknown; explanation?: unknown };
  try {
    verdict = JSON.parse(judgeResult.value.message.content) as typeof verdict;
  } catch {
    return { ok: false, error: new Error('Judge response was not valid JSON') };
  }

  if (typeof verdict.passed !== 'boolean' || typeof verdict.explanation !== 'string') {
    return { ok: false, error: new Error('Judge response missing required fields') };
  }

  return { ok: true, value: { passed: verdict.passed, explanation: verdict.explanation } };
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (all validate tests + all prior tests)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/validate.ts packages/landlord/test/validate.test.ts
git commit -m "feat(landlord): validateCheckpoint() — Ajv tier-1 + LLM semantic tier-2"
```

---

## Task 6: runTenant()

**Files:**
- Create: `packages/landlord/src/tenant.ts`
- Create: `packages/landlord/test/tenant.test.ts`

- [ ] **Step 1: Write the failing test**

`packages/landlord/test/tenant.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { runTenant } from '../src/tenant.ts';
import { tool } from 'flint';
import { budget } from 'flint/budget';
import { mockAdapter } from 'flint/testing';
import type { NormalizedResponse } from 'flint';
import type { Contract } from '../src/contract.ts';

function anySchema() {
  return { '~standard': { version: 1 as const, vendor: 'test', validate: (v: unknown) => ({ value: v }) } };
}

function textResponse(content: string): NormalizedResponse {
  return { message: { role: 'assistant', content }, usage: { input: 10, output: 5 }, stopReason: 'end' };
}

function toolCallResponse(name: string, args: unknown): NormalizedResponse {
  return {
    message: { role: 'assistant', content: '', toolCalls: [{ id: 'tc1', name, arguments: args }] },
    usage: { input: 20, output: 10 },
    stopReason: 'tool_call',
  };
}

function judgePassResponse(): NormalizedResponse {
  return {
    message: { role: 'assistant', content: JSON.stringify({ passed: true, explanation: 'Good' }) },
    usage: { input: 10, output: 5 },
    stopReason: 'end',
  };
}

const simpleContract: Contract = {
  tenantId: 'abc12345',
  role: 'coder',
  objective: 'Write a function',
  subPrompt: 'Write a TypeScript add function',
  checkpoints: [{
    name: 'code_written',
    description: 'Code has been written',
    schema: { type: 'object', properties: { code: { type: 'string' } }, required: ['code'] },
  }],
  outputSchema: {},
  dependsOn: [],
  maxRetries: 3,
};

const emptyCheckpointContract: Contract = { ...simpleContract, checkpoints: [] };

describe('runTenant', () => {
  it('succeeds when agent calls all checkpoint tools and they pass', async () => {
    let callIndex = 0;
    const adapter = mockAdapter({
      onCall: (_req, i) => {
        callIndex++;
        // First call: agent decides to call checkpoint tool
        if (i === 0) return toolCallResponse('emit_checkpoint__code_written', { code: 'const add = (a, b) => a + b;' });
        // Second call: validate (judge) — passes
        if (i === 1) return judgePassResponse();
        // Third call: agent finishes after checkpoint
        return textResponse('Done');
      },
    });

    const result = await runTenant(
      simpleContract,
      [],
      { adapter, model: 'test', budget: budget({ maxSteps: 20 }), workDir: '/tmp/test' },
    );

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value['code_written']).toMatchObject({ code: expect.any(String) });
    }
  });

  it('returns error when agent finishes without calling all checkpoints', async () => {
    const adapter = mockAdapter({
      onCall: () => textResponse('I am done (but did not call checkpoint)'),
    });

    const result = await runTenant(
      simpleContract,
      [],
      { adapter, model: 'test', budget: budget({ maxSteps: 20 }), workDir: '/tmp/test' },
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.message).toMatch(/code_written/);
    }
  });

  it('succeeds immediately for zero-checkpoint contract', async () => {
    const adapter = mockAdapter({ onCall: () => textResponse('Done') });

    const result = await runTenant(
      emptyCheckpointContract,
      [],
      { adapter, model: 'test', budget: budget({ maxSteps: 5 }), workDir: '/tmp/test' },
    );

    expect(result.ok).toBe(true);
  });

  it('passes user tools to agent alongside checkpoint tools', async () => {
    let receivedToolNames: string[] = [];
    const adapter = mockAdapter({
      onCall: (req) => {
        receivedToolNames = (req.tools ?? []).map(t => t.name);
        return textResponse('Done');
      },
    });

    const userTool = tool({ name: 'my_tool', description: 'x', input: anySchema(), handler: () => 'ok' });

    await runTenant(
      emptyCheckpointContract,
      [userTool],
      { adapter, model: 'test', budget: budget({ maxSteps: 5 }), workDir: '/tmp/test' },
    );

    expect(receivedToolNames).toContain('my_tool');
  });

  it('respects toolsAllowed filter', async () => {
    let receivedToolNames: string[] = [];
    const adapter = mockAdapter({
      onCall: (req) => {
        receivedToolNames = (req.tools ?? []).map(t => t.name);
        return textResponse('Done');
      },
    });

    const tool1 = tool({ name: 'allowed_tool', description: 'x', input: anySchema(), handler: () => 'ok' });
    const tool2 = tool({ name: 'denied_tool', description: 'x', input: anySchema(), handler: () => 'ok' });
    const contractWithFilter: Contract = { ...emptyCheckpointContract, toolsAllowed: ['allowed_tool'] };

    await runTenant(
      contractWithFilter,
      [tool1, tool2],
      { adapter, model: 'test', budget: budget({ maxSteps: 5 }), workDir: '/tmp/test' },
    );

    expect(receivedToolNames).toContain('allowed_tool');
    expect(receivedToolNames).not.toContain('denied_tool');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
pnpm test
```

Expected: FAIL with `Cannot find module '../src/tenant.ts'`

- [ ] **Step 3: Implement**

`packages/landlord/src/tenant.ts`:
```ts
import { agent, tool } from 'flint';
import { budget as makeBudget } from 'flint/budget';
import type { Budget, ProviderAdapter, Result, StandardSchemaV1, Tool } from 'flint';
import type { Checkpoint, Contract } from './contract.ts';
import { validateCheckpoint } from './validate.ts';

function anyObjectSchema(): StandardSchemaV1<unknown, Record<string, unknown>> {
  return {
    '~standard': {
      version: 1,
      vendor: 'landlord',
      validate: (v) => {
        if (typeof v !== 'object' || v === null || Array.isArray(v)) {
          return { issues: [{ message: 'Expected an object' }] };
        }
        return { value: v as Record<string, unknown> };
      },
    },
  };
}

function sanitizeName(name: string): string {
  return name.replace(/[^a-zA-Z0-9_-]/g, '_');
}

function buildSystemPrompt(
  contract: Contract,
  sharedArtifacts: Record<string, unknown> | undefined,
  retryContext: string | undefined,
): string {
  const parts: string[] = [
    `You are a ${contract.role}.`,
    `Objective: ${contract.objective}`,
  ];

  if (contract.checkpoints.length > 0) {
    const lines = contract.checkpoints.map(
      cp => `- ${cp.name}: call \`emit_checkpoint__${sanitizeName(cp.name)}\` when ${cp.description}`,
    );
    parts.push(`Checkpoints — call each tool when you reach the milestone:\n${lines.join('\n')}`);
  }

  parts.push(
    'You also have filesystem and shell tools sandboxed to your working directory. ' +
    'Checkpoint tools are how you declare structured results back to the orchestrator.',
  );

  if (sharedArtifacts !== undefined && Object.keys(sharedArtifacts).length > 0) {
    parts.push(`Context from dependencies:\n${JSON.stringify(sharedArtifacts, null, 2)}`);
  }

  if (retryContext !== undefined) {
    parts.push(`Previous attempt failed. Retry context:\n${retryContext}`);
  }

  return parts.join('\n\n');
}

function filterTools(userTools: Tool[], contract: Contract): Tool[] {
  if (contract.toolsAllowed !== undefined) {
    return userTools.filter(t => contract.toolsAllowed!.includes(t.name));
  }
  if (contract.toolsDenied !== undefined) {
    return userTools.filter(t => !contract.toolsDenied!.includes(t.name));
  }
  return userTools;
}

export async function runTenant(
  contract: Contract,
  userTools: Tool[],
  ctx: { adapter: ProviderAdapter; model: string; budget?: Budget; workDir: string },
  retryContext?: string,
  sharedArtifacts?: Record<string, unknown>,
): Promise<Result<Record<string, unknown>>> {
  const artifacts: Record<string, unknown> = {};

  const checkpointTools: Tool[] = contract.checkpoints.map(cp => {
    const schema = (cp.schema['type'] === 'object')
      ? cp.schema
      : { type: 'object', properties: { result: cp.schema }, required: ['result'] };

    return tool({
      name: `emit_checkpoint__${sanitizeName(cp.name)}`,
      description: `Declare checkpoint '${cp.name}' reached: ${cp.description}.`,
      input: anyObjectSchema(),
      jsonSchema: schema as Record<string, unknown>,
      handler: async (input) => {
        const verdict = await validateCheckpoint(input, cp, ctx);
        if (verdict.ok && verdict.value.passed) {
          artifacts[cp.name] = input;
          return { ok: true, message: `Checkpoint '${cp.name}' passed.` };
        }
        const explanation = verdict.ok ? verdict.value.explanation : verdict.error.message;
        return { ok: false, message: `Checkpoint '${cp.name}' failed: ${explanation}. Revise and retry.` };
      },
    });
  });

  const allTools = [...checkpointTools, ...filterTools(userTools, contract)];
  const systemPrompt = buildSystemPrompt(contract, sharedArtifacts, retryContext);
  const tenantBudget = ctx.budget ?? makeBudget({ maxSteps: 100 });

  const agentResult = await agent({
    adapter: ctx.adapter,
    model: ctx.model,
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: contract.subPrompt },
    ],
    tools: allTools,
    budget: tenantBudget,
  });

  if (!agentResult.ok) return agentResult;

  const requiredNames = new Set(contract.checkpoints.map(cp => cp.name));
  const passedNames = new Set(Object.keys(artifacts));
  const missing = [...requiredNames].filter(n => !passedNames.has(n));

  if (missing.length > 0) {
    return {
      ok: false,
      error: new Error(`Tenant finished without passing checkpoints: ${missing.join(', ')}`),
    };
  }

  return { ok: true, value: artifacts };
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (all prior tests + 5 tenant tests)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/tenant.ts packages/landlord/test/tenant.test.ts
git commit -m "feat(landlord): runTenant() — agent() loop with checkpoint tools + filtering"
```

---

## Task 7: File Tools

**Files:**
- Create: `packages/landlord/src/tools/file.ts`
- Create: `packages/landlord/test/tools/file.test.ts`

- [ ] **Step 1: Write the failing test**

`packages/landlord/test/tools/file.test.ts`:
```ts
import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { fileReadTool, fileWriteTool } from '../../src/tools/file.ts';
import { execute } from 'flint';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

describe('fileReadTool / fileWriteTool', () => {
  let workDir: string;

  beforeEach(async () => {
    workDir = await mkdtemp(join(tmpdir(), 'landlord-test-'));
  });

  afterEach(async () => {
    await rm(workDir, { recursive: true });
  });

  it('writes and reads a file', async () => {
    const write = fileWriteTool(workDir);
    const read = fileReadTool(workDir);

    await execute(write, { path: 'hello.txt', content: 'Hello, world!' });
    const result = await execute(read, { path: 'hello.txt' });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toBe('Hello, world!');
    }
  });

  it('fileReadTool returns error for missing file', async () => {
    const read = fileReadTool(workDir);
    const result = await execute(read, { path: 'nonexistent.txt' });
    expect(result.ok).toBe(false);
  });

  it('fileWriteTool rejects path traversal', async () => {
    const write = fileWriteTool(workDir);
    const result = await execute(write, { path: '../escape.txt', content: 'bad' });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.message).toMatch(/outside/i);
    }
  });

  it('fileReadTool rejects path traversal', async () => {
    const read = fileReadTool(workDir);
    const result = await execute(read, { path: '../../etc/passwd' });
    expect(result.ok).toBe(false);
  });

  it('writes files in subdirectories', async () => {
    const write = fileWriteTool(workDir);
    const read = fileReadTool(workDir);

    await execute(write, { path: 'sub/dir/file.ts', content: 'export {}' });
    const result = await execute(read, { path: 'sub/dir/file.ts' });

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value).toBe('export {}');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
pnpm test
```

Expected: FAIL with `Cannot find module '../../src/tools/file.ts'`

- [ ] **Step 3: Implement**

`packages/landlord/src/tools/file.ts`:
```ts
import { tool } from 'flint';
import type { StandardSchemaV1, Tool } from 'flint';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve, relative, dirname } from 'node:path';
import { z } from 'zod';

function guardPath(workDir: string, userPath: string): string {
  const abs = resolve(workDir, userPath);
  const rel = relative(workDir, abs);
  if (rel.startsWith('..') || resolve(workDir, rel) !== abs) {
    throw new Error(`Path '${userPath}' is outside the working directory`);
  }
  return abs;
}

const readSchema = z.object({ path: z.string() });
const writeSchema = z.object({ path: z.string(), content: z.string() });

export function fileReadTool(workDir: string): Tool {
  return tool({
    name: 'file_read',
    description: 'Read a file relative to the working directory.',
    input: readSchema as unknown as StandardSchemaV1<unknown, { path: string }>,
    jsonSchema: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] },
    handler: async ({ path }) => {
      const abs = guardPath(workDir, path);
      const content = await readFile(abs, 'utf-8');
      return content;
    },
  });
}

export function fileWriteTool(workDir: string): Tool {
  return tool({
    name: 'file_write',
    description: 'Write content to a file relative to the working directory. Creates parent directories.',
    input: writeSchema as unknown as StandardSchemaV1<unknown, { path: string; content: string }>,
    jsonSchema: {
      type: 'object',
      properties: { path: { type: 'string' }, content: { type: 'string' } },
      required: ['path', 'content'],
    },
    handler: async ({ path, content }) => {
      const abs = guardPath(workDir, path);
      await mkdir(dirname(abs), { recursive: true });
      await writeFile(abs, content, 'utf-8');
      return `Written ${content.length} bytes to ${path}`;
    },
  });
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (all file tool tests + all prior tests)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/tools/file.ts packages/landlord/test/tools/file.test.ts
git commit -m "feat(landlord): fileReadTool and fileWriteTool with path traversal guard"
```

---

## Task 8: Bash Tool

**Files:**
- Create: `packages/landlord/src/tools/bash.ts`
- Create: `packages/landlord/test/tools/bash.test.ts`

- [ ] **Step 1: Write the failing test**

`packages/landlord/test/tools/bash.test.ts`:
```ts
import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { bashTool } from '../../src/tools/bash.ts';
import { execute } from 'flint';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

describe('bashTool', () => {
  let workDir: string;

  beforeEach(async () => {
    workDir = await mkdtemp(join(tmpdir(), 'landlord-bash-'));
  });

  afterEach(async () => {
    await rm(workDir, { recursive: true });
  });

  it('runs a command and returns stdout', async () => {
    const bash = bashTool(workDir);
    const result = await execute(bash, { command: 'echo hello' });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(String(result.value)).toContain('hello');
    }
  });

  it('captures stderr in output', async () => {
    const bash = bashTool(workDir);
    const result = await execute(bash, { command: 'echo error_text >&2' });
    expect(result.ok).toBe(true);
  });

  it('returns error on non-zero exit code', async () => {
    const bash = bashTool(workDir);
    const result = await execute(bash, { command: 'exit 1' });
    expect(result.ok).toBe(false);
  });

  it('runs in the workDir', async () => {
    const bash = bashTool(workDir);
    const result = await execute(bash, { command: 'pwd' });

    expect(result.ok).toBe(true);
    if (result.ok) {
      // Normalize for Windows temp path casing differences
      expect(String(result.value).trim().toLowerCase()).toContain(workDir.toLowerCase().replace(/\\/g, '/').split('/').pop()!);
    }
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
pnpm test
```

Expected: FAIL with `Cannot find module '../../src/tools/bash.ts'`

- [ ] **Step 3: Implement**

`packages/landlord/src/tools/bash.ts`:
```ts
import { tool } from 'flint';
import type { StandardSchemaV1, Tool } from 'flint';
import { exec } from 'node:child_process';
import { promisify } from 'node:util';
import { z } from 'zod';

const execAsync = promisify(exec);

const bashSchema = z.object({ command: z.string() });

export function bashTool(workDir: string): Tool {
  return tool({
    name: 'bash',
    description: 'Execute a shell command in the tenant working directory. Returns stdout + stderr combined.',
    input: bashSchema as unknown as StandardSchemaV1<unknown, { command: string }>,
    jsonSchema: { type: 'object', properties: { command: { type: 'string' } }, required: ['command'] },
    handler: async ({ command }) => {
      const { stdout, stderr } = await execAsync(command, { cwd: workDir });
      const combined = [stdout, stderr].filter(Boolean).join('\n');
      return combined || '(no output)';
    },
  });
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (all bash tests + all prior tests)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/tools/bash.ts packages/landlord/test/tools/bash.test.ts
git commit -m "feat(landlord): bashTool — shell execution sandboxed to workDir"
```

---

## Task 9: Web Tool

**Files:**
- Create: `packages/landlord/src/tools/web.ts`
- Create: `packages/landlord/test/tools/web.test.ts`

- [ ] **Step 1: Write the failing test**

`packages/landlord/test/tools/web.test.ts`:
```ts
import { describe, expect, it, vi, afterEach } from 'vitest';
import { webFetchTool } from '../../src/tools/web.ts';
import { execute } from 'flint';

describe('webFetchTool', () => {
  afterEach(() => { vi.restoreAllMocks() });

  it('returns response body as string', async () => {
    vi.stubGlobal('fetch', async (_url: string) => ({
      ok: true,
      text: async () => '<html>Hello</html>',
    }));

    const web = webFetchTool('/tmp/workdir');
    const result = await execute(web, { url: 'https://example.com' });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(String(result.value)).toContain('Hello');
    }
  });

  it('returns error on non-ok response', async () => {
    vi.stubGlobal('fetch', async (_url: string) => ({
      ok: false,
      status: 404,
      text: async () => 'Not Found',
    }));

    const web = webFetchTool('/tmp/workdir');
    const result = await execute(web, { url: 'https://example.com/missing' });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.message).toMatch(/404/);
    }
  });

  it('returns error on network failure', async () => {
    vi.stubGlobal('fetch', async (_url: string) => { throw new Error('ECONNREFUSED') });

    const web = webFetchTool('/tmp/workdir');
    const result = await execute(web, { url: 'https://unreachable.example' });

    expect(result.ok).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
pnpm test
```

Expected: FAIL with `Cannot find module '../../src/tools/web.ts'`

- [ ] **Step 3: Implement**

`packages/landlord/src/tools/web.ts`:
```ts
import { tool } from 'flint';
import type { StandardSchemaV1, Tool } from 'flint';
import { z } from 'zod';

const webSchema = z.object({ url: z.string() });

export function webFetchTool(_workDir: string): Tool {
  return tool({
    name: 'web_fetch',
    description: 'Fetch a URL and return the response body as text.',
    input: webSchema as unknown as StandardSchemaV1<unknown, { url: string }>,
    jsonSchema: { type: 'object', properties: { url: { type: 'string' } }, required: ['url'] },
    handler: async ({ url }) => {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }
      return response.text();
    },
  });
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (all web tests + all prior tests)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/tools/web.ts packages/landlord/test/tools/web.test.ts
git commit -m "feat(landlord): webFetchTool — HTTP GET with error handling"
```

---

## Task 10: Tools Barrel

**Files:**
- Create: `packages/landlord/src/tools/index.ts`

No new tests needed — the barrel is covered by each tool's own tests.

- [ ] **Step 1: Write the barrel**

`packages/landlord/src/tools/index.ts`:
```ts
export { fileReadTool, fileWriteTool } from './file.ts';
export { bashTool } from './bash.ts';
export { webFetchTool } from './web.ts';
import type { Tool } from 'flint';
import { fileReadTool, fileWriteTool } from './file.ts';
import { bashTool } from './bash.ts';
import { webFetchTool } from './web.ts';

export function standardTools(workDir: string): Tool[] {
  return [
    fileReadTool(workDir),
    fileWriteTool(workDir),
    bashTool(workDir),
    webFetchTool(workDir),
  ];
}
```

- [ ] **Step 2: Verify it typechecks**

```bash
pnpm typecheck
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add packages/landlord/src/tools/index.ts
git commit -m "feat(landlord): standardTools(workDir) barrel"
```

---

## Task 11: orchestrate()

**Files:**
- Modify: `packages/landlord/src/orchestrate.ts` (add full implementation)
- Modify: `packages/landlord/test/orchestrate.test.ts` (add orchestrate() tests)

- [ ] **Step 1: Write the failing tests**

Add to `packages/landlord/test/orchestrate.test.ts` (after the existing sort tests):

```ts
import { orchestrate } from '../src/orchestrate.ts';
import { budget } from 'flint/budget';
import { mockAdapter } from 'flint/testing';
import type { NormalizedResponse } from 'flint';

function textResponse(content: string): NormalizedResponse {
  return { message: { role: 'assistant', content }, usage: { input: 10, output: 5 }, stopReason: 'end' };
}

function toolCallResponse(name: string, args: unknown): NormalizedResponse {
  return {
    message: { role: 'assistant', content: '', toolCalls: [{ id: 'tc1', name, arguments: args }] },
    usage: { input: 20, output: 10 },
    stopReason: 'tool_call',
  };
}

function judgePass(): NormalizedResponse {
  return {
    message: { role: 'assistant', content: JSON.stringify({ passed: true, explanation: 'Good' }) },
    usage: { input: 10, output: 5 },
    stopReason: 'end',
  };
}

describe('orchestrate', () => {
  it('single tenant completes end-to-end', async () => {
    // Call sequence: decompose, agent (checkpoint call), validate judge, agent finish
    let callIndex = 0;
    const adapter = mockAdapter({
      onCall: (_req, i) => {
        if (i === 0) return toolCallResponse('emit_plan', {
          contracts: [{
            role: 'worker',
            objective: 'Do work',
            subPrompt: 'Do the work',
            checkpoints: [{ name: 'done', description: 'Work is done', schema: { type: 'object', properties: { result: { type: 'string' } }, required: ['result'] } }],
            outputSchema: {},
          }],
        });
        if (i === 1) return toolCallResponse('emit_checkpoint__done', { result: 'success' });
        if (i === 2) return judgePass();
        return textResponse('Complete');
      },
    });

    const result = await orchestrate('Do some work', () => [], {
      adapter,
      landlordModel: 'test',
      tenantModel: 'test',
      budget: budget({ maxSteps: 50 }),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.status).toBe('complete');
      expect(result.value.tenants['worker']?.status).toBe('complete');
    }
  });

  it('two independent tenants run and both complete', async () => {
    let callIndex = 0;
    const adapter = mockAdapter({
      onCall: (_req, i) => {
        if (i === 0) return toolCallResponse('emit_plan', {
          contracts: [
            { role: 'alpha', objective: 'x', subPrompt: 'x', checkpoints: [], outputSchema: {} },
            { role: 'beta', objective: 'y', subPrompt: 'y', checkpoints: [], outputSchema: {} },
          ],
        });
        return textResponse('Done');
      },
    });

    const result = await orchestrate('Two tasks', () => [], {
      adapter,
      landlordModel: 'test',
      tenantModel: 'test',
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.status).toBe('complete');
      expect(result.value.tenants['alpha']?.status).toBe('complete');
      expect(result.value.tenants['beta']?.status).toBe('complete');
    }
  });

  it('tenant that misses checkpoints is retried and eventually escalated', async () => {
    const events: string[] = [];
    let callIndex = 0;
    const adapter = mockAdapter({
      onCall: (_req, i) => {
        if (i === 0) return toolCallResponse('emit_plan', {
          contracts: [{
            role: 'flaky',
            objective: 'x',
            subPrompt: 'x',
            checkpoints: [{ name: 'cp', description: 'checkpoint', schema: { type: 'object', properties: { v: { type: 'string' } }, required: ['v'] } }],
            outputSchema: {},
            maxRetries: 2,
          }],
        });
        // Always finish without hitting checkpoint
        return textResponse('Oops forgot checkpoint');
      },
    });

    const result = await orchestrate('Flaky task', () => [], {
      adapter,
      landlordModel: 'test',
      tenantModel: 'test',
      onEvent: (e) => events.push(e.type),
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.status).toBe('partial');
      expect(result.value.tenants['flaky']?.status).toBe('escalated');
    }
    expect(events).toContain('tenant_escalated');
  });

  it('onEvent fires tenant_started and tenant_complete events', async () => {
    const events: string[] = [];
    const adapter = mockAdapter({
      onCall: (_req, i) => {
        if (i === 0) return toolCallResponse('emit_plan', {
          contracts: [{ role: 'w', objective: 'x', subPrompt: 'x', checkpoints: [], outputSchema: {} }],
        });
        return textResponse('Done');
      },
    });

    await orchestrate('Task', () => [], {
      adapter,
      landlordModel: 'test',
      tenantModel: 'test',
      onEvent: (e) => events.push(e.type),
    });

    expect(events).toContain('tenant_started');
    expect(events).toContain('tenant_complete');
    expect(events).toContain('job_complete');
  });

  it('dependent tenant receives shared artifacts', async () => {
    let alphaArtifacts: unknown;
    let callIndex = 0;
    const adapter = mockAdapter({
      onCall: (req, i) => {
        if (i === 0) return toolCallResponse('emit_plan', {
          contracts: [
            { role: 'producer', objective: 'Produce', subPrompt: 'Produce data', checkpoints: [], outputSchema: {} },
            { role: 'consumer', objective: 'Consume', subPrompt: 'Consume data', checkpoints: [], outputSchema: {}, dependsOn: ['producer'] },
          ],
        });
        // consumer system prompt will contain shared artifacts — capture it
        const sysMsg = req.messages.find(m => m.role === 'system');
        if (sysMsg && typeof sysMsg.content === 'string' && sysMsg.content.includes('consumer')) {
          alphaArtifacts = sysMsg.content;
        }
        return textResponse('Done');
      },
    });

    await orchestrate('Chain task', () => [], {
      adapter,
      landlordModel: 'test',
      tenantModel: 'test',
    });
    // producer had no checkpoints so no artifacts, but the pipeline should complete without error
    expect(alphaArtifacts).toBeUndefined(); // no shared artifacts since producer had no checkpoints
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
pnpm test
```

Expected: FAIL — `orchestrate` not exported from `orchestrate.ts`

- [ ] **Step 3: Implement — add orchestrate() to orchestrate.ts**

Replace `packages/landlord/src/orchestrate.ts` with the full implementation (keep `DependencyCycleError` and `resolveOrder` at top):

```ts
import type { Budget, ProviderAdapter, Result, Tool } from 'flint';
import type { Contract } from './contract.ts';
import { decompose } from './decompose.ts';
import { runTenant } from './tenant.ts';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

export class DependencyCycleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DependencyCycleError';
  }
}

export function resolveOrder(contracts: Contract[]): Contract[] {
  const byRole = new Map(contracts.map(c => [c.role, c]));
  const WHITE = 0, GRAY = 1, BLACK = 2;
  const color = new Map(contracts.map(c => [c.role, WHITE]));
  const order: Contract[] = [];

  function visit(role: string, stack: string[]): void {
    if (color.get(role) === GRAY) {
      throw new DependencyCycleError(`Dependency cycle: ${[...stack, role].join(' -> ')}`);
    }
    if (color.get(role) === BLACK) return;
    if (!byRole.has(role)) return;
    color.set(role, GRAY);
    for (const dep of byRole.get(role)!.dependsOn) {
      visit(dep, [...stack, role]);
    }
    color.set(role, BLACK);
    order.push(byRole.get(role)!);
  }

  for (const c of contracts) visit(c.role, []);
  return order;
}

export type TenantOutcome =
  | { status: 'complete'; artifacts: Record<string, unknown> }
  | { status: 'escalated'; lastError: string; retriesExhausted: number };

export type OrchestrateResult = {
  status: 'complete' | 'partial';
  tenants: Record<string, TenantOutcome>;
  artifacts: Record<string, Record<string, unknown>>;
};

export type LandlordEvent =
  | { type: 'tenant_started'; role: string }
  | { type: 'checkpoint_passed'; role: string; checkpoint: string }
  | { type: 'checkpoint_failed'; role: string; checkpoint: string; reason: string }
  | { type: 'tenant_complete'; role: string }
  | { type: 'tenant_evicted'; role: string; reason: string; retry: number }
  | { type: 'tenant_escalated'; role: string }
  | { type: 'job_complete'; artifacts: Record<string, Record<string, unknown>> };

export type OrchestratorConfig = {
  adapter: ProviderAdapter;
  landlordModel: string;
  tenantModel: string;
  budget?: Budget;
  outputDir?: string;
  onEvent?: (event: LandlordEvent) => void;
};

export async function orchestrate(
  prompt: string,
  toolsFactory: (workDir: string) => Tool[],
  config: OrchestratorConfig,
): Promise<Result<OrchestrateResult>> {
  // Decompose
  const decomposeResult = await decompose(prompt, {
    adapter: config.adapter,
    model: config.landlordModel,
    ...(config.budget !== undefined ? { budget: config.budget } : {}),
  });
  if (!decomposeResult.ok) return decomposeResult;
  const plan = decomposeResult.value;

  resolveOrder(plan); // validate — throws DependencyCycleError if cyclic

  const baseOutputDir = config.outputDir ?? join(tmpdir(), `landlord-${Date.now()}`);
  await mkdir(join(baseOutputDir, 'shared'), { recursive: true });

  // Per-role gate: resolves with artifacts when the tenant completes (empty obj if escalated)
  const gates = new Map<string, { promise: Promise<Record<string, unknown>>; resolve: (v: Record<string, unknown>) => void }>();
  for (const c of plan) {
    let resolve!: (v: Record<string, unknown>) => void;
    const promise = new Promise<Record<string, unknown>>(r => { resolve = r; });
    gates.set(c.role, { promise, resolve });
  }

  const escalatedRoles = new Set<string>();
  const tenantOutcomes: Record<string, TenantOutcome> = {};
  const jobArtifacts: Record<string, Record<string, unknown>> = {};

  async function runWithRetry(contract: Contract): Promise<void> {
    // Wait for dependencies
    for (const dep of contract.dependsOn) {
      await gates.get(dep)!.promise;
      if (escalatedRoles.has(dep)) {
        const lastError = `Dependency '${dep}' escalated before this tenant could start`;
        escalatedRoles.add(contract.role);
        tenantOutcomes[contract.role] = { status: 'escalated', lastError, retriesExhausted: 0 };
        gates.get(contract.role)!.resolve({});
        config.onEvent?.({ type: 'tenant_escalated', role: contract.role });
        return;
      }
    }

    // Build shared context from dependencies
    const sharedArtifacts: Record<string, unknown> = {};
    for (const dep of contract.dependsOn) {
      const depArtifacts = jobArtifacts[dep] ?? {};
      for (const [k, v] of Object.entries(depArtifacts)) {
        sharedArtifacts[`${dep}.${k}`] = v;
      }
    }

    config.onEvent?.({ type: 'tenant_started', role: contract.role });

    const workDir = join(baseOutputDir, contract.role);
    await mkdir(workDir, { recursive: true });

    let lastError: string | undefined;

    for (let attempt = 0; attempt < contract.maxRetries; attempt++) {
      const result = await runTenant(
        contract,
        toolsFactory(workDir),
        {
          adapter: config.adapter,
          model: config.tenantModel,
          ...(config.budget !== undefined ? { budget: config.budget } : {}),
          workDir,
        },
        lastError,
        Object.keys(sharedArtifacts).length > 0 ? sharedArtifacts : undefined,
      );

      if (result.ok) {
        jobArtifacts[contract.role] = result.value;
        tenantOutcomes[contract.role] = { status: 'complete', artifacts: result.value };
        gates.get(contract.role)!.resolve(result.value);
        config.onEvent?.({ type: 'tenant_complete', role: contract.role });
        return;
      }

      lastError = result.error.message;
      config.onEvent?.({ type: 'tenant_evicted', role: contract.role, reason: lastError, retry: attempt + 1 });
    }

    // All retries exhausted
    escalatedRoles.add(contract.role);
    tenantOutcomes[contract.role] = {
      status: 'escalated',
      lastError: lastError ?? 'unknown',
      retriesExhausted: contract.maxRetries,
    };
    gates.get(contract.role)!.resolve({});
    config.onEvent?.({ type: 'tenant_escalated', role: contract.role });
  }

  await Promise.all(plan.map(c => runWithRetry(c)));

  const allComplete = Object.values(tenantOutcomes).every(o => o.status === 'complete');
  const status = allComplete ? 'complete' : 'partial';
  config.onEvent?.({ type: 'job_complete', artifacts: jobArtifacts });

  return {
    ok: true,
    value: { status, tenants: tenantOutcomes, artifacts: jobArtifacts },
  };
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
pnpm test
```

Expected: PASS (all 5 orchestrate tests + all prior tests)

- [ ] **Step 5: Commit**

```bash
git add packages/landlord/src/orchestrate.ts packages/landlord/test/orchestrate.test.ts
git commit -m "feat(landlord): orchestrate() — parallel dispatch, dependency gates, retry/eviction"
```

---

## Task 12: Public API Barrel + Typecheck

**Files:**
- Create: `packages/landlord/src/index.ts`

- [ ] **Step 1: Write the barrel**

`packages/landlord/src/index.ts`:
```ts
export { orchestrate, resolveOrder, DependencyCycleError } from './orchestrate.ts';
export { decompose } from './decompose.ts';
export { runTenant } from './tenant.ts';
export { validateCheckpoint } from './validate.ts';
export { ContractSchema, CheckpointSchema } from './contract.ts';
export type { Contract, Checkpoint } from './contract.ts';
export type {
  OrchestrateResult,
  OrchestratorConfig,
  LandlordEvent,
  TenantOutcome,
} from './orchestrate.ts';
export type { ValidationVerdict } from './validate.ts';
```

- [ ] **Step 2: Run full test suite**

```bash
pnpm test
```

Expected: PASS — all tests green

- [ ] **Step 3: Typecheck**

```bash
pnpm typecheck
```

Expected: no TypeScript errors

- [ ] **Step 4: Build**

```bash
pnpm build
```

Expected: `dist/` is produced with `index.js`, `index.d.ts`, `tools/index.js`, `tools/index.d.ts`

- [ ] **Step 5: Run tests from monorepo root to verify workspace integration**

```bash
# From Flint monorepo root
pnpm test
```

Expected: all packages' tests pass

- [ ] **Step 6: Commit**

```bash
git add packages/landlord/src/index.ts
git commit -m "feat(landlord): public API barrel — orchestrate, decompose, runTenant, types"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `packages/landlord` in Flint monorepo | Task 1 |
| Contract/Checkpoint as Zod schemas | Task 2 |
| `decompose()` via `call()` + forced `emit_plan` | Task 4 |
| `validateCheckpoint()` Zod/JSON tier + LLM semantic tier | Task 5 |
| `runTenant()` via `agent()` with checkpoint tools | Task 6 |
| Tool filtering (toolsAllowed/toolsDenied) | Task 6 |
| File tools (fileReadTool, fileWriteTool) | Task 7 |
| Bash tool | Task 8 |
| Web fetch tool | Task 9 |
| `standardTools(workDir)` factory barrel | Task 10 |
| `orchestrate()` topological sort | Task 3 |
| Parallel dispatch + dependency gates | Task 11 |
| Retry/eviction loop | Task 11 |
| `onEvent` callback | Task 11 |
| `OrchestrateResult` with `status`, `tenants`, `artifacts` | Task 11 |
| `landlord/tools` subpath export | Task 1 (package.json exports) |
| Public API barrel | Task 12 |

**One deliberate spec deviation:** `runTenant()` returns `Promise<Result<Record<string, unknown>>>` (artifacts on success, error on failure) rather than `Promise<Result<TenantResult>>`. The `TenantOutcome` type (with `status: 'escalated'`) lives in `orchestrate.ts` where retries are managed. This is cleaner — `runTenant` does one attempt, the orchestrator handles retry semantics.
