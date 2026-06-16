from __future__ import annotations

import logging
from pathlib import Path

from edi_processor.models.diagnosis_mapping import (
    DiagnosisCodeMapping,
    X12DiagnosisUpdateResult,
)


class X12DiagnosisUpdateService:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def update_diagnosis_codes(
        self,
        path: Path,
        mappings: tuple[DiagnosisCodeMapping, ...],
        qualifier: str,
        run_id: str,
        provider_key: str,
        file_name: str,
    ) -> X12DiagnosisUpdateResult:
        if not mappings:
            return X12DiagnosisUpdateResult(succeeded=True)

        try:
            content = self._read_text(path)
        except OSError as exc:
            return X12DiagnosisUpdateResult(
                succeeded=False,
                message=str(exc),
                error_code="X12_DIAGNOSIS_READ_FAILED",
            )

        segments = content.split("~")
        diagnosis_indexes = self._diagnosis_indexes(segments, qualifier)
        if len(diagnosis_indexes) != len(mappings):
            return X12DiagnosisUpdateResult(
                succeeded=False,
                message=(
                    f"Expected {len(mappings)} HI*{qualifier}: diagnosis segments "
                    f"but found {len(diagnosis_indexes)}."
                ),
                error_code="X12_DIAGNOSIS_SEGMENT_COUNT_MISMATCH",
            )

        for mapping, segment_index in zip(mappings, diagnosis_indexes, strict=True):
            segments[segment_index] = self._replace_diagnosis_code(
                segments[segment_index],
                qualifier,
                mapping.diagnosis_code,
            )

        updated_content = "~".join(segments)
        path.write_text(updated_content, encoding="utf-8")

        verification = self._verify(path, mappings, qualifier)
        if not verification.succeeded:
            return verification

        self.logger.info(
            f"Updated X12 diagnosis codes in {path}",
            extra={
                "run_id": run_id,
                "provider": provider_key,
                "file_name": file_name,
                "status": "x12_diagnosis_codes_updated",
                "updated_segments": len(mappings),
            },
        )
        return X12DiagnosisUpdateResult(
            succeeded=True,
            updated_segments=len(mappings),
        )

    def _verify(
        self,
        path: Path,
        mappings: tuple[DiagnosisCodeMapping, ...],
        qualifier: str,
    ) -> X12DiagnosisUpdateResult:
        content = self._read_text(path)
        segments = content.split("~")
        diagnosis_indexes = self._diagnosis_indexes(segments, qualifier)
        if len(diagnosis_indexes) != len(mappings):
            return X12DiagnosisUpdateResult(
                succeeded=False,
                message="X12 diagnosis segment count changed after update.",
                error_code="X12_DIAGNOSIS_VERIFICATION_COUNT_MISMATCH",
            )

        for mapping, segment_index in zip(mappings, diagnosis_indexes, strict=True):
            actual = self._diagnosis_code(segments[segment_index], qualifier)
            if actual != mapping.diagnosis_code:
                return X12DiagnosisUpdateResult(
                    succeeded=False,
                    message=(
                        f"Diagnosis verification failed for source row "
                        f"{mapping.row_number}: expected {mapping.diagnosis_code} "
                        f"but found {actual or 'blank'}."
                    ),
                    error_code="X12_DIAGNOSIS_VERIFICATION_FAILED",
                )

        return X12DiagnosisUpdateResult(
            succeeded=True,
            updated_segments=len(mappings),
        )

    def _diagnosis_indexes(self, segments: list[str], qualifier: str) -> list[int]:
        indexes: list[int] = []
        prefix = f"{qualifier}:"
        for index, segment in enumerate(segments):
            parts = segment.strip().split("*")
            if not parts or parts[0] != "HI":
                continue
            if any(component.startswith(prefix) for component in parts[1:]):
                indexes.append(index)
        return indexes

    def _replace_diagnosis_code(
        self,
        segment: str,
        qualifier: str,
        diagnosis_code: str,
    ) -> str:
        leading_whitespace = segment[: len(segment) - len(segment.lstrip())]
        trailing_whitespace = segment[len(segment.rstrip()) :]
        stripped = segment.strip()
        parts = stripped.split("*")
        prefix = f"{qualifier}:"
        for index, component in enumerate(parts[1:], start=1):
            if component.startswith(prefix):
                pieces = component.split(":")
                pieces[1] = diagnosis_code
                parts[index] = ":".join(pieces)
                break
        return f"{leading_whitespace}{'*'.join(parts)}{trailing_whitespace}"

    def _diagnosis_code(self, segment: str, qualifier: str) -> str | None:
        prefix = f"{qualifier}:"
        for component in segment.strip().split("*")[1:]:
            if component.startswith(prefix):
                pieces = component.split(":")
                if len(pieces) > 1:
                    return pieces[1]
        return None

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="cp1252")
