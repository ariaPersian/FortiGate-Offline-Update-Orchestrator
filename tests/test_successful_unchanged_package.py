from __future__ import annotations

from fgops import controlled_apply
from fgops import entrypoint  # noqa: F401 - installs runtime guards
from fgops.models import UpdateStatus


def _versions(value: str) -> dict[str, dict[str, str]]:
    return {
        "Attack Definitions": {"Version": value},
        "Attack Extended Definitions": {"Version": value},
    }


def test_successful_transfer_with_unchanged_versions_is_no_update() -> None:
    result = controlled_apply.classify_package_result(
        kind="IPS",
        filename="ips.pkg",
        expected_objects=("Attack Definitions", "Attack Extended Definitions"),
        before=_versions("36.00260"),
        after=_versions("36.00260"),
        command_output=(
            "Connect to tftp server 192.0.2.10 ...\n"
            "###########\n"
            "Get IPS database from tftp server OK.\n"
        ),
        prevent_downgrade=True,
    )

    assert result.status is UpdateStatus.SKIPPED_NO_UPDATE
    assert "already current" in result.reason


def test_unchanged_versions_without_success_marker_remain_unconfirmed() -> None:
    result = controlled_apply.classify_package_result(
        kind="IPS",
        filename="ips.pkg",
        expected_objects=("Attack Definitions", "Attack Extended Definitions"),
        before=_versions("36.00260"),
        after=_versions("36.00260"),
        command_output="Connect to tftp server 192.0.2.10 ...\n###########\n",
        prevent_downgrade=True,
    )

    assert result.status is UpdateStatus.FAILED_UNCONFIRMED


def test_success_marker_does_not_override_command_failure() -> None:
    result = controlled_apply.classify_package_result(
        kind="IPS",
        filename="ips.pkg",
        expected_objects=("Attack Definitions", "Attack Extended Definitions"),
        before=_versions("36.00260"),
        after=_versions("36.00260"),
        command_output=(
            "Get IPS database from tftp server OK.\n"
            "Command fail. Return code 49\n"
        ),
        prevent_downgrade=True,
    )

    assert result.status is UpdateStatus.FAILED_UNCONFIRMED
