from __future__ import annotations

import json
from pathlib import Path

import paramiko
import pytest

from fgops.agent_config import (
    AgentConfig,
    DeviceConfig,
    ExecutionConfig,
    SourceConfig,
    StorageConfig,
)
from fgops.fortigate_preflight import (
    HostKeyInfo,
    PinnedFingerprintPolicy,
    READ_ONLY_COMMANDS,
    openssh_sha256,
    parse_autoupdate_versions,
    parse_system_status,
    run_read_only_preflight,
    validate_observed,
)

SYSTEM_STATUS = """SITEC-FW-02 (global) # get system status
Version: FortiGate-300D v6.4.16,build2098,250326 (GA.M)
Serial-Number: FGT3HD3917802415
Hostname: SITEC-FW-02
Operation Mode: NAT
Current virtual domain: Management
Virtual domain configuration: multiple
Current HA mode: standalone
SITEC-FW-02 (global) #
"""

AUTOUPDATE = """SITEC-FW-02 (global) # diagnose autoupdate versions
Virus Definitions
---------
Version: 93.07607
Last Updated using manual update on Sun Jul 26 11:00:00 2026
Result: Connectivity failure

Attack Definitions
---------
Version: 36.00260
Last Updated using manual update on Sun Jul 26 11:01:00 2026
Result: Connectivity failure
SITEC-FW-02 (global) #
"""


def test_openssh_fingerprint_policy_accepts_only_exact_key() -> None:
    key = paramiko.RSAKey.generate(1024)
    expected = openssh_sha256(key)
    policy = PinnedFingerprintPolicy(expected)
    policy.missing_host_key(paramiko.SSHClient(), "172.16.1.2", key)

    other = paramiko.RSAKey.generate(1024)
    with pytest.raises(paramiko.SSHException, match="host-key mismatch"):
        policy.missing_host_key(paramiko.SSHClient(), "172.16.1.2", other)


def test_parses_and_validates_expected_fortigate() -> None:
    status = parse_system_status(SYSTEM_STATUS)
    assert status.hostname == "SITEC-FW-02"
    assert status.model == "FortiGate-300D"
    assert status.firmware_version == "6.4.16"
    assert status.build == 2098

    device = DeviceConfig(
        host="172.16.1.2",
        username="fgops-readonly",
        host_key_sha256="SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        expected_hostname="SITEC-FW-02",
        expected_model="FortiGate-300D",
        expected_firmware_branch="6.4",
        expected_build=2098,
    )
    assert validate_observed(device, status) == []


def test_parses_autoupdate_sections() -> None:
    versions = parse_autoupdate_versions(AUTOUPDATE)
    assert versions["Virus Definitions"]["Version"] == "93.07607"
    assert versions["Attack Definitions"]["Version"] == "36.00260"


class _FakeSession:
    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.host_key = HostKeyInfo(
            host=config.host,
            port=config.port,
            key_type="ssh-ed25519",
            bits=256,
            sha256=config.host_key_sha256,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run_command(self, command: str) -> str:
        assert command in READ_ONLY_COMMANDS
        if command == "get system status":
            return SYSTEM_STATUS
        if command == "diagnose autoupdate versions":
            return AUTOUPDATE
        return f"SITEC-FW-02 (global) # {command}\nOK\nSITEC-FW-02 (global) #\n"


def test_preflight_writes_pass_evidence(tmp_path: Path) -> None:
    package_map = tmp_path / "package-map.yml"
    package_map.write_text("packages: []\n", encoding="utf-8")
    root = tmp_path / "runtime"
    config = AgentConfig(
        config_path=tmp_path / "config.yml",
        package_map=package_map,
        source=SourceConfig(
            page_url="https://example.test/",
            link_text_regex="Fortigate V6.4",
        ),
        storage=StorageConfig(
            root=root,
            incoming=root / "incoming",
            quarantine=root / "quarantine",
            reports=root / "reports",
            state_file=root / "state.json",
        ),
        execution=ExecutionConfig(),
        device=DeviceConfig(
            host="172.16.1.2",
            username="fgops-readonly",
            host_key_sha256="SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            expected_hostname="SITEC-FW-02",
            expected_model="FortiGate-300D",
            expected_firmware_branch="6.4",
            expected_build=2098,
        ),
    )

    result = run_read_only_preflight(config, session_factory=_FakeSession)
    assert result.status == "PASS"
    evidence = json.loads(Path(result.evidence_json).read_text(encoding="utf-8"))
    assert evidence["device_changes_performed"] is False
    assert evidence["system_status"]["build"] == 2098
    assert Path(result.evidence_text).is_file()
