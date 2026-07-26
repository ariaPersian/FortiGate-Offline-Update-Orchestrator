from __future__ import annotations

import ssl
from pathlib import Path

import pytest

from fgops.agent_config import SourceConfig
from fgops.tls import build_tls_context


def test_system_tls_context_keeps_verification_enabled() -> None:
    context = build_tls_context("system")
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_python_tls_context_keeps_verification_enabled() -> None:
    context = build_tls_context("python")
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_custom_tls_mode_requires_existing_ca_file(tmp_path: Path) -> None:
    config = SourceConfig(
        page_url="https://example.test/",
        link_text_regex="example",
        tls_mode="custom",
        ca_file=tmp_path / "missing.pem",
    )
    with pytest.raises(ValueError, match="does not exist"):
        config.validate()


def test_insecure_tls_mode_is_rejected() -> None:
    config = SourceConfig(
        page_url="https://example.test/",
        link_text_regex="example",
        tls_mode="insecure",
    )
    with pytest.raises(ValueError, match="system, python, or custom"):
        config.validate()
