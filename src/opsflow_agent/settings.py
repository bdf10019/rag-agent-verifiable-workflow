from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings with safe, local-only defaults."""

    model_config = SettingsConfigDict(
        env_prefix="OPSFLOW_",
        env_file=".env",
        extra="ignore",
    )

    database_path: Path = PROJECT_ROOT / "data" / "opsflow.db"
    sop_directory: Path = Path(__file__).resolve().parent / "resources" / "sops"
    max_tool_attempts: int = Field(default=3, ge=1, le=5)
    tool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    fail_once_tool: str | None = None
    log_level: str = "INFO"
    max_plan_steps: int = Field(default=6, ge=1, le=10)
    retrieval_top_k: int = Field(default=3, ge=1, le=5)

    def normalized(self) -> Settings:
        data = self.model_dump()
        for key in ("database_path", "sop_directory"):
            value = Path(data[key])
            if not value.is_absolute():
                data[key] = PROJECT_ROOT / value
        return Settings.model_construct(**data)
