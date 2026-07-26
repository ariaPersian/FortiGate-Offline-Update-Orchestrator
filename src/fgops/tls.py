from __future__ import annotations

import ssl
from pathlib import Path

import truststore


def build_tls_context(mode: str, ca_file: Path | None = None) -> ssl.SSLContext:
    """Build a hostname-verifying TLS client context.

    ``system`` uses the operating system trust store. On Windows this is
    CryptoAPI, which also supports enterprise CAs and missing-intermediate
    retrieval. ``python`` uses CPython/OpenSSL defaults. ``custom`` loads an
    operator-supplied CA bundle while preserving certificate and hostname
    verification.
    """

    normalized = mode.strip().lower()
    if normalized == "system":
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    elif normalized == "python":
        context = ssl.create_default_context()
    elif normalized == "custom":
        if ca_file is None:
            raise ValueError("source.ca_file is required when source.tls_mode is custom.")
        if not ca_file.is_file():
            raise ValueError(f"Configured source.ca_file does not exist: {ca_file}")
        context = ssl.create_default_context(cafile=str(ca_file))
    else:
        raise ValueError("source.tls_mode must be system, python, or custom.")

    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.set_alpn_protocols(["http/1.1"])
    return context
