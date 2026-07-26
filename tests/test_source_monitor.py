from __future__ import annotations

import pytest

from fgops.source_monitor import discover_download_link


PAGE_URL = "https://example.test/offline-updates/"


def test_discovers_version_from_text_before_anchor() -> None:
    html = """
    <ul>
      <li>Fortigate V6.2 – <a href="/files/v62.zip">دانلود</a></li>
      <li>Fortigate V6.4 – <a href="/files/v64.zip">دانلود</a></li>
    </ul>
    """
    result = discover_download_link(html, PAGE_URL, r"(?i)Fortigate\s+V6\.4")
    assert result.url == "https://example.test/files/v64.zip"
    assert "Fortigate V6.4" in result.context


def test_scopes_match_to_one_cyberlogic_list_item() -> None:
    html = """
    <section>
      <ul>
        <li>Fortigate V6.0 – <a href="/Cyberlogic-Fortigate-V6.0-Weekly-Signature.zip">دانلود</a></li>
        <li>Fortigate V6.2 – <a href="/Cyberlogic-Fortigate-V6.2-Weekly-Signature.zip">دانلود</a></li>
        <li>Fortigate V6.4 – <a href="/Cyberlogic-Fortigate-V6.4-Weekly-Signature.zip">دانلود</a></li>
        <li>Fortigate V7.0 – <a href="/Cyberlogic-Fortigate-V7.0-Weekly-Signature.zip">دانلود</a></li>
        <li>Fortigate V7.2 – <a href="/Cyberlogic-Fortigate-V7.2-Weekly-Signature.zip">دانلود</a></li>
        <li>Fortigate V7.4 – <a href="/Cyberlogic-Fortigate-V7.4-Weekly-Signature.zip">دانلود</a></li>
        <li>Fortigate V7.6 – <a href="/Cyberlogic-Fortigate-V7.6-Weekly-Signature.zip">دانلود</a></li>
        <li>Fortigate V8.0 – <a href="/Cyberlogic-Fortigate-V8.0-Weekly-Signature.zip">دانلود</a></li>
      </ul>
      <ul>
        <li>FortiWeb V6.3 – <a href="/Cyberlogic-FortiWeb-V6.3-Weekly-Signature.zip">دانلود</a></li>
        <li>FortiWeb V6.4 – <a href="/Cyberlogic-FortiWeb-V6.4-Weekly-Signature.zip">دانلود</a></li>
      </ul>
    </section>
    """
    result = discover_download_link(html, PAGE_URL, r"(?i)Fortigate\s+V6\.4")
    assert result.url.endswith("/Cyberlogic-Fortigate-V6.4-Weekly-Signature.zip")
    assert result.context == "Fortigate V6.4 – دانلود"


def test_supports_nested_inline_markup_inside_list_item() -> None:
    html = """
    <ul>
      <li><strong>Fortigate</strong> <span>V6.4</span> – <a href="/v64.zip"><em>دانلود</em></a></li>
    </ul>
    """
    result = discover_download_link(html, PAGE_URL, r"(?i)Fortigate\s+V6\.4")
    assert result.url == "https://example.test/v64.zip"


def test_rejects_ambiguous_matching_links() -> None:
    html = """
    <p>Fortigate V6.4 <a href="/a.zip">primary</a></p>
    <p>Fortigate V6.4 <a href="/b.zip">mirror</a></p>
    """
    with pytest.raises(ValueError, match="More than one"):
        discover_download_link(html, PAGE_URL, r"(?i)Fortigate\s+V6\.4")


def test_rejects_missing_link() -> None:
    with pytest.raises(ValueError, match="No download link"):
        discover_download_link("<p>No packages</p>", PAGE_URL, r"Fortigate V6\.4")
