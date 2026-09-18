from datetime import datetime, timedelta, timezone
from uuid import uuid4
from engine.types import Contract
from pydantic import Field


class DraftContract(Contract):
    """Phase 1 wire payload; version belongs to the confirmed storage record."""

    version: int = Field(default=1, exclude=True)


def draft(task: str) -> Contract:
    # PLACEHOLDER: deterministic local extractor retained because constrained Ollama output lost task scope.
    if not task.strip():
        raise ValueError("Task is required")
    return DraftContract(
        contract_id=str(uuid4()),
        task=task,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )


def confirm(contract: Contract) -> Contract:
    if contract.status != "draft":
        raise ValueError("Contract already confirmed and immutable")
    if contract.expires_at <= datetime.now(timezone.utc):
        raise ValueError("Contract expired")
    return Contract.model_validate({**contract.model_dump(), "status": "confirmed"})
