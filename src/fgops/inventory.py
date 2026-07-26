from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
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


def safe_extract_packages(archive: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            _validate_member(member)
            if member.is_dir() or not member.filename.lower().endswith(".pkg"):
                continue
            target = output_dir / PurePosixPath(member.filename).name
            if target.exists():
                raise ValueError(f"Duplicate package filename after flattening: {target.name}")
            with bundle.open(member) as source, target.open("wb") as destination:
                destination.write(source.read())
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
    return (
        PackageKind(entry["kind"]),
        RestoreFamily(entry["restore_family"]),
        tuple(entry.get("expected_objects", [])),
        bool(entry.get("safe_for_deferred_apply", False)),
    )


def build_manifest(archive: Path, output_dir: Path, package_map: Path) -> BundleManifest:
    archive = archive.resolve()
    extracted_dir = output_dir / "packages"
    packages = safe_extract_packages(archive, extracted_dir)
    mappings = load_package_map(package_map)

    records: list[PackageRecord] = []
    warnings: list[str] = []
    seen_kinds: set[PackageKind] = set()
    for package in packages:
        kind, restore_family, expected_objects, safe = identify_package(package.name, mappings)
        if kind == PackageKind.UNKNOWN:
            warnings.append(f"Unknown package type: {package.name}")
        elif kind in seen_kinds:
            raise ValueError(f"More than one package was identified as {kind.value}.")
        else:
            seen_kinds.add(kind)
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
        generated_at=datetime.now(timezone.utc).isoformat(),
        packages=tuple(records),
        warnings=tuple(warnings),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest
