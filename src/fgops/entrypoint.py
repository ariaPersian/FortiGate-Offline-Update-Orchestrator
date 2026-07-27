from __future__ import annotations

import re

from . import fortigate_preflight

# FortiGate prints TFTP transfer progress as lines made only of '#'.  The
# historical prompt matcher accepted those progress bars as CLI prompts, which
# caused the orchestrator to send the post-restore command before the transfer
# had completed and then close the SSH session.  A real prompt must contain at
# least one non-prompt character before its trailing '#' or '$'.
_PROMPT_RE = re.compile(r"(?m)^(?![#$]+\s*$)([^\r\n]{1,240}[#$])\s*$")


def install_prompt_guard() -> None:
    fortigate_preflight._PROMPT_RE = _PROMPT_RE


install_prompt_guard()


def main() -> int:
    from .agent_cli import main as agent_main

    result = agent_main()
    return int(result) if isinstance(result, int) else 0
