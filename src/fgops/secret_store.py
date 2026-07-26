from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import subprocess
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .agent_state import utc_now

_SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_ENTROPY = b"FGOps/WindowsMachineSecretStore/v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


@dataclass(frozen=True)
class SecretMetadata:
    name: str
    updated_at: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "updated_at": self.updated_at}


def _validate_name(name: str) -> str:
    normalized = name.strip().upper()
    if not _SECRET_NAME_RE.fullmatch(normalized):
        raise ValueError("Secret names must match ^[A-Z][A-Z0-9_]{2,127}$.")
    return normalized


def _make_blob(data: bytes) -> tuple[_DataBlob, object]:
    if not data:
        return _DataBlob(0, None), None
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _windows_libraries():
    if os.name != "nt":
        raise OSError("The FGOps DPAPI secret store is available only on Windows.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _protect_bytes(data: bytes) -> bytes:
    if not data:
        raise ValueError("Secret values cannot be empty.")
    crypt32, kernel32 = _windows_libraries()
    input_blob, input_buffer = _make_blob(data)
    entropy_blob, entropy_buffer = _make_blob(_ENTROPY)
    output_blob = _DataBlob()
    del input_buffer, entropy_buffer
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "FGOps machine secret",
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN | _CRYPTPROTECT_LOCAL_MACHINE,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect_bytes(data: bytes) -> bytes:
    crypt32, kernel32 = _windows_libraries()
    input_blob, input_buffer = _make_blob(data)
    entropy_blob, entropy_buffer = _make_blob(_ENTROPY)
    output_blob = _DataBlob()
    del input_buffer, entropy_buffer
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _run_icacls(arguments: list[str]) -> None:
    completed = subprocess.run(
        ["icacls", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Unable to harden secret-store ACLs with icacls: {detail}")


def _harden_acl(path: Path) -> None:
    if os.name != "nt":
        raise OSError("Secret-store ACL hardening is available only on Windows.")
    directory = path.parent
    _run_icacls(
        [
            str(directory),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ]
    )
    if path.exists():
        _run_icacls(
            [
                str(path),
                "/inheritance:r",
                "/grant:r",
                "*S-1-5-18:F",
                "*S-1-5-32-544:F",
            ]
        )


def _empty_store() -> dict[str, object]:
    return {"schema_version": 1, "scope": "LocalMachine", "secrets": {}}


def _load_store(path: Path) -> dict[str, object]:
    if not path.exists():
        return _empty_store()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
        raise ValueError("Unsupported or invalid FGOps secret-store schema.")
    if raw.get("scope") != "LocalMachine" or not isinstance(raw.get("secrets"), dict):
        raise ValueError("Invalid FGOps secret-store content.")
    return raw


def _save_store(path: Path, store: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _harden_acl(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    _harden_acl(temporary)
    temporary.replace(path)
    _harden_acl(path)


def set_secret(path: Path, name: str, value: str) -> SecretMetadata:
    normalized = _validate_name(name)
    if not value:
        raise ValueError("Secret values cannot be empty.")
    store = _load_store(path)
    secrets = store["secrets"]
    assert isinstance(secrets, dict)
    updated_at = utc_now()
    ciphertext = _protect_bytes(value.encode("utf-8"))
    secrets[normalized] = {
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "updated_at": updated_at,
    }
    _save_store(path, store)
    return SecretMetadata(name=normalized, updated_at=updated_at)


def get_secret(path: Path, name: str) -> str:
    normalized = _validate_name(name)
    store = _load_store(path)
    secrets = store["secrets"]
    assert isinstance(secrets, dict)
    entry = secrets.get(normalized)
    if not isinstance(entry, dict) or not isinstance(entry.get("ciphertext"), str):
        raise KeyError(f"Secret is not configured: {normalized}")
    try:
        protected = base64.b64decode(entry["ciphertext"], validate=True)
    except ValueError as exc:
        raise ValueError(f"Secret ciphertext is invalid: {normalized}") from exc
    return _unprotect_bytes(protected).decode("utf-8")


def list_secrets(path: Path) -> tuple[SecretMetadata, ...]:
    store = _load_store(path)
    secrets = store["secrets"]
    assert isinstance(secrets, dict)
    result: list[SecretMetadata] = []
    for name in sorted(secrets):
        entry = secrets[name]
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid secret metadata for {name}.")
        result.append(SecretMetadata(name=name, updated_at=str(entry.get("updated_at", ""))))
    return tuple(result)


def delete_secret(path: Path, name: str) -> bool:
    normalized = _validate_name(name)
    store = _load_store(path)
    secrets = store["secrets"]
    assert isinstance(secrets, dict)
    existed = normalized in secrets
    if existed:
        del secrets[normalized]
        _save_store(path, store)
    return existed


@contextmanager
def secret_environment(path: Path, names: tuple[str, ...]) -> Iterator[None]:
    normalized_names = tuple(dict.fromkeys(_validate_name(name) for name in names if name))
    previous = {name: os.environ.get(name) for name in normalized_names}
    try:
        for name in normalized_names:
            os.environ[name] = get_secret(path, name)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
