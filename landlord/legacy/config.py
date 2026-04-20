"""Configuration loading for the Landlord Framework."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class LandlordConfig(BaseModel):
    """Framework configuration with YAML + CLI override support."""

    landlord_model: str = "claude-sonnet-4-20250514"
    tenant_model: str | None = None
    output_dir: str = "./output"
    max_retries: int = 3
    verbose: bool = False
    auto_approve: bool = False
    search_api_url: str | None = None

    @property
    def effective_tenant_model(self) -> str:
        return self.tenant_model or self.landlord_model

    @classmethod
    def load(cls, config_path: str | None = None, **cli_overrides: Any) -> LandlordConfig:
        """Load config from YAML file, then apply CLI overrides."""
        yaml_data: dict[str, Any] = {}
        if config_path:
            path = Path(config_path)
            if path.exists():
                with open(path) as f:
                    raw = yaml.safe_load(f)
                    if isinstance(raw, dict):
                        yaml_data = raw

        active_overrides = {k: v for k, v in cli_overrides.items() if v is not None}
        merged = {**yaml_data, **active_overrides}
        known_fields = cls.model_fields.keys()
        filtered = {k: v for k, v in merged.items() if k in known_fields}

        return cls(**filtered)
