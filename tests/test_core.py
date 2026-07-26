from datetime import datetime, timedelta, timezone
from pathlib import Path
import zipfile

import pytest

from fgops.approval import ApprovalPolicy, evaluate_policy, parse_approval_command
from fgops.fortios import classify_outcome, parse_autoupdate_versions, render_restore_command
from fgops.inventory import build_manifest, safe_extract_packages
from fgops.models import (
    ApprovalState,
    BundleManifest,
    PackageKind,
    PackageRecord,
    RestoreFamily,
    UpdateStatus,
)


BEFORE = """Virus Definitions
---------
Version: 93.06139
Last Updated using manual update on Tue Oct  7 22:22:00 2025
Result: Connectivity failure

Internet-service Database Apps
---------
Version: 7.04348
Last Updated using manual update on Wed Oct  8 00:51:00 2025
Result: Connectivity failure
"""

AFTER = """Virus Definitions
---------
Version: 93.07607
Last Updated using manual update on Sun Jul 26 08:53:56 2026
Result: Connectivity failure

Internet-service Database Apps
---------
Version: 7.04473
Last Updated using manual update on Sun Jul 26 08:57:34 2026
Result: Connectivity failure
"""


def _manifest() -> BundleManifest:
    return BundleManifest(
        schema_version=1,
        manifest_id="FGOPS-TEST",
        source_archive="bundle.zip",
        source_archive_sha256="a" * 64,
        generated_at="2026-07-26T00:00:00+00:00",
        packages=(
            PackageRecord(
                "cyberlogic.ir-AV.pkg",
                1,
                "b" * 64,
                PackageKind.AV,
                RestoreFamily.AV,
                ("Virus Definitions",),
                True,
            ),
            PackageRecord(
                "cyberlogic.ir-isdb.pkg",
                1,
                "c" * 64,
                PackageKind.ISDB,
                RestoreFamily.OTHER_OBJECTS,
                ("Industrial Attack Definitions",),
                False,
            ),
        ),
    )


def test_commands_are_strict() -> None:
    assert parse_approval_command("/fg approve").command == "approve"
    assert parse_approval_command("/fg snooze 24h").argument == "24h"
    with pytest.raises(ValueError):
        parse_approval_command("/fg reject")


def test_grace_period_only_approves_safe_packages() -> None:
    policy = ApprovalPolicy(
        mode="grace_period",
        timezone_name="UTC",
        reminders=(),
        repeat_every=None,
        timeout=timedelta(days=7),
        on_timeout="apply_safe_only",
        grace_period=timedelta(hours=24),
        safe_package_kinds=(PackageKind.AV, PackageKind.ISDB),
    )
    created = datetime(2026, 7, 25, tzinfo=timezone.utc)
    decision = evaluate_policy(_manifest(), policy, created, created + timedelta(hours=25))
    assert decision.state == ApprovalState.APPROVED
    assert decision.eligible_packages == (PackageKind.AV,)


def test_parse_versions_and_classify_observed_return_code() -> None:
    before = parse_autoupdate_versions(BEFORE)
    after = parse_autoupdate_versions(AFTER)
    outcome = classify_outcome(
        "Internet-service Database Apps",
        before["Internet-service Database Apps"],
        after["Internet-service Database Apps"],
        "Get other objects from tftp server OK.\nCommand fail. Return code 49",
    )
    assert outcome.status == UpdateStatus.SUCCESS_WITH_WARNING
    assert outcome.return_code == 49


def test_no_update_is_not_generic_failure() -> None:
    parsed = parse_autoupdate_versions(BEFORE)
    outcome = classify_outcome(
        "Virus Definitions",
        parsed["Virus Definitions"],
        parsed["Virus Definitions"],
        "Get other objects from tftp server OK.\nNo updates\nReturn code -85",
    )
    assert outcome.status == UpdateStatus.SKIPPED_NO_UPDATE


def test_restore_command_validation() -> None:
    assert (
        render_restore_command(PackageKind.AV, "cyberlogic.ir-AV.pkg", "192.168.1.179")
        == "execute restore av tftp cyberlogic.ir-AV.pkg 192.168.1.179"
    )


def test_inventory_builds_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("cyberlogic.ir-AV.pkg", b"av-data")
        bundle.writestr("cyberlogic.ir-ips.pkg", b"ips-data")
    package_map = Path(__file__).parents[1] / "config" / "fortios64-package-map.yml"
    manifest = build_manifest(archive, tmp_path / "out", package_map)
    assert {item.kind for item in manifest.packages} == {PackageKind.AV, PackageKind.IPS}
    assert (tmp_path / "out" / "manifest.json").exists()


def test_zip_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.pkg", b"no")
    with pytest.raises(ValueError, match="Unsafe archive path"):
        safe_extract_packages(archive, tmp_path / "out")
