from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from edi_processor.config import X12ValidationSettings
from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.validation import ValidationIssue, ValidationResult


class X12ValidationService:
    def __init__(self, settings: X12ValidationSettings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def validate(self, submission: FileSubmission, run_id: str) -> ValidationResult:
        if not self._should_validate(submission):
            return ValidationResult(is_valid=True)

        try:
            content = self._read_text(submission.path)
        except OSError as exc:
            return ValidationResult(
                is_valid=False,
                issues=(
                    ValidationIssue(
                        row_number=None,
                        field_name="DTP",
                        severity="error",
                        error_code="X12_READ_FAILED",
                        message=str(exc),
                    ),
                ),
            )

        result = self._validate_date_of_service(content)
        if not result.is_valid:
            self.logger.error(
                "X12 date of service validation failed",
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "x12_validation_failed",
                },
            )
        return result

    def _should_validate(self, submission: FileSubmission) -> bool:
        if not self.settings.enabled or not self.settings.date_of_service_enabled:
            return False

        suffix = submission.path.suffix.lower()
        return submission.provider.converter == "convert837ITo837P" or suffix in {
            ".837i",
            ".837p",
            ".x12",
        }

    def _validate_date_of_service(self, content: str) -> ValidationResult:
        issues: list[ValidationIssue] = []
        matching_segments = 0

        for segment_number, raw_segment in enumerate(content.split("~"), start=1):
            segment = raw_segment.strip()
            if not segment:
                continue

            parts = segment.split("*")
            if len(parts) < 4:
                continue

            if (
                parts[0] != self.settings.service_date_segment
                or parts[1] != self.settings.service_date_qualifier
            ):
                continue

            matching_segments += 1
            if parts[2] != self.settings.range_format_qualifier:
                continue

            dates = parts[3].split("-", 1)
            if len(dates) != 2:
                issues.append(
                    self._issue(
                        segment_number=segment_number,
                        error_code="X12_DTP_472_RANGE_INVALID",
                        message="DTP 472 uses RD8 but does not contain a from-through date range.",
                        raw_value=segment,
                        suggested_fix="Use YYYYMMDD-YYYYMMDD for the DTP 472 service date range.",
                    )
                )
                continue

            from_date = self._parse_x12_date(dates[0])
            through_date = self._parse_x12_date(dates[1])
            if from_date is None or through_date is None:
                issues.append(
                    self._issue(
                        segment_number=segment_number,
                        error_code="X12_DTP_472_DATE_INVALID",
                        message="DTP 472 contains a service date that is not a valid YYYYMMDD date.",
                        raw_value=segment,
                        suggested_fix="Correct the DTP 472 service date range.",
                    )
                )
                continue

            if through_date < from_date:
                issues.append(
                    self._issue(
                        segment_number=segment_number,
                        error_code="X12_DTP_472_THROUGH_BEFORE_FROM",
                        message="The DTP 472 service date through value is earlier than the from value.",
                        raw_value=segment,
                        suggested_fix="Correct the service date range so the through date is on or after the from date.",
                    )
                )

        if matching_segments == 0 and self.settings.require_service_date:
            issues.append(
                self._issue(
                    segment_number=None,
                    error_code="X12_DTP_472_MISSING",
                    message="No DTP 472 service date segment was found.",
                    raw_value=None,
                    suggested_fix="Include a DTP 472 service date segment before resubmitting.",
                )
            )

        return ValidationResult(is_valid=not issues, issues=tuple(issues))

    def _issue(
        self,
        segment_number: int | None,
        error_code: str,
        message: str,
        raw_value: str | None,
        suggested_fix: str | None,
    ) -> ValidationIssue:
        return ValidationIssue(
            row_number=segment_number,
            field_name="DTP*472",
            severity="error",
            error_code=error_code,
            message=message,
            raw_value=raw_value,
            suggested_fix=suggested_fix,
        )

    def _parse_x12_date(self, value: str) -> date | None:
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            return None

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="cp1252")
