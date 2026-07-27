from fgops.entrypoint import install_prompt_guard
from fgops.fortigate_preflight import _last_prompt


def test_tftp_progress_hashes_are_not_cli_prompts() -> None:
    install_prompt_guard()

    assert _last_prompt("Connect to tftp server 192.168.1.34 ...\n##\n") is None
    assert _last_prompt("Connect to tftp server 192.168.1.34 ...\n###########\n") is None


def test_real_fortigate_prompt_is_still_detected() -> None:
    install_prompt_guard()

    assert _last_prompt("SITEC-FW-02 (global) #\n") == "SITEC-FW-02 (global) #"
