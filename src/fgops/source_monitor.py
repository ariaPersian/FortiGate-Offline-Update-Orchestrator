from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    text: str
    context: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._recent_text = ""
        self._active_href: str | None = None
        self._active_before = ""
        self._active_text: list[str] = []
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._active_href is not None:
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if href:
            self._active_href = href
            self._active_before = self._recent_text[-240:]
            self._active_text = []

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if not normalized:
            return
        self._recent_text = f"{self._recent_text} {normalized}"[-480:]
        if self._active_href is not None:
            self._active_text.append(normalized)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._active_href is None:
            return
        text = " ".join(self._active_text).strip()
        context = " ".join(f"{self._active_before} {text}".split())
        self.links.append((self._active_href, text, context))
        self._active_href = None
        self._active_before = ""
        self._active_text = []


def fetch_page(
    url: str,
    *,
    timeout_seconds: int,
    user_agent: str,
    ssl_context: ssl.SSLContext | None = None,
) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(  # noqa: S310 - URL is configured by the operator.
        request,
        timeout=timeout_seconds,
        context=ssl_context,
    ) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"Source page returned unexpected content type: {content_type}")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def discover_download_link(page_html: str, page_url: str, link_text_regex: str) -> DiscoveredLink:
    matcher = re.compile(link_text_regex)
    parser = _LinkParser()
    parser.feed(page_html)

    candidates: list[DiscoveredLink] = []
    for href, text, context in parser.links:
        resolved = urljoin(page_url, href)
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        searchable = " ".join((context, text, resolved))
        if matcher.search(searchable):
            candidates.append(DiscoveredLink(url=resolved, text=text, context=context))

    zip_candidates = [item for item in candidates if urlparse(item.url).path.lower().endswith(".zip")]
    selected = zip_candidates or candidates
    unique = {item.url: item for item in selected}
    if not unique:
        raise ValueError("No download link matched source.link_text_regex.")
    if len(unique) > 1:
        urls = ", ".join(sorted(unique))
        raise ValueError(f"More than one download link matched: {urls}")
    return next(iter(unique.values()))
