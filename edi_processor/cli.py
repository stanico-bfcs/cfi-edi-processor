from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from edi_processor.config import load_dotenv, load_settings
from edi_processor.logging_config import configure_logging
from edi_processor.runtime import create_run_context
from edi_processor.services.orchestrator import Orchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cfi-edi-processor")
    parser.add_argument("--config", default="appsettings.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-email", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--provider", action="append", default=[])
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    env_path = Path(args.env_file).expanduser().resolve()

    load_dotenv(env_path)
    settings = load_settings(config_path)
    context = create_run_context(
        dry_run=args.dry_run,
        allow_email=args.allow_email,
        allow_live=args.allow_live,
        provider_filter=tuple(args.provider),
    )
    log_path = configure_logging(settings.runtime.logs_directory, context.run_id)

    logger = logging.getLogger(__name__)
    logger.info(
        "CLI initialized",
        extra={"run_id": context.run_id, "status": "initialized"},
    )
    logger.info(
        f"Writing run log to {log_path}",
        extra={"run_id": context.run_id, "status": "logging_ready"},
    )

    try:
        return Orchestrator(settings=settings, context=context).run()
    except Exception:
        logger.exception(
            "Run failed",
            extra={"run_id": context.run_id, "status": "failed"},
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
