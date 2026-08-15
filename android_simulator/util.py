from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .errors import AndroidSimError


@dataclass(frozen=True)
class Result:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def quote_command(args: Sequence[str]) -> str:
    """Return a readable shell representation without invoking a shell."""
    import shlex

    return shlex.join([str(arg) for arg in args])


def run(
    args: Sequence[str | Path],
    *,
    check: bool = True,
    capture: bool = True,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    quiet: bool = False,
) -> Result:
    argv = tuple(str(arg) for arg in args)
    if not quiet:
        print(f"+ {quote_command(argv)}", file=sys.stderr)
    completed = subprocess.run(
        argv,
        check=False,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=dict(env) if env is not None else None,
        cwd=str(cwd) if cwd else None,
    )
    result = Result(
        args=argv,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise AndroidSimError(
            f"Command failed ({result.returncode}): {quote_command(argv)}\n{detail}"
        )
    return result


def which(name: str, candidates: Iterable[Path] = ()) -> Path | None:
    found = shutil.which(name)
    if found:
        return Path(found).resolve()
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def atomic_write(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    if mode is not None:
        temp_path.chmod(mode)
    temp_path.replace(path)


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise AndroidSimError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AndroidSimError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AndroidSimError(f"Expected a JSON object in {path}")
    return value


def save_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha256(value: str) -> str:
    normalized = value.lower().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise AndroidSimError("SHA-256 must be exactly 64 hexadecimal characters")
    return normalized


def safe_download_name(url: str, fallback: str = "download.bin") -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path)).name
    if not name or name in {".", ".."}:
        return fallback
    return re.sub(r"[^A-Za-z0-9._+-]", "_", name)[:180] or fallback



class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, allow_http: bool) -> None:
        super().__init__()
        self.allow_http = allow_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        scheme = urllib.parse.urlparse(newurl).scheme.lower()
        allowed = {"https", "http"} if self.allow_http else {"https"}
        if scheme not in allowed:
            raise AndroidSimError(
                f"Refusing download redirect to unsupported scheme {scheme!r}: {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def download(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    allow_http: bool = False,
) -> Path:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ({"https", "http"} if allow_http else {"https"}):
        requirement = "HTTPS or HTTP" if allow_http else "HTTPS"
        raise AndroidSimError(f"Download URL must use {requirement}: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "android-simulator/0.1 (+https://github.com/Jadenfix/android-simulator)"},
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler(allow_http=allow_http))
    temp_path: Path | None = None
    try:
        with opener.open(request, timeout=60) as response, tempfile.NamedTemporaryFile(
            "wb", dir=destination.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
            shutil.copyfileobj(response, handle, length=1024 * 1024)
    except AndroidSimError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # urllib exposes several transport-specific exceptions
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise AndroidSimError(f"Failed to download {url}: {exc}") from exc

    assert temp_path is not None
    if expected_sha256:
        expected = validate_sha256(expected_sha256)
        actual = sha256_file(temp_path)
        if actual != expected:
            temp_path.unlink(missing_ok=True)
            raise AndroidSimError(
                f"SHA-256 mismatch for {url}: expected {expected}, got {actual}"
            )
    temp_path.replace(destination)
    return destination


def parse_version(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", text)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))
