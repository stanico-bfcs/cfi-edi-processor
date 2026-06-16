from __future__ import annotations

import logging
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from edi_processor.config import EmailSettings


class EmailService:
    def __init__(self, settings: EmailSettings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def send(
        self,
        subject: str,
        recipients: tuple[str, ...],
        text_body: str,
        html_body: str | None,
        attachments: tuple[Path, ...],
        run_id: str,
    ) -> bool:
        if not self._can_send(recipients, run_id):
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.from_address
        message["To"] = ", ".join(recipients)
        message.set_content(text_body)

        if html_body:
            message.add_alternative(html_body, subtype="html")

        for attachment in attachments:
            self._attach_file(message, attachment)

        username = os.getenv(self.settings.username_env)
        password = os.getenv(self.settings.password_env)

        with smtplib.SMTP(self.settings.smtp_server, self.settings.smtp_port, timeout=60) as smtp:
            if self.settings.use_ssl:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)

        self.logger.info(
            f"Sent email to {', '.join(recipients)}",
            extra={"run_id": run_id, "status": "email_sent"},
        )
        return True

    def _can_send(self, recipients: tuple[str, ...], run_id: str) -> bool:
        if not self.settings.enabled:
            self.logger.info(
                "Email sending disabled by configuration",
                extra={"run_id": run_id, "status": "email_disabled"},
            )
            return False

        if not self.settings.from_address:
            self.logger.warning(
                "Email sending skipped because fromAddress is not configured",
                extra={"run_id": run_id, "status": "email_missing_sender"},
            )
            return False

        if not recipients:
            self.logger.warning(
                "Email sending skipped because there are no recipients",
                extra={"run_id": run_id, "status": "email_missing_recipients"},
            )
            return False

        return True

    def _attach_file(self, message: EmailMessage, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.logger.warning(f"Email attachment skipped because it does not exist: {path}")
            return

        content_type, _ = mimetypes.guess_type(path)
        if content_type:
            maintype, subtype = content_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"

        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
