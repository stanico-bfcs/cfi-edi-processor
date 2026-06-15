from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationIssue:
    row_number: int | None
    field_name: str | None
    severity: str
    error_code: str
    message: str
    raw_value: str | None = None
    suggested_fix: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    issues: tuple[ValidationIssue, ...] = ()
