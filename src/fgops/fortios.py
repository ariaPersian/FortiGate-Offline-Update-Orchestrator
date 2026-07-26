from __future__ import annotations

import ipaddress
import re
from pathlib import Path

from .models import DefinitionVersion, PackageKind, PackageOutcome, RestoreFamily, UpdateStatus

_SECTION_RE = re.compile(
    r"(?ms)^(?P<name>[^\r\n]+)\r?\n-+\r?\n(?P<body>.*?)(?=^[^\r\n]+\r?\n-+\r?\n|\Z)"
)
_RETURN_CODE_RE = re.compile(r"Return code\s+(-?\d+)")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

RESTORE_FAMILY_BY_KIND = {
    PackageKind.AV: RestoreFamily.AV,
    PackageKind.MMDB: RestoreFamily.AV,
    PackageKind.IPS: RestoreFamily.IPS,
    PackageKind.APDB: RestoreFamily.IPS,
    PackageKind.FFDB: RestoreFamily.OTHER_OBJECTS,
    PackageKind.MCDB: RestoreFamily.OTHER_OBJECTS,
    PackageKind.ISDB: RestoreFamily.OTHER_OBJECTS,
    PackageKind.BOTNET: RestoreFamily.OTHER_OBJECTS,
}


def parse_autoupdate_versions(text: str) -> dict[str, DefinitionVersion]:
    result: dict[str, DefinitionVersion] = {}
    for match in _SECTION_RE.finditer(text.replace("\x1b", "")):
        name = match.group("name").strip()
        body = match.group("body")
        version = _field(body, "Version")
        if not version:
            continue
        result[name] = DefinitionVersion(
            name=name,
            version=version,
            last_updated=_field(body, "Last Updated using manual update"),
            result=_field(body, "Result"),
        )
    return result


def _field(body: str, label: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(label)}:\s*(.*?)\s*$", body)
    return match.group(1).strip() if match else None


def version_key(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version)
    return tuple(int(item) for item in numbers) if numbers else (0,)


def render_restore_command(kind: PackageKind, filename: str, tftp_server: str) -> str:
    if not _SAFE_FILENAME_RE.fullmatch(filename):
        raise ValueError("Package filename contains unsupported characters.")
    ipaddress.ip_address(tftp_server)
    family = RESTORE_FAMILY_BY_KIND.get(kind)
    if family is None:
        raise ValueError(f"No restore command is defined for {kind.value}.")
    return f"execute restore {family.value} tftp {filename} {tftp_server}"


def classify_outcome(
    object_name: str,
    before: DefinitionVersion | None,
    after: DefinitionVersion | None,
    transcript: str,
) -> PackageOutcome:
    return_code_match = _RETURN_CODE_RE.search(transcript)
    return_code = int(return_code_match.group(1)) if return_code_match else None
    before_version = before.version if before else None
    after_version = after.version if after else None
    increased = bool(
        before_version
        and after_version
        and version_key(after_version) > version_key(before_version)
    )

    if increased and return_code is not None:
        return PackageOutcome(
            UpdateStatus.SUCCESS_WITH_WARNING,
            object_name,
            before_version,
            after_version,
            "The object version increased even though FortiOS returned a non-zero code.",
            return_code,
        )
    if increased:
        return PackageOutcome(
            UpdateStatus.SUCCESS,
            object_name,
            before_version,
            after_version,
            "The object version increased.",
            return_code,
        )
    if "No updates" in transcript and before_version == after_version:
        return PackageOutcome(
            UpdateStatus.SKIPPED_NO_UPDATE,
            object_name,
            before_version,
            after_version,
            "FortiOS accepted the transfer but reported no applicable update.",
            return_code,
        )
    if "Get " in transcript and " from tftp server OK" in transcript:
        return PackageOutcome(
            UpdateStatus.FAILED_UNCONFIRMED,
            object_name,
            before_version,
            after_version,
            "TFTP succeeded, but the expected object version did not increase.",
            return_code,
        )
    return PackageOutcome(
        UpdateStatus.FAILED,
        object_name,
        before_version,
        after_version,
        "The transfer or installation could not be confirmed.",
        return_code,
    )


def parse_versions_file(path: Path) -> dict[str, DefinitionVersion]:
    return parse_autoupdate_versions(path.read_text(encoding="utf-8", errors="replace"))
