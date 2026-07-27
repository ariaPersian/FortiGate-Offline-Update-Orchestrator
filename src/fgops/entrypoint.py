from __future__ import annotations

import re
from dataclasses import replace

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


_ORIGINAL_CLASSIFIER = controlled_apply.classify_package_result


def install_runtime_guards() -> None:
    fortigate_preflight._PROMPT_RE = _PROMPT_RE
    controlled_apply.classify_package_result = _classify_with_successful_no_change


install_runtime_guards()


def main() -> int:
    from .agent_cli import main as agent_main

    result = agent_main()
    return int(result) if isinstance(result, int) else 0
