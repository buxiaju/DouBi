"""Bilibili QR-code login flow.

The B 站 web login flow is:
    1. GET /x/passport-login/web/qrcode/generate
       → returns ``{qrcode_key, url}`` where ``url`` is the QR-code payload
    2. The user scans the QR with the B 站 app.
    3. The CLI polls GET /x/passport-login/web/qrcode/poll?qrcode_key=...
       → returns one of:
           code 86101 — not scanned yet
           code 86090 — scanned, waiting for confirmation
           code 0     — login success (data.refresh_token is set)
    4. On success, the user has logged in **in their app** but the
       SESSDATA / bili_jct cookies are not in our CLI's session.

For M3.1 we deliver the QR generation + polling + ASCII display,
plus a manual cookie-import path (``auth.parse_netscape_file`` /
``auth.parse_json_cookies``) so the user can paste the cookies they
export from the browser after the QR scan.

A Playwright-based fully-automatic flow (open the QR URL in a
headless browser, wait for the cookies to be set, extract them)
is planned for M3.1.1 — it is **not** required for M3.1 to be
useful: any standard "Get cookies.txt LOCALLY" browser extension
exports a Netscape-format file that the import flow accepts.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger("doubi.platforms.bilibili.qr_login")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Public endpoints — no auth needed
GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

# B 站 status codes returned by the poll endpoint
CODE_NOT_SCANNED = 86101
CODE_SCANNED = 86090
CODE_SUCCESS = 0


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class QRStatus(str, Enum):
    """Status of a QR login session."""

    NOT_SCANNED = "not_scanned"
    SCANNED = "scanned"
    SUCCESS = "success"
    EXPIRED = "expired"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class QRCode:
    """A freshly generated QR code from B 站."""

    qrcode_key: str
    url: str                # the URL the QR encodes (used by the app to start the login flow)

    def render_ascii(self, box_size: int = 1) -> str:
        """Render the QR as ASCII for terminal display.

        Returns a multi-line string. Empty if ``qrcode`` is not installed
        (we treat it as a hard dep, but defensively guard anyway).
        """
        try:
            import qrcode  # type: ignore
        except ImportError:  # pragma: no cover
            return f"[qrcode package not installed; visit: {self.url}]"
        qr = qrcode.QRCode(box_size=box_size, border=1)
        qr.add_data(self.url)
        qr.make(fit=True)
        # Use the default ASCII printer from the qrcode package
        from io import StringIO
        buf = StringIO()
        qr.print_ascii(out=buf, invert=False)
        return buf.getvalue().rstrip("\n")


@dataclass
class PollResult:
    """Result of a single poll."""

    status: QRStatus
    code: int                       # raw B 站 status code
    message: str = ""               # human-readable
    refresh_token: Optional[str] = None
    timestamp: int = 0              # server timestamp when polled


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class QRSession:
    """A QR login session.

    Typical usage::

        async with QRSession() as s:
            qr = await s.generate()
            print(qr.render_ascii())
            while True:
                r = await s.poll(qr.qrcode_key)
                if r.status is QRStatus.SUCCESS:
                    break
                if r.status in (QRStatus.EXPIRED, QRStatus.ERROR):
                    raise RuntimeError(r.message)
                await asyncio.sleep(2)
    """

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.timeout = timeout
        self.user_agent = user_agent
        self._client: Optional[httpx.AsyncClient] = client

    async def __aenter__(self) -> "QRSession":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("QRSession must be used as an async context manager")
        return self._client

    # ------------------------------------------------------------------

    async def generate(self) -> QRCode:
        """Step 1: ask B 站 for a new QR code."""
        client = self._require_client()
        resp = await client.get(GENERATE_URL)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"QR generate failed: {data}")
        d = data.get("data") or {}
        return QRCode(qrcode_key=d["qrcode_key"], url=d["url"])

    async def poll(self, qrcode_key: str) -> PollResult:
        """Step 2: poll B 站 for the QR scan status."""
        client = self._require_client()
        resp = await client.get(POLL_URL, params={"qrcode_key": qrcode_key})
        resp.raise_for_status()
        data = resp.json()
        # NB: do NOT collapse "0" via `or -1` — 0 is the success code!
        raw_code = data.get("code")
        code = int(raw_code) if raw_code is not None else -1
        d = data.get("data") or {}

        if code == CODE_SUCCESS:
            status = QRStatus.SUCCESS
        elif code == CODE_NOT_SCANNED:
            status = QRStatus.NOT_SCANNED
        elif code == CODE_SCANNED:
            status = QRStatus.SCANNED
        elif code in (86038, 86039):      # token / qrcode expired variants
            status = QRStatus.EXPIRED
        else:
            status = QRStatus.ERROR

        return PollResult(
            status=status,
            code=code,
            message=str(data.get("message") or ""),
            refresh_token=d.get("refresh_token"),
            timestamp=int(d.get("timestamp") or 0),
        )


# ---------------------------------------------------------------------------
# Helper: wait until success / expiry
# ---------------------------------------------------------------------------


async def wait_for_login(
    session: QRSession,
    qrcode_key: str,
    *,
    poll_interval: float = 2.0,
    max_wait: float = 180.0,
) -> PollResult:
    """Poll the QR login until success / expiry / max_wait.

    Raises ``TimeoutError`` if ``max_wait`` seconds elapse without
    reaching a terminal state. Returns the final :class:`PollResult`.
    """
    import time as _time

    deadline = _time.monotonic() + max_wait
    while True:
        result = await session.poll(qrcode_key)
        if result.status in (QRStatus.SUCCESS, QRStatus.EXPIRED, QRStatus.ERROR):
            return result
        if _time.monotonic() >= deadline:
            raise TimeoutError(f"QR login did not complete within {max_wait:.0f}s")
        await asyncio.sleep(poll_interval)
