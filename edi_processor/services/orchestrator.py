from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from edi_processor.config import AppSettings
from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.processing import FileProcessingResult
from edi_processor.models.validation import ValidationResult
from edi_processor.runtime import RunContext
from edi_processor.services.archive_service import ArchiveService
from edi_processor.services.converter_service import ConverterService
from edi_processor.services.duplicate_check_service import DuplicateCheckService
from edi_processor.services.email_service import EmailService
from edi_processor.services.file_discovery_service import FileDiscoveryService
from edi_processor.services.file_verification_service import FileVerificationService
from edi_processor.services.inbox_observer_service import InboxObserverService
from edi_processor.services.incoming_publish_service import IncomingPublishService
from edi_processor.services.preprocessing_service import PreprocessingService
from edi_processor.services.prefix_service import PrefixService
from edi_processor.services.processing_summary_service import ProcessingSummaryService
from edi_processor.services.provider_notification_service import ProviderNotificationService
from edi_processor.services.received_date_override_service import ReceivedDateOverrideService
from edi_processor.services.transaction_count_service import TransactionCountService
from edi_processor.services.transaction_report_service import TransactionReportService
from edi_processor.services.validation_report_service import ValidationReportService
from edi_processor.services.validation_service import ValidationService
from edi_processor.services.x12_date_update_service import X12DateUpdateService
from edi_processor.services.x12_validation_service import X12ValidationService


class Orchestrator:
    def __init__(self, settings: AppSettings, context: RunContext) -> None:
        self.settings = settings
        self.context = context
        self.logger = logging.getLogger(__name__)
        self.discovery_service = FileDiscoveryService(settings)
        self.processing_summary_service = ProcessingSummaryService(settings.runtime.logs_directory)
        self.received_date_override_service = ReceivedDateOverrideService(
            paths=settings.paths,
            settings=settings.received_date_overrides,
        )
        self.archive_service = ArchiveService()
        self.prefix_service = PrefixService()
        self.duplicate_check_service = DuplicateCheckService(settings.duplicate_check)
        self.preprocessing_service = PreprocessingService(settings.runtime.working_directory)
        self.transaction_count_service = TransactionCountService(settings.validation_schemas)
        self.transaction_report_service = TransactionReportService(settings.runtime.logs_directory)
        self.validation_service = ValidationService(settings.validation_schemas)
        self.x12_validation_service = X12ValidationService(settings.x12_validation)
        self.validation_report_service = ValidationReportService(
            settings.paths.validation_reports_directory
        )
        self.email_service = EmailService(settings.email)
        self.file_verification_service = FileVerificationService()
        self.provider_notification_service = ProviderNotificationService(
            templates_directory=settings.paths.templates_directory,
            rendered_notifications_directory=settings.paths.rendered_notifications_directory,
            email_settings=settings.email,
        )
        self.converter_service = ConverterService(settings.paths, settings.converters)
        self.x12_date_update_service = X12DateUpdateService()
        self.publish_service = IncomingPublishService(settings.publish)
        self.inbox_observer_service = InboxObserverService(settings.publish)

    def run(self) -> int:
        self._validate_runtime_safety()
        started_at = datetime.now()
        self.logger.info(
            "Run started",
            extra={"run_id": self.context.run_id, "status": "started"},
        )
        self.logger.info(
            "Foundation runtime initialized",
            extra={"run_id": self.context.run_id, "status": "initialized"},
        )
        self.logger.info(
            f"Loaded {len(self.settings.providers)} provider configurations",
            extra={"run_id": self.context.run_id, "status": "config_loaded"},
        )
        self.logger.info(
            f"Loaded {len(self.settings.validation_schemas)} validation schemas",
            extra={"run_id": self.context.run_id, "status": "validation_schemas_loaded"},
        )
        overrides = self.received_date_override_service.load(self.context.run_id)
        submissions = self.discovery_service.discover(
            self.context.run_id,
            provider_filter=self.context.provider_filter,
        )
        submissions = self.received_date_override_service.apply(
            submissions=submissions,
            overrides=overrides,
            run_id=self.context.run_id,
        )
        self.logger.info(
            f"Discovered {len(submissions)} total files",
            extra={"run_id": self.context.run_id, "status": "discovery_completed"},
        )

        results = [self._process_submission(submission) for submission in submissions]
        exit_code = self._exit_code(results)
        completed_at = datetime.now()
        transaction_report_paths: tuple[Path, Path] | None = None
        if self.settings.transaction_reports.enabled:
            transaction_report_paths = self.transaction_report_service.write_report(
                results=results,
                run_id=self.context.run_id,
                completed_at=completed_at,
            )
        summary_paths = self.processing_summary_service.write_summary(
            results=results,
            run_id=self.context.run_id,
            dry_run=self.context.dry_run,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=exit_code,
        )
        self.logger.info(
            f"Processed {len(results)} file submissions",
            extra={"run_id": self.context.run_id, "status": "processing_completed"},
        )
        self.logger.info(
            f"Run summary ready: {summary_paths[0]}, {summary_paths[1]}",
            extra={"run_id": self.context.run_id, "status": "run_summary_ready"},
        )
        if transaction_report_paths:
            self.logger.info(
                f"Transaction count report ready: {transaction_report_paths[0]}, {transaction_report_paths[1]}",
                extra={"run_id": self.context.run_id, "status": "transaction_report_ready"},
            )
            self._send_transaction_report(transaction_report_paths)

        self.received_date_override_service.cleanup(
            overrides=overrides,
            run_id=self.context.run_id,
            dry_run=self.context.dry_run,
        )

        self.logger.info(
            "Run completed",
            extra={
                "run_id": self.context.run_id,
                "status": "completed",
                "exit_code": exit_code,
            },
        )
        return exit_code

    def _validate_runtime_safety(self) -> None:
        if self.context.dry_run:
            return

        if not self.context.allow_live:
            raise RuntimeError("Live processing requires --allow-live.")

        if not self.context.provider_filter:
            raise RuntimeError("Live processing requires at least one --provider value.")

        allowed = set(self.settings.runtime.live_provider_allow_list)
        requested = set(self.context.provider_filter)
        blocked = requested - allowed
        if blocked:
            blocked_list = ", ".join(sorted(blocked))
            raise RuntimeError(f"Provider is not allowed for live processing: {blocked_list}")

    def _process_submission(self, submission: FileSubmission) -> FileProcessingResult:
        if submission.file_name.upper().startswith("NO"):
            self.logger.info(
                "File marked with NO override prefix; skipping processing",
                extra={
                    "run_id": self.context.run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "override_skipped",
                },
            )
            return FileProcessingResult(
                provider_key=submission.provider.key,
                file_name=submission.file_name,
                status="override_skipped",
                message="File name starts with legacy NO override marker.",
                received_date=self._received_date_text(submission),
            )

        prefix_result = self.prefix_service.apply(
            submission=submission,
            run_id=self.context.run_id,
            dry_run=self.context.dry_run,
        )
        if not prefix_result.is_valid:
            return FileProcessingResult(
                provider_key=submission.provider.key,
                file_name=submission.file_name,
                status="prefix_failed",
                message=prefix_result.message,
                received_date=self._received_date_text(submission),
            )

        submission = prefix_result.submission
        duplicate_result = self.duplicate_check_service.check(
            submission=submission,
            run_id=self.context.run_id,
        )
        if not duplicate_result.succeeded:
            self.logger.error(
                duplicate_result.message,
                extra={
                    "run_id": self.context.run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "duplicate_check_failed",
                    "error": duplicate_result.error_code,
                },
            )
            return FileProcessingResult(
                provider_key=submission.provider.key,
                file_name=submission.file_name,
                status="duplicate_check_failed",
                message=duplicate_result.message,
                received_date=self._received_date_text(submission),
            )
        if duplicate_result.is_duplicate:
            return FileProcessingResult(
                provider_key=submission.provider.key,
                file_name=submission.file_name,
                status="duplicate_skipped",
                message=duplicate_result.message,
                received_date=self._received_date_text(submission),
            )

        original_submission = submission
        preprocessing_result = self.preprocessing_service.preprocess(
            submission=submission,
            run_id=self.context.run_id,
        )
        if not preprocessing_result.succeeded:
            self.logger.error(
                preprocessing_result.message,
                extra={
                    "run_id": self.context.run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "preprocessing_failed",
                    "error": preprocessing_result.error_code,
                },
            )
            return FileProcessingResult(
                provider_key=submission.provider.key,
                file_name=submission.file_name,
                status="preprocessing_failed",
                message=preprocessing_result.message,
                received_date=self._received_date_text(submission),
            )

        processed_submission = preprocessing_result.submission
        transaction_count, transaction_count_message = self._transaction_count(processed_submission)
        x12_validation_result = self.x12_validation_service.validate(
            submission=processed_submission,
            run_id=self.context.run_id,
        )
        if not x12_validation_result.is_valid:
            return self._handle_validation_failure(
                submission=processed_submission,
                validation_result=x12_validation_result,
                transaction_count=transaction_count,
                transaction_count_message=transaction_count_message,
                status="x12_validation_failed",
            )

        validation_result = self.validation_service.validate(
            submission=processed_submission,
            run_id=self.context.run_id,
        )
        if not validation_result.is_valid:
            return self._handle_validation_failure(
                submission=processed_submission,
                validation_result=validation_result,
                transaction_count=transaction_count,
                transaction_count_message=transaction_count_message,
                status="validation_failed",
            )

        expected_output = self._expected_converter_output(processed_submission)
        if not processed_submission.provider.converter:
            self.logger.info(
                "No converter configured for provider",
                extra={
                    "run_id": self.context.run_id,
                    "provider": processed_submission.provider.key,
                    "file_name": processed_submission.file_name,
                    "status": "converter_not_configured",
                },
            )
            return FileProcessingResult(
                provider_key=processed_submission.provider.key,
                file_name=processed_submission.file_name,
                status="converter_not_configured",
                transaction_count=transaction_count,
                transaction_count_message=transaction_count_message,
                received_date=self._received_date_text(processed_submission),
            )

        conversion_result = self.converter_service.run_converter(
            converter_key=processed_submission.provider.converter,
            input_file=processed_submission.path,
            provider_key=processed_submission.provider.key,
            run_id=self.context.run_id,
            dry_run=self.context.dry_run,
            expected_result_files=self._expected_result_logs(processed_submission.provider.converter),
        )
        if not self.context.dry_run and not conversion_result.succeeded:
            return FileProcessingResult(
                provider_key=processed_submission.provider.key,
                file_name=processed_submission.file_name,
                status="conversion_failed",
                message=conversion_result.error_message,
                transaction_count=transaction_count,
                transaction_count_message=transaction_count_message,
                received_date=self._received_date_text(processed_submission),
            )

        if not self.context.dry_run:
            output_verification = self.file_verification_service.verify_non_empty_stable(
                path=expected_output,
                stability_checks=self.settings.publish.stability_checks,
                stability_interval_seconds=self.settings.publish.stability_interval_seconds,
            )
            if not output_verification.succeeded:
                self.logger.error(
                    output_verification.message,
                    extra={
                        "run_id": self.context.run_id,
                        "provider": processed_submission.provider.key,
                        "file_name": processed_submission.file_name,
                        "status": "converter_output_verification_failed",
                        "error": output_verification.error_code,
                    },
                )
                return FileProcessingResult(
                    provider_key=processed_submission.provider.key,
                    file_name=processed_submission.file_name,
                    status="converter_output_verification_failed",
                    message=output_verification.message,
                    transaction_count=transaction_count,
                    transaction_count_message=transaction_count_message,
                    received_date=self._received_date_text(processed_submission),
                )

            if processed_submission.received_date is not None:
                update_result = self.x12_date_update_service.update_received_date(
                    path=expected_output,
                    received_date=processed_submission.received_date,
                    run_id=self.context.run_id,
                    provider_key=processed_submission.provider.key,
                    file_name=processed_submission.file_name,
                )
                if not update_result.succeeded:
                    self.logger.error(
                        update_result.message,
                        extra={
                            "run_id": self.context.run_id,
                            "provider": processed_submission.provider.key,
                            "file_name": processed_submission.file_name,
                            "status": "x12_received_date_update_failed",
                            "error": update_result.error_code,
                        },
                    )
                    return FileProcessingResult(
                        provider_key=processed_submission.provider.key,
                        file_name=processed_submission.file_name,
                        status="x12_received_date_update_failed",
                        message=update_result.message,
                        transaction_count=transaction_count,
                        transaction_count_message=transaction_count_message,
                        received_date=self._received_date_text(processed_submission),
                    )

                output_verification = self.file_verification_service.verify_non_empty_stable(
                    path=expected_output,
                    stability_checks=self.settings.publish.stability_checks,
                    stability_interval_seconds=self.settings.publish.stability_interval_seconds,
                )
                if not output_verification.succeeded:
                    return FileProcessingResult(
                        provider_key=processed_submission.provider.key,
                        file_name=processed_submission.file_name,
                        status="x12_received_date_verification_failed",
                        message=output_verification.message,
                        transaction_count=transaction_count,
                        transaction_count_message=transaction_count_message,
                        received_date=self._received_date_text(processed_submission),
                    )

        publish_result = self.publish_service.publish(
            source=expected_output,
            incoming_directory=self.settings.paths.incoming_directory,
            run_id=self.context.run_id,
            provider_key=processed_submission.provider.key,
            dry_run=self.context.dry_run,
        )
        if not self.context.dry_run and not publish_result.succeeded:
            return FileProcessingResult(
                provider_key=processed_submission.provider.key,
                file_name=processed_submission.file_name,
                status="publish_failed",
                message=publish_result.message,
                transaction_count=transaction_count,
                transaction_count_message=transaction_count_message,
                received_date=self._received_date_text(processed_submission),
            )

        if publish_result.destination is not None:
            observation = self.inbox_observer_service.observe(
                expected_file_name=publish_result.destination.name,
                inbox_directory=self.settings.paths.inbox_directory,
                run_id=self.context.run_id,
                provider_key=processed_submission.provider.key,
                dry_run=self.context.dry_run,
            )
            if (
                not self.context.dry_run
                and self.settings.publish.observe_inbox
                and not observation.succeeded
            ):
                return FileProcessingResult(
                    provider_key=processed_submission.provider.key,
                    file_name=processed_submission.file_name,
                    status=f"inbox_observation_{observation.status}",
                    message=observation.message,
                    transaction_count=transaction_count,
                    transaction_count_message=transaction_count_message,
                    received_date=self._received_date_text(processed_submission),
                )

        archive_plan = self.archive_service.plan(original_submission, datetime.now())
        self.archive_service.execute(
            plan=archive_plan,
            run_id=self.context.run_id,
            dry_run=self.context.dry_run,
        )
        return FileProcessingResult(
            provider_key=processed_submission.provider.key,
            file_name=processed_submission.file_name,
            status="completed" if not self.context.dry_run else "planned",
            transaction_count=transaction_count,
            transaction_count_message=transaction_count_message,
            received_date=self._received_date_text(processed_submission),
        )

    def _expected_converter_output(self, submission: FileSubmission) -> Path:
        if submission.provider.converter == "rxFlatfileTo837P":
            return self.settings.paths.x12_files_directory / f"{submission.file_name}.x12"

        if submission.provider.converter == "convert837ITo837P":
            return self.settings.paths.converted_837i_directory / (
                f"{submission.file_name}_PLEXISCONVERSION.837p.x12"
            )

        return self.settings.paths.x12_files_directory / submission.file_name

    def _exit_code(self, results: list[FileProcessingResult]) -> int:
        if self.context.dry_run:
            return 0

        failure_statuses = set(self.settings.runtime.fail_on_file_statuses)
        for result in results:
            if result.status in failure_statuses:
                return 2
        return 0

    def _transaction_count(self, submission: FileSubmission) -> tuple[int | None, str | None]:
        result = self.transaction_count_service.count(submission)
        if result.succeeded:
            self.logger.info(
                f"Transaction count for {submission.file_name}: {result.count}",
                extra={
                    "run_id": self.context.run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "transaction_counted",
                    "transaction_count": result.count,
                },
            )
            count_message = result.method
            if result.message:
                count_message = f"{result.method}: {result.message}"
            return result.count, count_message

        self.logger.warning(
            result.message,
            extra={
                "run_id": self.context.run_id,
                "provider": submission.provider.key,
                "file_name": submission.file_name,
                "status": "transaction_count_failed",
            },
        )
        return None, result.message

    def _handle_validation_failure(
        self,
        submission: FileSubmission,
        validation_result: ValidationResult,
        transaction_count: int | None,
        transaction_count_message: str | None,
        status: str,
    ) -> FileProcessingResult:
        report_paths = self.validation_report_service.write_reports(
            submission=submission,
            result=validation_result,
            run_id=self.context.run_id,
        )
        notification = self.provider_notification_service.render_validation_failed(
            submission=submission,
            validation_result=validation_result,
            run_id=self.context.run_id,
        )
        for issue in validation_result.issues:
            self.logger.error(
                issue.message,
                extra={
                    "run_id": self.context.run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": status,
                    "error": issue.error_code,
                },
            )
        self.logger.info(
            f"Validation reports ready: {report_paths[0]}, {report_paths[1]}",
            extra={
                "run_id": self.context.run_id,
                "provider": submission.provider.key,
                "file_name": submission.file_name,
                "status": "validation_reports_ready",
            },
        )
        self.logger.info(
            f"Provider notification rendered: {notification.text_path}, {notification.html_path}",
            extra={
                "run_id": self.context.run_id,
                "provider": submission.provider.key,
                "file_name": submission.file_name,
                "status": "provider_notification_ready",
            },
        )
        if notification.send_enabled:
            text_body, html_body = self.provider_notification_service.read_rendered_bodies(
                notification
            )
            self.email_service.send(
                subject=notification.subject,
                recipients=notification.recipients,
                text_body=text_body,
                html_body=html_body,
                attachments=(*report_paths, notification.text_path, notification.html_path),
                run_id=self.context.run_id,
                allow_email=self.context.allow_email,
            )
        return FileProcessingResult(
            provider_key=submission.provider.key,
            file_name=submission.file_name,
            status=status,
            transaction_count=transaction_count,
            transaction_count_message=transaction_count_message,
            received_date=self._received_date_text(submission),
        )

    def _received_date_text(self, submission: FileSubmission) -> str | None:
        if submission.received_date is None:
            return None
        return submission.received_date.isoformat()

    def _send_transaction_report(self, report_paths: tuple[Path, Path]) -> None:
        report_settings = self.settings.transaction_reports
        if not report_settings.send_email:
            return

        self.email_service.send(
            subject=f"{report_settings.subject_prefix}: {self.context.run_id}",
            recipients=report_settings.recipients,
            text_body="Attached is the EDI transaction count report for this run.",
            html_body=None,
            attachments=report_paths,
            run_id=self.context.run_id,
            allow_email=self.context.allow_email,
        )

    def _expected_result_logs(self, converter_key: str) -> tuple[Path, ...]:
        result_file_names = {
            "rxFlatfileTo837P": "837P_Results.txt",
            "convert837ITo837P": "837I_Results.txt",
        }
        result_file_name = result_file_names.get(converter_key)
        if result_file_name is None:
            return ()
        return (self.settings.paths.qds_processor_root / result_file_name,)
