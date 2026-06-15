from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from edi_processor.config import EmailSettings
from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.notification import NotificationRenderResult
from edi_processor.models.validation import ValidationResult


class ProviderNotificationService:
    def __init__(
        self,
        templates_directory: Path,
        rendered_notifications_directory: Path,
        email_settings: EmailSettings,
    ) -> None:
        self.templates_directory = templates_directory
        self.rendered_notifications_directory = rendered_notifications_directory
        self.email_settings = email_settings
        self.logger = logging.getLogger(__name__)

    def render_validation_failed(
        self,
        submission: FileSubmission,
        validation_result: ValidationResult,
        run_id: str,
    ) -> NotificationRenderResult:
        template_data = {
            "run_id": run_id,
            "provider_key": submission.provider.key,
            "provider_name": submission.provider.name,
            "file_name": submission.file_name,
            "issues": [asdict(issue) for issue in validation_result.issues],
        }
        subject = f"Validation failed: {submission.provider.name} - {submission.file_name}"
        try:
            environment = self._jinja_environment()
            text_body = environment.get_template(
                "provider_notifications/validation_failed.txt.j2"
            ).render(**template_data)
            html_body = environment.get_template(
                "provider_notifications/validation_failed.html.j2"
            ).render(**template_data)
        except RuntimeError as exc:
            self.logger.warning(str(exc))
            text_body = self._fallback_text(template_data)
            html_body = self._fallback_html(template_data)

        output_dir = self.rendered_notifications_directory / datetime.now().strftime("%m-%d-%Y")
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = self._safe_stem(submission.path.stem)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        text_path = self._unique_destination(
            output_dir / f"{timestamp}_{submission.provider.key}_{safe_stem}_validation_failed.txt"
        )
        html_path = self._unique_destination(
            output_dir / f"{timestamp}_{submission.provider.key}_{safe_stem}_validation_failed.html"
        )
        text_path.write_text(text_body, encoding="utf-8")
        html_path.write_text(html_body, encoding="utf-8")

        recipients = self._recipients_for(submission)
        send_enabled = self.email_settings.enabled and self.email_settings.send_provider_validation_emails
        self.logger.info(
            f"Rendered provider validation notification for {submission.file_name}",
            extra={
                "run_id": run_id,
                "provider": submission.provider.key,
                "file_name": submission.file_name,
                "status": "provider_notification_rendered",
            },
        )
        if not send_enabled:
            self.logger.info(
                "Provider validation email sending is disabled by configuration",
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "provider_notification_send_disabled",
                },
            )

        return NotificationRenderResult(
            subject=subject,
            recipients=recipients,
            text_path=text_path,
            html_path=html_path,
            send_enabled=send_enabled,
        )

    def read_rendered_bodies(self, notification: NotificationRenderResult) -> tuple[str, str]:
        return (
            notification.text_path.read_text(encoding="utf-8"),
            notification.html_path.read_text(encoding="utf-8"),
        )

    def _jinja_environment(self):
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
        except ImportError as exc:
            raise RuntimeError(
                "Jinja2 is required to render provider notifications. Install project dependencies first."
            ) from exc

        return Environment(
            loader=FileSystemLoader(self.templates_directory),
            autoescape=select_autoescape(enabled_extensions=("html", "j2")),
        )

    def _fallback_text(self, data: dict) -> str:
        lines = [
            f"Provider: {data['provider_name']}",
            f"File: {data['file_name']}",
            f"Received/Run ID: {data['run_id']}",
            f"Issue count: {len(data['issues'])}",
            "",
            "Validation issues:",
        ]
        for issue in data["issues"]:
            lines.extend(
                [
                    f"- Severity: {issue['severity']}",
                    f"  Code: {issue['error_code']}",
                    f"  Row: {issue['row_number'] or ''}",
                    f"  Field: {issue['field_name'] or ''}",
                    f"  Message: {issue['message']}",
                    f"  Raw Value: {issue['raw_value'] or ''}",
                    f"  Suggested Fix: {issue['suggested_fix'] or ''}",
                ]
            )
        return "\n".join(lines)

    def _fallback_html(self, data: dict) -> str:
        rows = "\n".join(
            "<tr>"
            f"<td>{issue['severity']}</td>"
            f"<td>{issue['error_code']}</td>"
            f"<td>{issue['row_number'] or ''}</td>"
            f"<td>{issue['field_name'] or ''}</td>"
            f"<td>{issue['message']}</td>"
            f"<td>{issue['raw_value'] or ''}</td>"
            f"<td>{issue['suggested_fix'] or ''}</td>"
            "</tr>"
            for issue in data["issues"]
        )
        return (
            "<!DOCTYPE html><html><body>"
            f"<p>Provider: {data['provider_name']}</p>"
            f"<p>File: {data['file_name']}</p>"
            f"<p>Received/Run ID: {data['run_id']}</p>"
            f"<p>Issue count: {len(data['issues'])}</p>"
            "<table border=\"1\"><thead><tr>"
            "<th>Severity</th><th>Code</th><th>Row</th><th>Field</th>"
            "<th>Message</th><th>Raw Value</th><th>Suggested Fix</th>"
            "</tr></thead><tbody>"
            f"{rows}"
            "</tbody></table>"
            "</body></html>"
        )

    def _recipients_for(self, submission: FileSubmission) -> tuple[str, ...]:
        email = submission.provider.notification.email
        if email:
            return (email,)
        return self.email_settings.default_recipients

    def _safe_stem(self, value: str) -> str:
        safe = "".join(character if character.isalnum() else "_" for character in value)
        return safe.strip("_") or "file"

    def _unique_destination(self, destination: Path) -> Path:
        if not destination.exists():
            return destination

        stem = destination.stem
        suffix = destination.suffix
        parent = destination.parent
        counter = 1

        while True:
            candidate = parent / f"{stem}_({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1
