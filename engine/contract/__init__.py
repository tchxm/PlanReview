from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any
from engine.types import Contract
from pydantic import Field


class DraftContract(Contract):
    """Phase 1 wire payload; version belongs to the confirmed storage record."""

    version: int = Field(default=1, exclude=True)


def draft(task: str, mode: str = "replay", intent: Any = None) -> Contract:
    if not task.strip():
        raise ValueError("Task is required")

    allowed_addresses = ("aws_lambda_function.dev_api",)
    allowed_types = ("aws_lambda_function",)

    if intent is not None:
        addr = getattr(intent, "resource_address", None) or (
            intent.get("resource_address") if isinstance(intent, dict) else None
        )
        rtype = getattr(intent, "resource_type", None) or (
            intent.get("resource_type") if isinstance(intent, dict) else None
        )
        if addr and rtype:
            allowed_addresses = (addr,)
            allowed_types = (rtype,)

    return DraftContract(
        contract_id=str(uuid4()),
        task=task,
        allowed_resource_addresses=allowed_addresses,
        allowed_resource_types=allowed_types,
        allowed_operations=("update",),
        allowed_regions=("ap-south-1",),
        max_changed_resources=1,
        denies=("production", "networking", "public_access"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )


def confirm(contract: Contract) -> Contract:
    if contract.status != "draft":
        raise ValueError("Contract already confirmed and immutable")
    if contract.expires_at <= datetime.now(timezone.utc):
        raise ValueError("Contract expired")
    return Contract.model_validate({**contract.model_dump(), "status": "confirmed"})
