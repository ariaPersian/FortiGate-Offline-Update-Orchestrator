from __future__ import annotations

import os
from pathlib import Path

from fgops import secret_store


def _install_fake_backend(monkeypatch) -> None:
    monkeypatch.setattr(secret_store, "_protect_bytes", lambda value: b"enc:" + value[::-1])
    monkeypatch.setattr(
        secret_store,
        "_unprotect_bytes",
        lambda value: value.removeprefix(b"enc:")[::-1],
    )
    monkeypatch.setattr(secret_store, "_harden_acl", lambda _path: None)


def test_secret_store_never_writes_plaintext(tmp_path: Path, monkeypatch) -> None:
    _install_fake_backend(monkeypatch)
    path = tmp_path / "secrets" / "secret-store.json"

    metadata = secret_store.set_secret(path, "FGOPS_SSH_PASSWORD", "super-secret-value")

    assert metadata.name == "FGOPS_SSH_PASSWORD"
    raw = path.read_text(encoding="utf-8")
    assert "super-secret-value" not in raw
    assert secret_store.get_secret(path, "FGOPS_SSH_PASSWORD") == "super-secret-value"
    assert [item.name for item in secret_store.list_secrets(path)] == ["FGOPS_SSH_PASSWORD"]


def test_secret_environment_restores_previous_process_values(tmp_path: Path, monkeypatch) -> None:
    _install_fake_backend(monkeypatch)
    path = tmp_path / "secret-store.json"
    secret_store.set_secret(path, "FGOPS_SSH_PASSWORD", "stored")
    monkeypatch.setenv("FGOPS_SSH_PASSWORD", "original")

    with secret_store.secret_environment(path, ("FGOPS_SSH_PASSWORD",)):
        assert os.environ["FGOPS_SSH_PASSWORD"] == "stored"

    assert os.environ["FGOPS_SSH_PASSWORD"] == "original"


def test_delete_secret_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    _install_fake_backend(monkeypatch)
    path = tmp_path / "secret-store.json"
    secret_store.set_secret(path, "FGOPS_BACKUP_PASSWORD", "backup")

    assert secret_store.delete_secret(path, "FGOPS_BACKUP_PASSWORD") is True
    assert secret_store.delete_secret(path, "FGOPS_BACKUP_PASSWORD") is False
