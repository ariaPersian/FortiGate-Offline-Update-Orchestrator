from __future__ import annotations

import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

import tftpy


class TemporaryTftpServer:
    """A short-lived TFTP server restricted to one run directory.

    Downloads are served only from ``root``. Uploads are rejected unless the
    requested basename exactly matches ``allowed_upload_name``. This allows a
    FortiGate configuration backup to be received without creating a general
    writeable TFTP endpoint.
    """

    def __init__(
        self,
        root: Path,
        *,
        bind_address: str,
        port: int = 69,
        allowed_upload_name: str | None = None,
        server_factory: Callable[..., object] = tftpy.TftpServer,
    ) -> None:
        self.root = root.resolve()
        self.bind_address = bind_address
        self.port = port
        self.allowed_upload_name = allowed_upload_name
        self.server_factory = server_factory
        self._server: object | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    def _upload_open(self, requested_path: str, _context: object):
        requested = Path(requested_path)
        name = requested.name
        if (
            self.allowed_upload_name is None
            or name != self.allowed_upload_name
            or requested.is_absolute()
            or ".." in requested.parts
        ):
            return None
        target = self.root / name
        if target.exists():
            target.unlink()
        return target.open("wb")

    def _serve(self) -> None:
        try:
            server = self.server_factory(
                str(self.root),
                upload_open=self._upload_open,
                flock=False,
            )
            self._server = server
            server.listen(self.bind_address, self.port, timeout=1, retries=3)
        except BaseException as exc:  # surfaced to the controlling thread
            self._error = exc

    def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._assert_udp_port_available()
        self._thread = threading.Thread(target=self._serve, name="fgops-tftp", daemon=True)
        self._thread.start()
        time.sleep(0.35)
        if self._error is not None:
            raise RuntimeError(f"TFTP server failed to start: {self._error}") from self._error
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("TFTP server exited during startup.")

    def _assert_udp_port_available(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind((self.bind_address, self.port))

    def stop(self) -> None:
        server = self._server
        if server is not None:
            stop = getattr(server, "stop", None)
            if callable(stop):
                stop(now=True)
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self._error is not None:
            raise RuntimeError(f"TFTP server failed: {self._error}") from self._error

    def __enter__(self) -> TemporaryTftpServer:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.stop()
        except Exception:
            if exc is None:
                raise


def stage_tftp_files(
    source_dir: Path,
    destination_dir: Path,
    filenames: Iterable[str],
) -> tuple[Path, ...]:
    source_dir = source_dir.resolve()
    destination_dir = destination_dir.resolve()
    if destination_dir.exists():
        shutil.rmtree(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    staged: list[Path] = []
    for filename in filenames:
        if Path(filename).name != filename:
            raise ValueError(f"Unsafe TFTP filename: {filename}")
        source = source_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"Package is missing from prepared bundle: {source}")
        target = destination_dir / filename
        shutil.copy2(source, target)
        staged.append(target)
    return tuple(staged)


def wait_for_uploaded_file(path: Path, *, timeout_seconds: int, stable_seconds: float = 0.5) -> Path:
    deadline = time.monotonic() + timeout_seconds
    last_size = -1
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if path.is_file():
            size = path.stat().st_size
            if size > 0 and size == last_size:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= stable_seconds:
                    return path
            else:
                stable_since = None
                last_size = size
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for TFTP upload: {path}")
