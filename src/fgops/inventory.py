from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .models import BundleManifest, PackageKind, PackageRecord, RestoreFamily


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_member(member: zipfile.ZipInfo) -> None:
    path = PurePosixPath(member.filename)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe archive path: {member.filename}")
    if member.is_dir():
        return
    unix_mode = member.external_attr >> 16
    if unix_mode & 0o170000 == 0o120000:
        raise ValueError(f"Symbolic links are not allowed: {member.filename}")


def safe_extract_packages(
    archive: Path,
    output_dir: Path,
    *,
    warnings: list[str] | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    claimed_targets: dict[str, tuple[str, Path]] = {}
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            _validate_member(member)
            if member.is_dir() or not member.filename.lower().endswith(".pkg"):
                continue
            target = output_dir / PurePosixPath(member.filename).name
            normalized_name = target.name.casefold()
            claimed = claimed_targets.get(normalized_name)
            if claimed is not None:
                first_member, first_target = claimed
                with bundle.open(member) as source:
                    member_hash = hashlib.file_digest(source, "sha256").hexdigest()
                target_hash = sha256_file(first_target)
                if member_hash != target_hash:
                    raise ValueError(
                        "Conflicting package files share the same flattened filename "
                        f"'{target.name}': '{first_member}' and '{member.filename}'."
                    )
                if warnings is not None:
                    warnings.append(
                        "Ignored an identical duplicate archive member after SHA-256 "
                        f"verification: {member.filename} -> {target.name}"
                    )
                continue

            claimed_targets[normalized_name] = (member.filename, target)
            if target.exists():
                with bundle.open(member) as source:
                    member_hash = hashlib.file_digest(source, "sha256").hexdigest()
                if member_hash != sha256_file(target):
                    raise ValueError(
                        f"Existing extracted package conflicts with archive member: {target.name}"
                    )
            else:
                with bundle.open(member) as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
            extracted.append(target)
    if not extracted:
        raise ValueError("No .pkg files were found in the archive.")
    return sorted(extracted, key=lambda item: item.name.lower())


def load_package_map(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mappings = raw.get("packages")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("Package map must contain a non-empty 'packages' list.")
    return mappings


def identify_package(filename: str, mappings: list[dict[str, Any]]) -> tuple[
    PackageKind,
    RestoreFamily | None,
    tuple[str, ...],
    bool,
]:
    matches = [entry for entry in mappings if re.search(entry["pattern"], filename, re.I)]
    if len(matches) > 1:
        raise ValueError(f"Package '{filename}' matches more than one package-map rule.")
    if not matches:
        return PackageKind.UNKNOWN, None, (), False
    entry = matches[0]
    kind = PackageKind(entry["kind"])
    restore_family = entry.get("restore_family")
    if kind != PackageKind.IGNORED and not restore_family:
        raise ValueError(f"Package-map rule for {kind.value} requires restore_family.")
    safe_for_deferred_apply = bool(entry.get("safe_for_deferred_apply", False))
    if kind == PackageKind.IGNORED and safe_for_deferred_apply:
        raise ValueError("IGNORED package-map rules cannot be safe for deferred apply.")
    return (
        kind,
        RestoreFamily(restore_family) if restore_family else None,
        tuple(entry.get("expected_objects", [])),
        safe_for_deferred_apply,
    )


def build_manifest(
    archive: Path,
    output_dir: Path,
    package_map: Path,
    *,
    required_unique_kinds: Iterable[str | PackageKind] | None = None,
) -> BundleManifest:
    archive = archive.resolve()
    extracted_dir = output_dir / "packages"
    warnings: list[str] = []
    packages = safe_extract_packages(archive, extracted_dir, warnings=warnings)
    mappings = load_package_map(package_map)

    records: list[PackageRecord] = []
    for package in packages:
        kind, restore_family, expected_objects, safe = identify_package(package.name, mappings)
        if kind == PackageKind.UNKNOWN:
            warnings.append(f"Unknown package type: {package.name}")
        elif kind == PackageKind.IGNORED:
            warnings.append(f"Package retained for audit but excluded by package map: {package.name}")
        records.append(
            PackageRecord(
                filename=package.name,
                size=package.stat().st_size,
                sha256=sha256_file(package),
                kind=kind,
                restore_family=restore_family,
                expected_objects=expected_objects,
                safe_for_deferred_apply=safe,
            )
        )

    by_kind: dict[PackageKind, list[PackageRecord]] = defaultdict(list)
    for record in records:
        if record.kind not in {PackageKind.UNKNOWN, PackageKind.IGNORED}:
            by_kind[record.kind].append(record)
    if required_unique_kinds is None:
        unique_kinds = set(by_kind)
    else:
        unique_kinds = {
            value if isinstance(value, PackageKind) else PackageKind(str(value).upper())
            for value in required_unique_kinds
        }
    for kind, matches in sorted(by_kind.items(), key=lambda item: item[0].value):
        if len(matches) < 2:
            continue
        details = ", ".join(f"{item.filename} ({item.sha256[:12]})" for item in matches)
        if kind in unique_kinds:
            raise ValueError(
                f"Enabled package kind {kind.value} is ambiguous; found {len(matches)} "
                f"candidates: {details}. No package was selected."
            )
        warnings.append(
            f"Multiple packages were identified as disabled kind {kind.value} and retained "
            f"for audit only: {details}"
        )

    archive_hash = sha256_file(archive)
    identity_material = "\n".join(
        [archive_hash, *[f"{item.filename}:{item.sha256}:{item.kind.value}" for item in records]]
    )
    manifest_id = "FGOPS-" + hashlib.sha256(identity_material.encode()).hexdigest()[:16].upper()
    manifest = BundleManifest(
        schema_version=1,
        manifest_id=manifest_id,
        source_archive=archive.name,
        source_archive_sha256=archive_hash,
        generated_at=datetime.now(UTC).isoformat(),
        packages=tuple(records),
        warnings=tuple(warnings),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest
