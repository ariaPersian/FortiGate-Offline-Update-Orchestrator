from __future__ import annotations

import os
import re
import time
from dataclasses import replace
from typing import Callable

from . import controlled_apply, fortigate_preflight
from .models import UpdateStatus

# FortiGate prints TFTP transfer progress as lines made only of '#'.  The
# historical prompt matcher accepted those progress bars as CLI prompts, which
# caused the orchestrator to send the post-restore command before the transfer
# had completed and then close the SSH session.  A real prompt must contain at
# least one non-prompt character before its trailing '#' or '$'.
_PROMPT_RE = re.compile(r"(?m)^(?![#$]+\s*$)([^\r\n]{1,240}[#$])\s*$")

# FortiOS can successfully receive a signed package that contains the same
# database revision already installed on the appliance.  In that case the
# transfer completes with an explicit OK line, while diagnose autoupdate
# versions remains unchanged.  This is a safe no-op, not an unconfirmed failure.
_SUCCESSFUL_TRANSFER_RE = re.compile(
    r"(?im)^Get (?:antivirus database|IPS database|other objects) "
    r"from (?:tftp|ftp) server OK\.\s*$"
)
_BLOCKING_OUTPUT_RE = re.compile(
    r"(?i)(command fail|invalid signature|signature invalid|wrong firmware version|downgrade)"
)
_FFDB_OBJECTS = (
    "Internet-service Database Apps",
    "Internet-service Full Database Maps",
)
_FFDB_RETURN_CODE = 49
_DEFAULT_FFDB_MAX_WAIT_SECONDS = 30 * 60
_DEFAULT_FFDB_POLL_SECONDS = 30


def _classify_with_successful_no_change(**kwargs):
    result = _ORIGINAL_CLASSIFIER(**kwargs)
    if result.status is not UpdateStatus.FAILED_UNCONFIRMED:
        return result

    output = str(kwargs.get("command_output", ""))
    if not _SUCCESSFUL_TRANSFER_RE.search(output):
        return result
    if result.return_code not in {None, 0} or _BLOCKING_OUTPUT_RE.search(output):
        return result
    if not result.objects:
        return result
    if any(
        item.before_version is None
        or item.after_version is None
        or item.before_version != item.after_version
        for item in result.objects
    ):
        return result

    return replace(
        result,
        status=UpdateStatus.SKIPPED_NO_UPDATE,
        reason=(
            "FortiGate completed the package transfer successfully; "
            "the expected object versions were already current."
        ),
    )


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _read_versions(session) -> dict[str, dict[str, str]]:
    command = "diagnose autoupdate versions"
    raw = session.run_command(command)
    body = fortigate_preflight._strip_command_envelope(raw, command)
    return fortigate_preflight.parse_autoupdate_versions(body)


def _object_versions(versions: dict[str, dict[str, str]]) -> tuple[str | None, ...]:
    return tuple((versions.get(name) or {}).get("Version") for name in _FFDB_OBJECTS)


def _wait_for_ffdb_version_change(
    session,
    *,
    before: tuple[str | None, ...],
    max_wait_seconds: int,
    poll_seconds: int,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[bool, int, tuple[str | None, ...]]:
    """Poll FFDB versions after return code 49 without submitting another package.

    FortiOS can return code 49 while the Internet Service Database is still being
    parsed.  Submitting another FFDB package during that window can trigger another
    validation failure, so this function only reads versions until they change or
    the bounded wait expires.
    """

    elapsed = 0
    latest = before
    while elapsed < max_wait_seconds:
        delay = min(poll_seconds, max_wait_seconds - elapsed)
        sleep_fn(delay)
        elapsed += delay
        latest = _object_versions(_read_versions(session))
        if all(value is not None for value in latest) and latest != before:
            return True, elapsed, latest
    return False, elapsed, latest


def _run_restore_with_ffdb_poll(self, *, family: str, filename: str, tftp_address: str) -> str:
    is_ffdb = family == "other-objects" and "ffdb" in filename.lower()
    before = _object_versions(_read_versions(self)) if is_ffdb else ()
    output = _ORIGINAL_RUN_RESTORE(
        self,
        family=family,
        filename=filename,
        tftp_address=tftp_address,
    )
    if not is_ffdb or controlled_apply._return_code(output) != _FFDB_RETURN_CODE:
        return output

    max_wait = _positive_int_from_env(
        "FGOPS_FFDB_MAX_WAIT_SECONDS",
        _DEFAULT_FFDB_MAX_WAIT_SECONDS,
    )
    poll_seconds = _positive_int_from_env(
        "FGOPS_FFDB_POLL_SECONDS",
        _DEFAULT_FFDB_POLL_SECONDS,
    )
    changed, elapsed, latest = _wait_for_ffdb_version_change(
        self,
        before=before,
        max_wait_seconds=max_wait,
        poll_seconds=poll_seconds,
    )
    state = "changed" if changed else "unchanged"
    return (
        output.rstrip()
        + "\n"
        + (
            "[FGOps] FFDB return code 49 observed; version polling completed "
            f"after {elapsed}s with state={state}, before={before}, after={latest}."
        )
        + "\n"
    )


_ORIGINAL_CLASSIFIER = controlled_apply.classify_package_result
if not hasattr(controlled_apply.FortiGateApplySession, "_fgops_original_run_restore"):
    controlled_apply.FortiGateApplySession._fgops_original_run_restore = (
        controlled_apply.FortiGateApplySession.run_restore
    )
_ORIGINAL_RUN_RESTORE = controlled_apply.FortiGateApplySession._fgops_original_run_restore


def install_prompt_guard() -> None:
    """Install only the CLI prompt guard; retained as a stable public test hook."""
    fortigate_preflight._PROMPT_RE = _PROMPT_RE


def install_runtime_guards() -> None:
    install_prompt_guard()
    controlled_apply.classify_package_result = _classify_with_successful_no_change
    controlled_apply.FortiGateApplySession.run_restore = _run_restore_with_ffdb_poll


install_runtime_guards()


def main() -> int:
    from .agent_cli import main as agent_main

    result = agent_main()
    return int(result) if isinstance(result, int) else 0
