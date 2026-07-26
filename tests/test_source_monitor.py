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
