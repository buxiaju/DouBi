"""Update check — GitHub Releases API based "new version" notifier.

Borrowed design from BiliMusic-Desktop: a desktop app should tell the
user a new version exists *inside the app* instead of hoping they read
the release page. This module is pure stdlib + the repo's existing http
helper, platform-agnostic, and safe to call from any surface (GUI /
CLI / REST).

Design constraints (project conventions):

- Platform-agnostic: lives in ``core/``, knows nothing about Qt or
  yt-dlp. GUI wires the result into an InfoBar; CLI/REST can print it.
- Fail-silent: any network/parse error returns ``None``-ish results,
  never raises — an update check must never break startup.
- Network discipline: one GET to ``api.github.com`` per check, short
  timeout, honors the app-level proxy setting when provided.
- Version comparison is a plain tuple compare on the numeric dots of
  ``X.Y.Z``; anything non-numeric (``0.4.0-beta1``) compares
  gracefully by falling back to the numeric prefix.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .. import __version__


#: GitHub repo to query. Central here so tests can monkeypatch it and
#: a future repo move only touches one line.
GITHUB_REPO = "buxiaju/DouBi"

#: GitHub mirror used when direct api.github.com access is flaky
#: (mainland China networks). Empty means "no mirror, direct only".
GITHUB_API_MIRRORS: tuple[str, ...] = (
    "https://api.github.com",
    "https://gh-api.zstart.cc/https://api.github.com",  # community mirror
)

REQUEST_TIMEOUT = 8.0  # seconds — short: this runs at startup


@dataclass
class UpdateInfo:
    """Result of a successful update check.

    ``update_available`` is the single field callers should branch on;
    the rest is presentation material.
    """

    latest_version: str
    current_version: str
    update_available: bool
    release_url: str
    release_notes: str          # release body, may be empty
    published_at: str           # ISO date string, may be empty

    def summary_line(self) -> str:
        """One-line human summary for CLI / InfoBar text."""
        if not self.update_available:
            return f"已是最新版本 (v{self.current_version})"
        return f"发现新版本 v{self.latest_version}（当前 v{self.current_version}）"


def parse_version(version: str) -> tuple[int, ...]:
    """Extract a numeric tuple from a version string.

    ``"v0.4.5"`` → ``(0, 4, 5)``; ``"0.4.0-beta1"`` → ``(0, 4, 0)``.
    Non-numeric input yields ``(0,)`` so it never reports "newer".
    """
    match = re.match(r"v?(\d+(?:\.\d+)*)", (version or "").strip())
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    """True if ``latest`` is strictly newer than ``current``.

    Tuple comparison with right-padding, so ``0.4`` vs ``0.4.0`` ties
    and ``0.10.0`` correctly beats ``0.9.9`` (string compare would not).
    """
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    return (a + (0,) * (width - len(a))) > (b + (0,) * (width - len(b)))


def fetch_latest_release(
    timeout: float = REQUEST_TIMEOUT,
    repo: str = GITHUB_REPO,
) -> Optional[UpdateInfo]:
    """Query GitHub Releases API for the latest published release.

    Returns ``None`` on any failure (offline / rate-limited / parse
    error / disabled). Callers must treat ``None`` as "don't know",
    not as "up to date".
    """
    info = _try_endpoints(repo, GITHUB_API_MIRRORS, timeout)
    return info


def _try_endpoints(
    repo: str, endpoints: tuple[str, ...], timeout: float
) -> Optional[UpdateInfo]:
    last_error: Optional[Exception] = None
    for base in endpoints:
        url = f"{base}/repos/{repo}/releases/latest"
        try:
            raw = _http_get_json(url, timeout)
        except Exception as exc:  # noqa: BLE001 — fail-silent by contract
            last_error = exc
            continue
        info = _parse_release(raw)
        if info is not None:
            return info
    if last_error is not None:
        # Surface in debug logs without breaking callers.
        from .logger import get_logger

        get_logger(__name__).debug("update check failed: %s", last_error)
    return None


def _http_get_json(url: str, timeout: float) -> dict:
    """Minimal stdlib JSON GET — avoids importing the heavier http layer."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "DouBi-UpdateCheck",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_release(payload: dict) -> Optional[UpdateInfo]:
    """Extract :class:`UpdateInfo` from a GitHub release payload.

    Drafts and prereleases are ignored (``/releases/latest`` already
    excludes drafts, but the flag check documents intent).
    """
    tag = str(payload.get("tag_name") or "").strip()
    if not tag or payload.get("draft") or payload.get("prerelease"):
        return None
    latest = tag.lstrip("vV")
    current = __version__
    return UpdateInfo(
        latest_version=latest,
        current_version=current,
        update_available=is_newer(latest, current),
        release_url=str(payload.get("html_url") or ""),
        release_notes=str(payload.get("body") or ""),
        published_at=str(payload.get("published_at") or ""),
    )
