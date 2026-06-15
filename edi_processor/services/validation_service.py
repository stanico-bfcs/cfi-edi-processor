from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from edi_processor.config import ValidationField, ValidationSchema
from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.validation import ValidationIssue, ValidationResult
from edi_processor.services.excel_reader import ExcelReader


class ValidationService:
    def __init__(self, schemas: dict[str, ValidationSchema]) -> None:
        self.schemas = schemas
        self.logger = logging.getLogger(__name__)
        self.excel_reader = ExcelReader()

    def validate(self, submission: FileSubmission, run_id: str) -> ValidationResult:
        validation = submission.provider.validation
        if not validation.enabled:
            return ValidationResult(is_valid=True)

        if not validation.schema:
            return ValidationResult(
                is_valid=False,
                issues=(
                    ValidationIssue(
                        row_number=None,
                        field_name=None,
                        severity="error",
                        error_code="VALIDATION_SCHEMA_MISSING",
                        message="Provider validation is enabled but no schema is configured.",
                    ),
                ),
            )

        schema = self.schemas[validation.schema]
        if schema.file_type not in {"csv", "xlsx"}:
            self.logger.info(
                f"Validation schema {schema.key} is not implemented yet",
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "validation_not_implemented",
                },
            )
            return ValidationResult(is_valid=True)

        if schema.file_type == "xlsx":
            return self._validate_rows(self.excel_reader.read_rows(submission.path), schema)

        return self._validate_delimited_file(submission.path, schema)

    def _validate_delimited_file(self, path: Path, schema: ValidationSchema) -> ValidationResult:
        issues: list[ValidationIssue] = []
        expected_headers = [field.name for field in schema.fields]

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                lines = file.readlines()
        except UnicodeDecodeError:
            with path.open("r", encoding="cp1252", newline="") as file:
                lines = file.readlines()

        if not lines:
            return ValidationResult(
                is_valid=False,
                issues=(
                    ValidationIssue(
                        row_number=None,
                        field_name=None,
                        severity="error",
                        error_code="FILE_EMPTY",
                        message="The submitted file is empty.",
                    ),
                ),
            )

        rows = self._read_csv_rows(lines, schema, issues)
        if issues:
            return ValidationResult(is_valid=False, issues=tuple(issues))

        return self._validate_rows(rows, schema)

    def _validate_rows(self, rows: list[list[str]], schema: ValidationSchema) -> ValidationResult:
        issues: list[ValidationIssue] = []
        expected_headers = [field.name for field in schema.fields]
        header_index = (schema.header_row or 1) - 1
        data_start_index = (schema.data_start_row or header_index + 2) - 1

        if header_index >= len(rows):
            issues.append(
                ValidationIssue(
                    row_number=schema.header_row,
                    field_name=None,
                    severity="error",
                    error_code="HEADER_ROW_MISSING",
                    message="The configured header row does not exist.",
                )
            )
            return ValidationResult(is_valid=False, issues=tuple(issues))

        actual_headers = [header.strip() for header in self._trim_trailing_blank(rows[header_index])]
        if expected_headers and actual_headers != expected_headers:
            issues.append(
                ValidationIssue(
                    row_number=schema.header_row,
                    field_name=None,
                    severity="error",
                    error_code="HEADER_MISMATCH",
                    message="The file headers do not match the configured schema.",
                    raw_value=", ".join(actual_headers),
                    suggested_fix=", ".join(expected_headers),
                )
            )

        expected_count = len(expected_headers)
        for row_index, row in enumerate(rows[data_start_index:], start=data_start_index + 1):
            row = self._trim_trailing_blank(row)
            if self._is_blank_row(row):
                if not schema.allow_blank_rows:
                    issues.append(
                        ValidationIssue(
                            row_number=row_index,
                            field_name=None,
                            severity="error",
                            error_code="BLANK_ROW_NOT_ALLOWED",
                            message="Blank rows are not allowed for this file type.",
                        )
                    )
                continue

            if schema.strict_column_count and expected_count and len(row) != expected_count:
                issues.append(
                    ValidationIssue(
                        row_number=row_index,
                        field_name=None,
                        severity="error",
                        error_code="COLUMN_COUNT_MISMATCH",
                        message=f"Expected {expected_count} columns but found {len(row)}.",
                        raw_value=", ".join(row),
                    )
                )
                continue

            for field_index, field in enumerate(schema.fields):
                value = row[field_index].strip() if field_index < len(row) else ""
                issues.extend(self._validate_field(row_index, field, value))

        return ValidationResult(is_valid=not issues, issues=tuple(issues))

    def _read_csv_rows(
        self,
        lines: list[str],
        schema: ValidationSchema,
        issues: list[ValidationIssue],
    ) -> list[list[str]]:
        if schema.malformed_quote_check:
            for line_number, line in enumerate(lines, start=1):
                if re.search(r'(^|,)""[^",]', line):
                    issues.append(
                        ValidationIssue(
                            row_number=line_number,
                            field_name=None,
                            severity="error",
                            error_code="CSV_MALFORMED_QUOTING",
                            message="A field appears to start with an extra quote, which can shift CSV columns.",
                            raw_value=line.strip(),
                            suggested_fix="Remove the extra quote and resubmit the file.",
                        )
                    )

        if issues:
            return []

        reader = csv.reader(lines, delimiter=schema.delimiter or ",", strict=True)
        try:
            return [row for row in reader]
        except csv.Error as exc:
            issues.append(
                ValidationIssue(
                    row_number=getattr(reader, "line_num", None),
                    field_name=None,
                    severity="error",
                    error_code="CSV_PARSE_ERROR",
                    message=str(exc),
                )
            )
            return []

    def _validate_field(
        self,
        row_number: int,
        field: ValidationField,
        value: str,
    ) -> list[ValidationIssue]:
        if not value:
            if field.required:
                return [
                    ValidationIssue(
                        row_number=row_number,
                        field_name=field.name,
                        severity="error",
                        error_code="REQUIRED_FIELD_MISSING",
                        message="A required field is blank.",
                    )
                ]
            return []

        validators = {
            "date": self._validate_date,
            "decimal": self._validate_decimal,
            "integer": self._validate_integer,
            "member_id": self._validate_pattern,
            "string": self._validate_string,
        }
        validator = validators.get(field.data_type, self._validate_string)
        return validator(row_number, field, value)

    def _validate_string(
        self,
        row_number: int,
        field: ValidationField,
        value: str,
    ) -> list[ValidationIssue]:
        return self._validate_pattern(row_number, field, value)

    def _validate_pattern(
        self,
        row_number: int,
        field: ValidationField,
        value: str,
    ) -> list[ValidationIssue]:
        if field.pattern and not re.match(field.pattern, value):
            return [
                ValidationIssue(
                    row_number=row_number,
                    field_name=field.name,
                    severity="error",
                    error_code="FIELD_PATTERN_MISMATCH",
                    message="The field value does not match the configured pattern.",
                    raw_value=value,
                )
            ]
        return []

    def _validate_date(
        self,
        row_number: int,
        field: ValidationField,
        value: str,
    ) -> list[ValidationIssue]:
        for date_format in field.date_formats:
            if date_format == "excel_serial" and self._is_excel_serial_date(value):
                return []

            formats = (date_format, date_format.replace("%-", "%#"))
            for candidate in formats:
                try:
                    datetime.strptime(value, candidate)
                    return []
                except ValueError:
                    continue

        return [
            ValidationIssue(
                row_number=row_number,
                field_name=field.name,
                severity="error",
                error_code="INVALID_DATE",
                message="The field value is not a valid date for the configured formats.",
                raw_value=value,
                suggested_fix=", ".join(field.date_formats),
            )
        ]

    def _is_excel_serial_date(self, value: str) -> bool:
        try:
            serial = Decimal(value)
        except InvalidOperation:
            return False

        return Decimal("1") <= serial <= Decimal("99999")

    def _validate_decimal(
        self,
        row_number: int,
        field: ValidationField,
        value: str,
    ) -> list[ValidationIssue]:
        try:
            parsed = Decimal(value.replace(",", ""))
        except InvalidOperation:
            return [
                ValidationIssue(
                    row_number=row_number,
                    field_name=field.name,
                    severity="error",
                    error_code="INVALID_DECIMAL",
                    message="The field value is not a valid decimal number.",
                    raw_value=value,
                )
            ]

        return self._validate_min_max(row_number, field, value, parsed)

    def _validate_integer(
        self,
        row_number: int,
        field: ValidationField,
        value: str,
    ) -> list[ValidationIssue]:
        try:
            parsed = Decimal(value.replace(",", ""))
        except InvalidOperation:
            return [
                ValidationIssue(
                    row_number=row_number,
                    field_name=field.name,
                    severity="error",
                    error_code="INVALID_INTEGER",
                    message="The field value is not a valid integer.",
                    raw_value=value,
                )
            ]

        if parsed != parsed.to_integral_value():
            return [
                ValidationIssue(
                    row_number=row_number,
                    field_name=field.name,
                    severity="error",
                    error_code="INVALID_INTEGER",
                    message="The field value is not a whole number.",
                    raw_value=value,
                )
            ]

        return self._validate_min_max(row_number, field, value, parsed)

    def _validate_min_max(
        self,
        row_number: int,
        field: ValidationField,
        value: str,
        parsed: Decimal,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if field.min_value is not None and parsed < Decimal(field.min_value):
            issues.append(
                ValidationIssue(
                    row_number=row_number,
                    field_name=field.name,
                    severity="error",
                    error_code="VALUE_BELOW_MINIMUM",
                    message=f"The field value is below the configured minimum of {field.min_value}.",
                    raw_value=value,
                )
            )

        if field.max_value is not None and parsed > Decimal(field.max_value):
            issues.append(
                ValidationIssue(
                    row_number=row_number,
                    field_name=field.name,
                    severity="error",
                    error_code="VALUE_ABOVE_MAXIMUM",
                    message=f"The field value is above the configured maximum of {field.max_value}.",
                    raw_value=value,
                )
            )

        return issues

    def _is_blank_row(self, row: list[str]) -> bool:
        return all(not value.strip() for value in row)

    def _trim_trailing_blank(self, row: list[str]) -> list[str]:
        trimmed = list(row)
        while trimmed and not trimmed[-1].strip():
            trimmed.pop()
        return trimmed
