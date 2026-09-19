from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Change(BaseModel):
    attribute: str
    before: Any = None
    after: Any = None


class CanonicalChange(BaseModel):
    address: str
    resource_type: str
    action: str
    environment: str = "unknown"
    region: str = "unknown"
    changes: list[Change] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    unknown: bool = False


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_id: str
    task: str
    allowed_resource_addresses: tuple[str, ...] = ("aws_lambda_function.dev_api",)
    allowed_resource_types: tuple[str, ...] = ("aws_lambda_function",)
    allowed_operations: tuple[str, ...] = ("update",)
    allowed_regions: tuple[str, ...] = ("ap-south-1",)
    max_changed_resources: int = Field(default=1, ge=0)
    max_cost_delta: float | None = None
    denies: tuple[Literal["production", "networking", "public_access"], ...] = (
        "production",
        "networking",
        "public_access",
    )
    expires_at: datetime
    status: Literal["draft", "confirmed"] = "draft"
    version: int = 1

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Expiry must include a timezone")
        return value

    def active(self):
        return self.status == "confirmed" and self.expires_at > datetime.now(
            timezone.utc
        )


class Verdict(BaseModel):
    address: str
    verdict: Literal["ALLOW", "REVIEW", "DENY", "EVALUATION_ERROR"]
    changes: list[Change]
    reason: str
    determining_policies: list[str] = Field(default_factory=list)
