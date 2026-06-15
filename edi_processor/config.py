from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeSettings:
    app_name: str = "cfi-edi-processor"
    environment: str = "development"
    logs_directory: Path = Path("logs")
    working_directory: Path = Path("work")
    live_provider_allow_list: tuple[str, ...] = ()
    fail_on_file_statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmailSettings:
    enabled: bool = False
    send_provider_validation_emails: bool = False
    smtp_server: str = "smtp.office365.com"
    smtp_port: int = 587
    use_ssl: bool = True
    from_address: str = ""
    default_recipients: tuple[str, ...] = ()
    username_env: str = "SMTP_USERNAME"
    password_env: str = "SMTP_PASSWORD"


@dataclass(frozen=True)
class TransactionReportSettings:
    enabled: bool = True
    send_email: bool = False
    recipients: tuple[str, ...] = ()
    subject_prefix: str = "EDI transaction count report"


@dataclass(frozen=True)
class PathSettings:
    source_root: Path = Path(".")
    qds_processor_root: Path = Path(".")
    x12_files_directory: Path = Path("X12 FILES")
    converted_837i_directory: Path = Path("X12 837I CONVERTED TO 837P")
    incoming_directory: Path = Path("incoming")
    inbox_directory: Path = Path("inbox")
    converter_logs_directory: Path = Path("logs/converters")
    validation_reports_directory: Path = Path("logs/validation")
    templates_directory: Path = Path("templates")
    rendered_notifications_directory: Path = Path("logs/notifications")


@dataclass(frozen=True)
class ConverterSettings:
    rx_flatfile_to_837p: Path = Path("RXFLATFILE_TO_837P_47.exe")
    convert_837i_to_837p: Path = Path("CONVERT_837I_TO_837P.exe")
    timeout_seconds: int = 300


@dataclass(frozen=True)
class PublishSettings:
    stability_checks: int = 3
    stability_interval_seconds: float = 2.0
    max_retries: int = 5
    retry_delay_seconds: float = 5.0
    temp_suffix: str = ".copying"
    observe_inbox: bool = False
    inbox_observation_timeout_seconds: float = 60.0
    inbox_observation_interval_seconds: float = 5.0


@dataclass(frozen=True)
class DuplicateCheckSettings:
    enabled: bool = False
    driver: str = "ODBC Driver 17 for SQL Server"
    server: str = ""
    database: str = ""
    trusted_connection: bool = True
    username_env: str = "TPM_DB_USERNAME"
    password_env: str = "TPM_DB_PASSWORD"
    table: str = "batch"
    file_name_column: str = "file_name"
    match_mode: str = "contains"
    fail_on_unavailable: bool = True


@dataclass(frozen=True)
class ArchiveSettings:
    enabled: bool = True
    folder_name: str = "backup"
    date_format: str = "%m-%d-%Y"


@dataclass(frozen=True)
class PrefixRule:
    values: tuple[str, ...] = ()
    add_if_missing: bool = False
    reject_if_missing: bool = False
    derive_from: str | None = None
    reject_if_multiple_locations: bool = False


@dataclass(frozen=True)
class FileFormatSettings:
    extensions: tuple[str, ...] = ()
    delimiter: str | None = None
    header_row: int | None = None
    data_start_row: int | None = None


@dataclass(frozen=True)
class PreprocessingSettings:
    enabled: bool = False
    kind: str | None = None
    output_format: str | None = None


@dataclass(frozen=True)
class ValidationSettings:
    enabled: bool = True
    schema: str | None = None


@dataclass(frozen=True)
class ValidationField:
    name: str
    required: bool = False
    data_type: str = "string"
    date_formats: tuple[str, ...] = ()
    pattern: str | None = None
    allowed_values: tuple[str, ...] = ()
    min_value: str | None = None
    max_value: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationSchema:
    key: str
    file_type: str
    delimiter: str | None = None
    header_row: int | None = None
    data_start_row: int | None = None
    allow_blank_rows: bool = True
    strict_column_count: bool = True
    malformed_quote_check: bool = True
    fields: tuple[ValidationField, ...] = ()


@dataclass(frozen=True)
class NotificationSettings:
    email: str = ""
    sub_locations: dict[str, "NotificationSettings"] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderSettings:
    key: str
    name: str
    folder: str
    aliases: tuple[str, ...] = ()
    auto_process: bool = False
    archive: ArchiveSettings = field(default_factory=ArchiveSettings)
    notification: NotificationSettings = field(default_factory=NotificationSettings)
    prefix: PrefixRule = field(default_factory=PrefixRule)
    file_format: FileFormatSettings = field(default_factory=FileFormatSettings)
    preprocessing: PreprocessingSettings = field(default_factory=PreprocessingSettings)
    validation: ValidationSettings = field(default_factory=ValidationSettings)
    converter: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppSettings:
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    email: EmailSettings = field(default_factory=EmailSettings)
    transaction_reports: TransactionReportSettings = field(
        default_factory=TransactionReportSettings
    )
    paths: PathSettings = field(default_factory=PathSettings)
    converters: ConverterSettings = field(default_factory=ConverterSettings)
    publish: PublishSettings = field(default_factory=PublishSettings)
    duplicate_check: DuplicateCheckSettings = field(default_factory=DuplicateCheckSettings)
    providers: tuple[ProviderSettings, ...] = ()
    validation_schemas: dict[str, ValidationSchema] = field(default_factory=dict)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_settings(config_path: Path) -> AppSettings:
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent

    runtime_data = data.get("runtime", {})
    email_data = data.get("email", {})
    transaction_reports_data = data.get("transactionReports", {})
    paths_data = data.get("paths", {})
    converters_data = data.get("converters", {})
    publish_data = data.get("publish", {})
    duplicate_check_data = data.get("duplicateCheck", {})

    runtime = RuntimeSettings(
        app_name=str(runtime_data.get("appName", "cfi-edi-processor")),
        environment=str(runtime_data.get("environment", "development")),
        logs_directory=_resolve_path(base_dir, runtime_data.get("logsDirectory", "logs")),
        working_directory=_resolve_path(base_dir, runtime_data.get("workingDirectory", "work")),
        live_provider_allow_list=tuple(
            str(item) for item in runtime_data.get("liveProviderAllowList", [])
        ),
        fail_on_file_statuses=tuple(
            str(item) for item in runtime_data.get("failOnFileStatuses", [])
        ),
    )

    email = EmailSettings(
        enabled=bool(email_data.get("enabled", False)),
        send_provider_validation_emails=bool(
            email_data.get("sendProviderValidationEmails", False)
        ),
        smtp_server=str(email_data.get("smtpServer", "smtp.office365.com")),
        smtp_port=int(email_data.get("smtpPort", 587)),
        use_ssl=bool(email_data.get("useSsl", True)),
        from_address=str(email_data.get("fromAddress", "")),
        default_recipients=tuple(str(item) for item in email_data.get("defaultRecipients", [])),
        username_env=str(email_data.get("usernameEnv", "SMTP_USERNAME")),
        password_env=str(email_data.get("passwordEnv", "SMTP_PASSWORD")),
    )

    transaction_reports = TransactionReportSettings(
        enabled=bool(transaction_reports_data.get("enabled", True)),
        send_email=bool(transaction_reports_data.get("sendEmail", False)),
        recipients=tuple(str(item) for item in transaction_reports_data.get("recipients", [])),
        subject_prefix=str(
            transaction_reports_data.get(
                "subjectPrefix",
                "EDI transaction count report",
            )
        ),
    )

    paths = PathSettings(
        source_root=_resolve_path(base_dir, paths_data.get("sourceRoot", ".")),
        qds_processor_root=_resolve_path(base_dir, paths_data.get("qdsProcessorRoot", ".")),
        x12_files_directory=_resolve_path(base_dir, paths_data.get("x12FilesDirectory", "X12 FILES")),
        converted_837i_directory=_resolve_path(
            base_dir,
            paths_data.get("converted837IDirectory", "X12 837I CONVERTED TO 837P"),
        ),
        incoming_directory=_resolve_path(base_dir, paths_data.get("incomingDirectory", "incoming")),
        inbox_directory=_resolve_path(base_dir, paths_data.get("inboxDirectory", "inbox")),
        converter_logs_directory=_resolve_path(
            base_dir,
            paths_data.get("converterLogsDirectory", "logs/converters"),
        ),
        validation_reports_directory=_resolve_path(
            base_dir,
            paths_data.get("validationReportsDirectory", "logs/validation"),
        ),
        templates_directory=_resolve_path(base_dir, paths_data.get("templatesDirectory", "templates")),
        rendered_notifications_directory=_resolve_path(
            base_dir,
            paths_data.get("renderedNotificationsDirectory", "logs/notifications"),
        ),
    )

    converters = ConverterSettings(
        rx_flatfile_to_837p=_resolve_path(
            base_dir,
            converters_data.get("rxFlatfileTo837P", "RXFLATFILE_TO_837P_47.exe"),
        ),
        convert_837i_to_837p=_resolve_path(
            base_dir,
            converters_data.get("convert837ITo837P", "CONVERT_837I_TO_837P.exe"),
        ),
        timeout_seconds=int(converters_data.get("timeoutSeconds", 300)),
    )

    publish = PublishSettings(
        stability_checks=int(publish_data.get("stabilityChecks", 3)),
        stability_interval_seconds=float(publish_data.get("stabilityIntervalSeconds", 2.0)),
        max_retries=int(publish_data.get("maxRetries", 5)),
        retry_delay_seconds=float(publish_data.get("retryDelaySeconds", 5.0)),
        temp_suffix=str(publish_data.get("tempSuffix", ".copying")),
        observe_inbox=bool(publish_data.get("observeInbox", False)),
        inbox_observation_timeout_seconds=float(
            publish_data.get("inboxObservationTimeoutSeconds", 60.0)
        ),
        inbox_observation_interval_seconds=float(
            publish_data.get("inboxObservationIntervalSeconds", 5.0)
        ),
    )

    duplicate_check = DuplicateCheckSettings(
        enabled=bool(duplicate_check_data.get("enabled", False)),
        driver=str(duplicate_check_data.get("driver", "ODBC Driver 17 for SQL Server")),
        server=str(duplicate_check_data.get("server", "")),
        database=str(duplicate_check_data.get("database", "")),
        trusted_connection=bool(duplicate_check_data.get("trustedConnection", True)),
        username_env=str(duplicate_check_data.get("usernameEnv", "TPM_DB_USERNAME")),
        password_env=str(duplicate_check_data.get("passwordEnv", "TPM_DB_PASSWORD")),
        table=str(duplicate_check_data.get("table", "batch")),
        file_name_column=str(duplicate_check_data.get("fileNameColumn", "file_name")),
        match_mode=str(duplicate_check_data.get("matchMode", "contains")),
        fail_on_unavailable=bool(duplicate_check_data.get("failOnUnavailable", True)),
    )

    providers = tuple(_load_provider(item) for item in data.get("providers", []))
    validation_schemas = {
        str(item["key"]): _load_validation_schema(item)
        for item in data.get("validationSchemas", [])
    }

    settings = AppSettings(
        runtime=runtime,
        email=email,
        transaction_reports=transaction_reports,
        paths=paths,
        converters=converters,
        publish=publish,
        duplicate_check=duplicate_check,
        providers=providers,
        validation_schemas=validation_schemas,
    )
    _validate_settings(settings)
    return settings


def _load_provider(data: dict[str, Any]) -> ProviderSettings:
    archive_data = data.get("archive", {})
    notification_data = data.get("notification", {})
    prefix_data = data.get("prefix", {})
    file_format_data = data.get("fileFormat", {})
    preprocessing_data = data.get("preprocessing", {})
    validation_data = data.get("validation", {})

    return ProviderSettings(
        key=str(data["key"]),
        name=str(data["name"]),
        folder=str(data["folder"]),
        aliases=tuple(str(item) for item in data.get("aliases", [])),
        auto_process=bool(data.get("autoProcess", False)),
        archive=ArchiveSettings(
            enabled=bool(archive_data.get("enabled", True)),
            folder_name=str(archive_data.get("folderName", "backup")),
            date_format=str(archive_data.get("dateFormat", "%m-%d-%Y")),
        ),
        notification=_load_notification(notification_data),
        prefix=PrefixRule(
            values=tuple(str(item) for item in prefix_data.get("values", [])),
            add_if_missing=bool(prefix_data.get("addIfMissing", False)),
            reject_if_missing=bool(prefix_data.get("rejectIfMissing", False)),
            derive_from=prefix_data.get("deriveFrom"),
            reject_if_multiple_locations=bool(prefix_data.get("rejectIfMultipleLocations", False)),
        ),
        file_format=FileFormatSettings(
            extensions=tuple(str(item) for item in file_format_data.get("extensions", [])),
            delimiter=file_format_data.get("delimiter"),
            header_row=file_format_data.get("headerRow"),
            data_start_row=file_format_data.get("dataStartRow"),
        ),
        preprocessing=PreprocessingSettings(
            enabled=bool(preprocessing_data.get("enabled", False)),
            kind=preprocessing_data.get("kind"),
            output_format=preprocessing_data.get("outputFormat"),
        ),
        validation=ValidationSettings(
            enabled=bool(validation_data.get("enabled", True)),
            schema=validation_data.get("schema"),
        ),
        converter=data.get("converter"),
        notes=tuple(str(item) for item in data.get("notes", [])),
    )


def _load_notification(data: dict[str, Any]) -> NotificationSettings:
    return NotificationSettings(
        email=str(data.get("email", "")),
        sub_locations={
            str(key): _load_notification(value)
            for key, value in data.get("subLocations", {}).items()
        },
    )


def _load_validation_schema(data: dict[str, Any]) -> ValidationSchema:
    return ValidationSchema(
        key=str(data["key"]),
        file_type=str(data.get("fileType", "csv")),
        delimiter=data.get("delimiter"),
        header_row=data.get("headerRow"),
        data_start_row=data.get("dataStartRow"),
        allow_blank_rows=bool(data.get("allowBlankRows", True)),
        strict_column_count=bool(data.get("strictColumnCount", True)),
        malformed_quote_check=bool(data.get("malformedQuoteCheck", True)),
        fields=tuple(_load_validation_field(item) for item in data.get("fields", [])),
    )


def _load_validation_field(data: dict[str, Any]) -> ValidationField:
    return ValidationField(
        name=str(data["name"]),
        required=bool(data.get("required", False)),
        data_type=str(data.get("type", "string")),
        date_formats=tuple(str(item) for item in data.get("dateFormats", [])),
        pattern=data.get("pattern"),
        allowed_values=tuple(str(item) for item in data.get("allowedValues", [])),
        min_value=data.get("min"),
        max_value=data.get("max"),
        notes=tuple(str(item) for item in data.get("notes", [])),
    )


def _validate_settings(settings: AppSettings) -> None:
    missing_schemas = [
        provider.validation.schema
        for provider in settings.providers
        if provider.validation.enabled
        and provider.validation.schema
        and provider.validation.schema not in settings.validation_schemas
    ]
    if missing_schemas:
        missing = ", ".join(sorted(set(missing_schemas)))
        raise ValueError(f"Missing validation schema definitions: {missing}")

    duplicate_check = settings.duplicate_check
    if duplicate_check.enabled:
        missing_database_settings = [
            name
            for name, value in (
                ("server", duplicate_check.server),
                ("database", duplicate_check.database),
                ("table", duplicate_check.table),
                ("fileNameColumn", duplicate_check.file_name_column),
            )
            if not value
        ]
        if missing_database_settings:
            missing = ", ".join(missing_database_settings)
            raise ValueError(f"Missing duplicate check settings: {missing}")

        if duplicate_check.match_mode not in {"contains", "exact"}:
            raise ValueError("duplicateCheck.matchMode must be either 'contains' or 'exact'.")


def _resolve_path(base_dir: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path
