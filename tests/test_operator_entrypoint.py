from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fgops.operator_entrypoint import _record_result
from fgops.operator_logging import (
    OperatorChecklist,
    close_operator_logging,
    configure_operator_logging,
    default_operator_steps,
)


def _checklist(tmp_path, command: str) -> tuple[OperatorChecklist, object]:
    now = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    logger = configure_operator_logging(
        tmp_path,
        logger_name=f"fgops.test.operator.result.{command}",
        clock=lambda: now,
    )
    checklist = OperatorChecklist(
        logger,
        command=command,
        steps=default_operator_steps(command),
        run_id=f"test-{command}",
    )
    checklist.start()
    checklist.success("startup")
    checklist.success("config")
    checklist.success("storage")
    return checklist, logger


def test_cycle_no_change_completes_every_planned_operator_step(tmp_path):
    checklist, logger = _checklist(tmp_path, "cycle")
    config = SimpleNamespace(
        execution=SimpleNamespace(mode="approval"),
        apply=SimpleNamespace(require_backup=True),
    )
    payload = {
        "status": "NO_CHANGE",
        "monitor": {
            "status": "NO_CHANGE",
            "source_page": "https://example.invalid/source",
            "download_url": "https://example.invalid/bundle.zip",
            "archive_sha256": "a" * 64,
            "message": "The archive hash was already prepared successfully.",
        },
        "apply": None,
        "notifications": [],
    }

    status, operator_action = _record_result(
        checklist,
        command="cycle",
        payload=payload,
        exit_code=0,
        config=config,
    )
    close_operator_logging(logger)

    assert status == "NO_CHANGE"
    assert operator_action == "اقدامی لازم نیست؛ بسته جدیدی شناسایی نشده است."
    assert all(step.state not in {"TODO", "RUNNING"} for step in checklist.steps)
    assert next(step for step in checklist.steps if step.key == "report").state == "SUCCESS"
    assert next(step for step in checklist.steps if step.key == "backup").state == "SKIPPED"


def test_apply_result_adds_one_operator_row_per_package(tmp_path):
    checklist, logger = _checklist(tmp_path, "apply")
    config = SimpleNamespace(
        execution=SimpleNamespace(mode="approval"),
        apply=SimpleNamespace(require_backup=True),
    )
    payload = {
        "status": "SUCCESS_WITH_WARNING",
        "manifest_id": "FGOPS-0123456789ABCDEF",
        "archive_sha256": "b" * 64,
        "backup_path": "C:/ProgramData/FGOps/evidence/backups/device-full.conf",
        "report_json": "C:/ProgramData/FGOps/reports/apply.json",
        "report_text": "C:/ProgramData/FGOps/reports/apply.txt",
        "package_results": [
            {
                "kind": "AV",
                "filename": "avdb.pkg",
                "status": "SUCCESS",
                "reason": "Expected object version increased.",
            },
            {
                "kind": "MMDB",
                "filename": "mmdb.pkg",
                "status": "SKIPPED_NO_UPDATE",
                "reason": "The installed database was already current.",
            },
        ],
    }

    status, operator_action = _record_result(
        checklist,
        command="apply",
        payload=payload,
        exit_code=0,
        config=config,
    )
    close_operator_logging(logger)

    package_steps = [step for step in checklist.steps if step.key.startswith("package:")]
    assert status == "SUCCESS_WITH_WARNING"
    assert operator_action is None
    assert len(package_steps) == 2
    assert package_steps[0].state == "SUCCESS"
    assert package_steps[1].state == "WARNING"
    assert next(step for step in checklist.steps if step.key == "packages").state == "WARNING"
    assert next(step for step in checklist.steps if step.key == "verification").state == "WARNING"
