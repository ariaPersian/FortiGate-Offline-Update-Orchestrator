from __future__ import annotations

from fgops import entrypoint


def _versions(apps: str, maps: str) -> str:
    return f"""diagnose autoupdate versions
Internet-service Database Apps
---------
Version: {apps}

Internet-service Full Database Maps
---------
Version: {maps}

SITEC-FW-02 (global) #
"""


class FakeSession:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = iter(outputs)
        self.read_count = 0

    def run_command(self, command: str) -> str:
        assert command == "diagnose autoupdate versions"
        self.read_count += 1
        return next(self.outputs)


def test_ffdb_poll_waits_until_versions_change() -> None:
    session = FakeSession(
        [
            _versions("7.04473", "7.04473"),
            _versions("7.04474", "7.04474"),
        ]
    )

    changed, elapsed, latest = entrypoint._wait_for_ffdb_version_change(
        session,
        before=("7.04473", "7.04473"),
        max_wait_seconds=60,
        poll_seconds=30,
        sleep_fn=lambda _seconds: None,
    )

    assert changed is True
    assert elapsed == 60
    assert latest == ("7.04474", "7.04474")
    assert session.read_count == 2


def test_ffdb_restore_return_49_polls_before_returning(monkeypatch) -> None:
    session = FakeSession(
        [
            _versions("7.04473", "7.04473"),  # before restore
            _versions("7.04473", "7.04473"),  # first poll
            _versions("7.04474", "7.04474"),  # second poll
        ]
    )

    def fake_restore(_self, *, family: str, filename: str, tftp_address: str) -> str:
        assert family == "other-objects"
        assert filename == "cyberlogic.ir-ffdb.pkg"
        assert tftp_address == "192.168.1.34"
        return (
            "Get other objects from tftp server OK.\n"
            "Command fail. Return code 49\n"
        )

    monkeypatch.setattr(entrypoint, "_ORIGINAL_RUN_RESTORE", fake_restore)
    monkeypatch.setenv("FGOPS_FFDB_MAX_WAIT_SECONDS", "2")
    monkeypatch.setenv("FGOPS_FFDB_POLL_SECONDS", "1")
    monkeypatch.setattr(entrypoint.time, "sleep", lambda _seconds: None)

    output = entrypoint._run_restore_with_ffdb_poll(
        session,
        family="other-objects",
        filename="cyberlogic.ir-ffdb.pkg",
        tftp_address="192.168.1.34",
    )

    assert "return code 49" in output.lower()
    assert "state=changed" in output
    assert "after=('7.04474', '7.04474')" in output
    assert session.read_count == 3


def test_non_ffdb_restore_does_not_poll(monkeypatch) -> None:
    session = FakeSession([])

    def fake_restore(_self, *, family: str, filename: str, tftp_address: str) -> str:
        return "Get other objects from tftp server OK.\n"

    monkeypatch.setattr(entrypoint, "_ORIGINAL_RUN_RESTORE", fake_restore)

    output = entrypoint._run_restore_with_ffdb_poll(
        session,
        family="other-objects",
        filename="cyberlogic.ir-apdb.pkg",
        tftp_address="192.168.1.34",
    )

    assert "Get other objects" in output
    assert session.read_count == 0
