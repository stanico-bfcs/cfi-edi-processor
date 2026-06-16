from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4


@dataclass(frozen=True)
class RunContext:
    run_id: str
    started_at: datetime
    dry_run: bool
    provider_filter: tuple[str, ...] = ()


def create_run_context(
    dry_run: bool,
    provider_filter: tuple[str, ...] = (),
) -> RunContext:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return RunContext(
        run_id=f"{timestamp}_{uuid4().hex[:8]}",
        started_at=datetime.now(),
        dry_run=dry_run,
        provider_filter=provider_filter,
    )
