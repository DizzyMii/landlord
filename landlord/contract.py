"""Contract and Checkpoint models for tenant task definitions."""

from uuid import uuid4

from pydantic import BaseModel, Field


class Checkpoint(BaseModel):
    """A validation point within a tenant's execution."""

    name: str
    description: str
    schema: dict


class Contract(BaseModel):
    """Defines everything a tenant needs and is bound by."""

    tenant_id: str = Field(default_factory=lambda: uuid4().hex[:8])
    role: str
    objective: str
    sub_prompt: str
    checkpoints: list[Checkpoint]
    output_schema: dict
    tools_allowed: list[str] | None = None
    tools_denied: list[str] | None = None
    depends_on: list[str] = Field(default_factory=list)
    max_retries: int = 3
    context: str | None = None

    def effective_tools(self, all_tool_names: list[str]) -> list[str]:
        """Resolve which tools this tenant can use."""
        if self.tools_allowed is not None:
            return [t for t in all_tool_names if t in self.tools_allowed]
        if self.tools_denied is not None:
            return [t for t in all_tool_names if t not in self.tools_denied]
        return list(all_tool_names)
