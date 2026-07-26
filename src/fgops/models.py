from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class PackageKind(StrEnum):
    AV = "AV"
    IPS = "IPS"
    APDB = "APDB"
    FFDB = "FFDB"
    MCDB = "MCDB"
    MMDB = "MMDB"
    ISDB = "ISDB"
    BOTNET = "BOTNET"
    UNKNOWN = "UNKNOWN"


class RestoreFamily(StrEnum):
    AV = "av"
    IPS = "ips"
    OTHER_OBJECTS = "other-objects"


class UpdateStatus(StrEnum):
    SUCCESS = "SUCCESS"
    SUCCESS_WITH_WARNING = "SUCCESS_WITH_WARNING"
    SKIPPED_NO_UPDATE = "SKIPPED_NO_UPDATE"
    FAILED_UNCONFIRMED = "FAILED_UNCONFIRMED"
    FAILED = "FAILED"


class ApprovalState(StrEnum):
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SNOOZED = "SNOOZED"
    SCHEDULED = "SCHEDULED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class PackageRecord:
    filename: str
    size: int
    sha256: str
    kind: PackageKind
    restore_family: RestoreFamily | None
    expected_objects: tuple[str, ...] = ()
    safe_for_deferred_apply: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["restore_family"] = self.restore_family.value if self.restore_family else None
        data["expected_objects"] = list(self.expected_objects)
        return data


@dataclass(frozen=True)
class BundleManifest:
    schema_version: int
    manifest_id: str
    source_archive: str
    source_archive_sha256: str
    generated_at: str
    packages: tuple[PackageRecord, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "source_archive": self.source_archive,
            "source_archive_sha256": self.source_archive_sha256,
            "generated_at": self.generated_at,
            "packages": [package.to_dict() for package in self.packages],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class DefinitionVersion:
    name: str
    version: str
    last_updated: str | None = None
    result: str | None = None


@dataclass(frozen=True)
class PackageOutcome:
    status: UpdateStatus
    object_name: str
    before_version: str | None
    after_version: str | None
    reason: str
    return_code: int | None = None


@dataclass(frozen=True)
class ApprovalDecision:
    state: ApprovalState
    approval_required: bool
    eligible_packages: tuple[PackageKind, ...] = field(default_factory=tuple)
    execute_at: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "approval_required": self.approval_required,
            "eligible_packages": [item.value for item in self.eligible_packages],
            "execute_at": self.execute_at,
            "reason": self.reason,
        }
