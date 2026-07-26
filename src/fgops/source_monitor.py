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
    """Collect links with context limited to their nearest semantic item.

    A rolling page-wide text window causes a version label from one list item
    to leak into all following links. Cyberlogic renders each product/version
    as a separate ``li`` whose anchor text is only ``دانلود``. Restricting the
    context to the nearest list/paragraph/table item binds each link to the
    correct product and version without relying on page order.
    """

    _CONTEXT_TAGS = {"li", "p", "td", "th", "dt", "dd"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._contexts: list[tuple[str, list[str]]] = []
        self._active_href: str | None = None
        self._active_text: list[str] = []
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in self._CONTEXT_TAGS:
            self._contexts.append((normalized_tag, []))

        if normalized_tag != "a" or self._active_href is not None:
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if href:
            self._active_href = href
            self._active_text = []

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if not normalized:
            return
        for _, parts in self._contexts:
            parts.append(normalized)
        if self._active_href is not None:
            self._active_text.append(normalized)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "a" and self._active_href is not None:
            text = " ".join(self._active_text).strip()
            context = text
            if self._contexts:
                context = " ".join(self._contexts[-1][1]).strip()
            self.links.append((self._active_href, text, context))
            self._active_href = None
            self._active_text = []

        if normalized_tag in self._CONTEXT_TAGS:
            for index in range(len(self._contexts) - 1, -1, -1):
                if self._contexts[index][0] == normalized_tag:
                    del self._contexts[index:]
                    break


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
