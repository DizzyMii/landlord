"""Two-tier checkpoint validator: JSON Schema + structured LLM judge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import jsonschema

from landlord.anthropic_client import AnthropicClient, CachedBlock
from landlord.contract import Checkpoint, Contract


@dataclass
class ValidationResult:
    passed: bool
    tier: int
    explanation: str
    errors: list[str] = field(default_factory=list)


JUDGE_SYSTEM = (
    "You are a strict validator. You receive a checkpoint output from a worker agent "
    "along with the contract objective and the checkpoint description. You must decide "
    "whether the output meets the intent of the checkpoint and call the judge_checkpoint "
    "tool with your verdict. Be lenient on form, strict on substance: if the worker "
    "produced something that factually satisfies the checkpoint description, pass. If it "
    "is missing required work, off-topic, or trivially incorrect, fail with a concrete "
    "reason."
)

JUDGE_TOOL = {
    "name": "judge_checkpoint",
    "description": "Record whether the checkpoint output meets the requirements.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["passed", "reason"],
    },
}


class Validator:
    def __init__(self, client: AnthropicClient) -> None:
        self._client = client

    async def validate_checkpoint(
        self,
        output: dict,
        checkpoint: Checkpoint,
        contract: Contract,
    ) -> ValidationResult:
        """Validate a checkpoint output through Tier 1 (JSON Schema) and,
        if that passes, Tier 2 (structured LLM judge).

        Raises:
            RuntimeError: if the judge model does not emit the forced
                judge_checkpoint tool (e.g., a safety refusal or an API
                error). Callers (e.g., the orchestrator) must handle
                this — it is intentionally not converted to a passed=False
                result so that "judge unavailable" can be distinguished
                from "judge said fail".
        """
        tier1 = self._validate_schema(output, checkpoint)
        if not tier1.passed:
            return tier1
        return await self._validate_semantic(output, checkpoint, contract)

    def _validate_schema(self, output: dict, checkpoint: Checkpoint) -> ValidationResult:
        try:
            jsonschema.validate(instance=output, schema=checkpoint.schema)
            return ValidationResult(
                passed=True, tier=1, explanation="Schema validation passed"
            )
        except jsonschema.ValidationError as e:
            return ValidationResult(
                passed=False,
                tier=1,
                explanation=f"Schema validation failed: {e.message}",
                errors=[e.message],
            )

    async def _validate_semantic(
        self, output: dict, checkpoint: Checkpoint, contract: Contract
    ) -> ValidationResult:
        system = [CachedBlock(text=JUDGE_SYSTEM, cache=True)]
        user_content = (
            f"Contract objective: {contract.objective}\n"
            f"Checkpoint name: {checkpoint.name}\n"
            f"Checkpoint description: {checkpoint.description}\n"
            f"Output:\n{json.dumps(output, indent=2, default=str)}"
        )
        verdict = await self._client.call_forced_tool(
            system=system,
            messages=[{"role": "user", "content": user_content}],
            tool=JUDGE_TOOL,
        )
        return ValidationResult(
            passed=bool(verdict.get("passed", False)),
            tier=2,
            explanation=str(verdict.get("reason", "")),
        )
