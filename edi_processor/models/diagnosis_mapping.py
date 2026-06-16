from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from edi_processor.models.validation import ValidationResult


@dataclass(frozen=True)
class DiagnosisCodeMapping:
    row_number: int
    calculated_percentage: Decimal
    rounded_percentage: Decimal
    diagnosis_code: str


@dataclass(frozen=True)
class DiagnosisMappingResult:
    validation_result: ValidationResult
    mappings: tuple[DiagnosisCodeMapping, ...] = ()

    @property
    def is_valid(self) -> bool:
        return self.validation_result.is_valid


@dataclass(frozen=True)
class X12DiagnosisUpdateResult:
    succeeded: bool
    updated_segments: int = 0
    message: str | None = None
    error_code: str | None = None
