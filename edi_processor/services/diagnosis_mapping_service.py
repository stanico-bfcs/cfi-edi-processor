from __future__ import annotations

import csv
from decimal import (
    Decimal,
    DivisionByZero,
    InvalidOperation,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
)
from pathlib import Path

from edi_processor.config import DiagnosisMappingSettings, ValidationSchema
from edi_processor.models.diagnosis_mapping import (
    DiagnosisCodeMapping,
    DiagnosisMappingResult,
)
from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.validation import ValidationIssue, ValidationResult
from edi_processor.services.excel_reader import ExcelReader


class DiagnosisMappingService:
    rounding_modes = {
        "half_up": ROUND_HALF_UP,
        "half_even": ROUND_HALF_EVEN,
        "floor": ROUND_FLOOR,
        "ceiling": ROUND_CEILING,
        "truncate": ROUND_DOWN,
    }

    def __init__(self, schemas: dict[str, ValidationSchema]) -> None:
        self.schemas = schemas
        self.excel_reader = ExcelReader()

    def map_for_submission(self, submission: FileSubmission) -> DiagnosisMappingResult:
        settings = submission.provider.diagnosis_mapping
        if not settings.enabled:
            return DiagnosisMappingResult(ValidationResult(is_valid=True))

        schema = self._schema(submission)
        if schema is None:
            return self._invalid(
                ValidationIssue(
                    row_number=None,
                    field_name=None,
                    severity="error",
                    error_code="DIAGNOSIS_MAPPING_SCHEMA_MISSING",
                    message="Diagnosis mapping is enabled but no validation schema is configured.",
                )
            )

        try:
            rows = self._read_rows(submission.path, schema)
        except (OSError, csv.Error, ValueError) as exc:
            return self._invalid(
                ValidationIssue(
                    row_number=None,
                    field_name=None,
                    severity="error",
                    error_code="DIAGNOSIS_MAPPING_READ_FAILED",
                    message=str(exc),
                )
            )

        return self._map_rows(rows, schema, settings)

    def _map_rows(
        self,
        rows: list[list[str]],
        schema: ValidationSchema,
        settings: DiagnosisMappingSettings,
    ) -> DiagnosisMappingResult:
        header_index = (schema.header_row or 1) - 1
        data_start_index = (schema.data_start_row or header_index + 2) - 1
        headers = [field.name for field in schema.fields]
        numerator_index = self._field_index(headers, settings.numerator_field)
        denominator_index = self._field_index(headers, settings.denominator_field)

        if numerator_index is None or denominator_index is None:
            missing = [
                field
                for field, index in (
                    (settings.numerator_field, numerator_index),
                    (settings.denominator_field, denominator_index),
                )
                if index is None
            ]
            return self._invalid(
                ValidationIssue(
                    row_number=schema.header_row,
                    field_name=", ".join(missing),
                    severity="error",
                    error_code="DIAGNOSIS_MAPPING_FIELD_MISSING",
                    message="Diagnosis mapping references a field that is not in the validation schema.",
                )
            )

        issues: list[ValidationIssue] = []
        mappings: list[DiagnosisCodeMapping] = []
        for row_index, row in enumerate(rows[data_start_index:], start=data_start_index + 1):
            row = self._trim_trailing_blank(row)
            if self._is_blank_row(row):
                continue

            numerator_value = row[numerator_index].strip() if numerator_index < len(row) else ""
            denominator_value = (
                row[denominator_index].strip() if denominator_index < len(row) else ""
            )
            mapping, issue = self._map_row(
                row_number=row_index,
                row=row,
                numerator_value=numerator_value,
                denominator_value=denominator_value,
                settings=settings,
            )
            if issue is not None:
                issues.append(issue)
            elif mapping is not None:
                mappings.append(mapping)

        return DiagnosisMappingResult(
            validation_result=ValidationResult(is_valid=not issues, issues=tuple(issues)),
            mappings=tuple(mappings),
        )

    def _map_row(
        self,
        row_number: int,
        row: list[str],
        numerator_value: str,
        denominator_value: str,
        settings: DiagnosisMappingSettings,
    ) -> tuple[DiagnosisCodeMapping | None, ValidationIssue | None]:
        try:
            numerator = self._decimal(numerator_value)
            denominator = self._decimal(denominator_value)
        except InvalidOperation:
            return None, ValidationIssue(
                row_number=row_number,
                field_name=f"{settings.numerator_field}/{settings.denominator_field}",
                severity="error",
                error_code="DIAGNOSIS_MAPPING_INVALID_DECIMAL",
                message="Could not calculate the diagnosis percentage because CoPay-CI or Price-CI is not numeric.",
                raw_value=", ".join(row),
                suggested_fix="Confirm CoPay-CI and Price-CI are valid numeric values.",
            )

        if denominator == 0:
            return None, ValidationIssue(
                row_number=row_number,
                field_name=settings.denominator_field,
                severity="error",
                error_code="DIAGNOSIS_MAPPING_ZERO_DENOMINATOR",
                message="Could not calculate the diagnosis percentage because Price-CI is zero.",
                raw_value=", ".join(row),
                suggested_fix="Correct Price-CI to a non-zero value.",
            )

        try:
            calculated_percentage = (numerator / denominator) * Decimal("100")
        except (DivisionByZero, InvalidOperation):
            return None, ValidationIssue(
                row_number=row_number,
                field_name=f"{settings.numerator_field}/{settings.denominator_field}",
                severity="error",
                error_code="DIAGNOSIS_MAPPING_CALCULATION_FAILED",
                message="Could not calculate the diagnosis percentage.",
                raw_value=", ".join(row),
            )

        rounded_percentage = self._round(calculated_percentage, settings)
        percentage_key = self._percentage_key(rounded_percentage)
        diagnosis_code = settings.allowed_percentages.get(percentage_key)
        if diagnosis_code is None:
            allowed = ", ".join(f"{key}%" for key in settings.allowed_percentages)
            return None, ValidationIssue(
                row_number=row_number,
                field_name=f"{settings.numerator_field}/{settings.denominator_field}",
                severity="error",
                error_code="DIAGNOSIS_PERCENTAGE_UNMAPPED",
                message=(
                    f"CoPay-CI / Price-CI calculated to "
                    f"{self._percentage_key(calculated_percentage)}%, rounded to "
                    f"{percentage_key}%, which is not configured for a diagnosis code."
                ),
                raw_value=", ".join(row),
                suggested_fix=f"Allowed rounded percentages are: {allowed}.",
            )

        return (
            DiagnosisCodeMapping(
                row_number=row_number,
                calculated_percentage=calculated_percentage,
                rounded_percentage=rounded_percentage,
                diagnosis_code=diagnosis_code,
            ),
            None,
        )

    def _read_rows(self, path: Path, schema: ValidationSchema) -> list[list[str]]:
        if schema.file_type == "xlsx":
            return self.excel_reader.read_rows(path)

        if schema.file_type != "csv":
            raise ValueError(
                f"Diagnosis mapping is not implemented for file type: {schema.file_type}."
            )

        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            content = path.read_text(encoding="cp1252")
        return list(csv.reader(content.splitlines(), delimiter=schema.delimiter or ",", strict=True))

    def _schema(self, submission: FileSubmission) -> ValidationSchema | None:
        schema_key = submission.provider.validation.schema
        if not schema_key:
            return None
        return self.schemas.get(schema_key)

    def _field_index(self, headers: list[str], field_name: str) -> int | None:
        try:
            return headers.index(field_name)
        except ValueError:
            return None

    def _decimal(self, value: str) -> Decimal:
        return Decimal(value.replace(",", "").strip())

    def _round(
        self,
        value: Decimal,
        settings: DiagnosisMappingSettings,
    ) -> Decimal:
        if not settings.rounding.enabled:
            return value

        quantizer = Decimal("1").scaleb(-settings.rounding.decimal_places)
        rounding = self.rounding_modes[settings.rounding.mode]
        return value.quantize(quantizer, rounding=rounding)

    def _percentage_key(self, value: Decimal) -> str:
        normalized = value.normalize()
        if normalized == normalized.to_integral_value():
            return str(normalized.quantize(Decimal("1")))
        return format(normalized, "f")

    def _trim_trailing_blank(self, row: list[str]) -> list[str]:
        trimmed = list(row)
        while trimmed and not trimmed[-1].strip():
            trimmed.pop()
        return trimmed

    def _is_blank_row(self, row: list[str]) -> bool:
        return all(not value.strip() for value in row)

    def _invalid(self, issue: ValidationIssue) -> DiagnosisMappingResult:
        return DiagnosisMappingResult(
            validation_result=ValidationResult(is_valid=False, issues=(issue,))
        )
