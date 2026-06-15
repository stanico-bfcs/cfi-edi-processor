from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from edi_processor.models.x12_update import X12DateUpdateResult


class X12DateUpdateService:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def update_received_date(
        self,
        path: Path,
        received_date: date,
        run_id: str,
        provider_key: str,
        file_name: str,
    ) -> X12DateUpdateResult:
        try:
            content = self._read_text(path)
        except OSError as exc:
            return X12DateUpdateResult(
                path=path,
                succeeded=False,
                message=str(exc),
                error_code="X12_READ_FAILED",
            )

        segments = content.split("~")
        isa_date = received_date.strftime("%y%m%d")
        long_date = received_date.strftime("%Y%m%d")
        updated_segments = 0

        for index, segment in enumerate(segments):
            stripped = segment.strip()
            if not stripped:
                continue

            parts = stripped.split("*")
            if parts[0] == "ISA" and len(parts) > 9:
                parts[9] = isa_date
                segments[index] = self._replace_segment(segment, parts)
                updated_segments += 1
            elif parts[0] == "GS" and len(parts) > 4:
                parts[4] = long_date
                segments[index] = self._replace_segment(segment, parts)
                updated_segments += 1
            elif parts[0] == "BHT" and len(parts) > 4:
                parts[4] = long_date
                segments[index] = self._replace_segment(segment, parts)
                updated_segments += 1

        if updated_segments == 0:
            return X12DateUpdateResult(
                path=path,
                succeeded=False,
                message="No ISA, GS, or BHT date segments were updated.",
                error_code="X12_DATE_SEGMENTS_NOT_FOUND",
            )

        path.write_text("~".join(segments), encoding="utf-8")
        self.logger.info(
            f"Updated X12 received date fields in {path}",
            extra={
                "run_id": run_id,
                "provider": provider_key,
                "file_name": file_name,
                "status": "x12_received_date_updated",
                "updated_segments": updated_segments,
            },
        )
        return X12DateUpdateResult(
            path=path,
            succeeded=True,
            updated_segments=updated_segments,
        )

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="cp1252")

    def _replace_segment(self, original: str, parts: list[str]) -> str:
        leading_whitespace = original[: len(original) - len(original.lstrip())]
        trailing_whitespace = original[len(original.rstrip()) :]
        return f"{leading_whitespace}{'*'.join(parts)}{trailing_whitespace}"
