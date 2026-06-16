from __future__ import annotations

import logging
import shutil
from pathlib import Path

from edi_processor.config import WorkCleanupSettings


class WorkCleanupService:
    run_scoped_folders = ("staged", "preprocessed", "x12_validation")

    def __init__(self, working_directory: Path, settings: WorkCleanupSettings) -> None:
        self.working_directory = working_directory
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def cleanup_run(
        self,
        run_id: str,
        date_folder: str,
        exit_code: int,
        dry_run: bool,
    ) -> None:
        if not self._should_cleanup(exit_code=exit_code, dry_run=dry_run):
            self.logger.info(
                "Work cleanup skipped by configuration",
                extra={"run_id": run_id, "status": "work_cleanup_skipped"},
            )
            return

        work_root = self.working_directory.resolve()
        deleted = 0
        for folder_name in self.run_scoped_folders:
            date_root = self.working_directory / folder_name / date_folder
            run_root = date_root / run_id
            if self._delete_directory(run_root, work_root, run_id):
                deleted += 1
            self._remove_empty_parents(date_root, work_root, run_id)

        self.logger.info(
            f"Cleaned {deleted} work directories for run {run_id}",
            extra={
                "run_id": run_id,
                "status": "work_cleanup_completed",
                "deleted_directories": deleted,
            },
        )

    def _should_cleanup(self, exit_code: int, dry_run: bool) -> bool:
        if not self.settings.enabled:
            return False
        if dry_run:
            return self.settings.delete_on_dry_run
        if exit_code == 0:
            return self.settings.delete_on_success
        return self.settings.delete_on_failure

    def _delete_directory(self, target: Path, work_root: Path, run_id: str) -> bool:
        if not target.exists():
            return False

        resolved_target = target.resolve()
        if not self._is_within(resolved_target, work_root):
            self.logger.error(
                f"Refusing to delete work path outside working directory: {target}",
                extra={"run_id": run_id, "status": "work_cleanup_refused"},
            )
            return False

        if not target.is_dir():
            self.logger.warning(
                f"Work cleanup target is not a directory: {target}",
                extra={"run_id": run_id, "status": "work_cleanup_target_not_directory"},
            )
            return False

        try:
            shutil.rmtree(target)
        except OSError as exc:
            self.logger.error(
                f"Could not delete work directory {target}: {exc}",
                extra={"run_id": run_id, "status": "work_cleanup_failed"},
            )
            return False

        self.logger.info(
            f"Deleted work directory: {target}",
            extra={"run_id": run_id, "status": "work_directory_deleted"},
        )
        return True

    def _remove_empty_parents(self, date_root: Path, work_root: Path, run_id: str) -> None:
        for target in (date_root, date_root.parent):
            if not target.exists() or not target.is_dir():
                continue

            resolved_target = target.resolve()
            if resolved_target == work_root or not self._is_within(resolved_target, work_root):
                continue

            try:
                target.rmdir()
            except OSError:
                continue

            self.logger.info(
                f"Removed empty work directory: {target}",
                extra={"run_id": run_id, "status": "empty_work_directory_deleted"},
            )

    def _is_within(self, path: Path, root: Path) -> bool:
        return path == root or root in path.parents
