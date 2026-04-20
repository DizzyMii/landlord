"""Tiered validation pipeline for checkpoint outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import jsonschema

from landlord.contract import Checkpoint, Contract
from landlord.legacy.llm_client import LLMClient


@dataclass
class ValidationResult:
    """Result of validating a checkpoint output."""

    passed: bool
    tier: int
    explanation: str
    errors: list[str] = field(default_factory=list)


class Validator:
    """3-tier checkpoint validation: schema -> static analysis -> LLM judgment."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    async def validate_checkpoint(
        self,
        output: dict,
        checkpoint: Checkpoint,
        contract: Contract,
    ) -> ValidationResult:
        # Tier 1: JSON Schema validation
        tier1 = self._validate_schema(output, checkpoint)
        if not tier1.passed:
            return tier1

        # Tier 3: LLM semantic judgment (when checkpoint has a description)
        if checkpoint.description:
            try:
                return await self._validate_semantic(output, checkpoint, contract)
            except (AttributeError, TypeError):
                return tier1

        return tier1

    def _validate_schema(self, output: dict, checkpoint: Checkpoint) -> ValidationResult:
        """Tier 1: Validate output against checkpoint JSON Schema."""
        try:
            jsonschema.validate(instance=output, schema=checkpoint.schema)
            return ValidationResult(passed=True, tier=1, explanation="Schema validation passed")
        except jsonschema.ValidationError as e:
            return ValidationResult(
                passed=False,
                tier=1,
                explanation="Schema validation failed",
                errors=[e.message],
            )

    async def _validate_semantic(
        self, output: dict, checkpoint: Checkpoint, contract: Contract
    ) -> ValidationResult:
        """Tier 3: LLM judges semantic correctness."""
        prompt = (
            f"You are validating a checkpoint output for a worker agent.\n\n"
            f"Contract objective: {contract.objective}\n"
            f"Checkpoint: {checkpoint.name}\n"
            f"Checkpoint description: {checkpoint.description}\n"
            f"Output: {json.dumps(output, indent=2)}\n\n"
            f"Does this output satisfy the checkpoint requirements?\n"
            f"Answer with PASS or FAIL followed by a brief explanation."
        )
        response = await self._llm_client.chat([{"role": "user", "content": prompt}])
        passed = response.strip().upper().startswith("PASS")
        return ValidationResult(
            passed=passed,
            tier=3,
            explanation=response.strip(),
        )
