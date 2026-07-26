from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    size: int
    source_url: str
    content_type: str


def _safe_filename(url: str, content_disposition: str | None) -> str:
    candidates: list[str] = []
    if content_disposition:
        match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", content_disposition, re.I)
        if match:
            candidates.append(unquote(match.group(1).strip().strip('"')))
    candidates.append(unquote(Path(urlparse(url).path).name))

    for candidate in candidates:
        name = Path(candidate).name
        if name and name not in {".", ".."}:
            return re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return "fgops-bundle.zip"


def download_bundle(
    url: str,
    destination_dir: Path,
    *,
    timeout_seconds: int,
    max_download_bytes: int,
    user_agent: str,
) -> DownloadResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Download URL must be absolute HTTP(S).")

    destination_dir.mkdir(parents=True, exist_ok=True)
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/zip,application/octet-stream,*/*;q=0.1",
        },
    )

    temporary: Path | None = None
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL is discovered from the configured source.
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_download_bytes:
                raise ValueError("Remote bundle exceeds source.max_download_bytes.")

            filename = _safe_filename(url, response.headers.get("Content-Disposition"))
            if not filename.lower().endswith(".zip"):
                filename += ".zip"
            temporary = destination_dir / f".{filename}.{os.getpid()}.part"
            digest = hashlib.sha256()
            size = 0
            with temporary.open("xb") as stream:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_download_bytes:
                        raise ValueError("Downloaded bundle exceeds source.max_download_bytes.")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())

            if size == 0:
                raise ValueError("Downloaded bundle is empty.")
            final_path = destination_dir / f"{digest.hexdigest()[:16]}-{filename}"
            if final_path.exists():
                temporary.unlink()
            else:
                temporary.replace(final_path)
            return DownloadResult(
                path=final_path,
                sha256=digest.hexdigest(),
                size=size,
                source_url=response.geturl(),
                content_type=response.headers.get_content_type(),
            )
    except Exception:
        if temporary and temporary.exists():
            temporary.unlink()
        raise
