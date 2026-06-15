from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NotificationRenderResult:
    subject: str
    recipients: tuple[str, ...]
    text_path: Path
    html_path: Path
    send_enabled: bool
