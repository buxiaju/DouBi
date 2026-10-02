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
    4. On success, B 站 sets ``SESSDATA`` / ``bili_jct`` / ``DedeUserID`` /
       ``sid`` on the poll response's ``Set-Cookie`` header. They land in
       :class:`QRSession`'s internal ``httpx.AsyncClient.cookies`` so we
       can extract them and persist via :func:`cookies_to_netscape`.

The M6.16 rewrite removes two earlier M3.1 warts:

* ``QRCode.render_ascii`` is kept for the CLI but the GUI now uses
  :meth:`QRCode.render_pil` (a real ``PIL.Image``) so QR codes render
  sharply at any dialog size.
* The Playwright fallback that previously opened a second Chromium
  window after a successful scan to "harvest" cookies is **gone**.
  The poll endpoint already issues the cookies on the same response;
  re-opening a browser would be both redundant and visually
  disruptive.

M3.1.1-style account-password / SMS flows are intentionally not
implemented because B 站's web login is gated by GeeTest (滑块) and
the ``b_ret`` / ``b_wet`` device-fingerprint WASM that cannot be
synthesized from a pure-httpx client. Users who need those flows
should use the QR tab or "Import Cookie" tab.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import httpx

if TYPE_CHECKING:
    # PIL 只是 ``qrcode`` 的可选依赖（``render_pil`` 才需要），不能做运行期
    # 顶层导入——没装 Pillow 时整个 qr_login 模块都要能用（ASCII 路径是
    # CLI 的默认渲染方式）。放进 TYPE_CHECKING 让类型检查器认得这个名字。
    # 注意 ``render_pil`` 的返回值是字符串注解，运行期不会求值，因此这里
    # 不需要额外的运行期绑定。
    import PIL.Image

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

# Cookies that must be present for downstream BilibiliAdapter to behave as
# a logged-in client. ``SESSDATA`` is the session key; ``bili_jct`` is the
# CSRF token required by write endpoints; the rest are nice-to-have for
# avatar / follower / dm calls. Keep the order so the Netscape dump
# matches what users would export from "Get cookies.txt LOCALLY".
REQUIRED_BILIBILI_COOKIES: tuple[str, ...] = (
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "sid",
)

# Default domain for Netscape export — B 站 cookies are issued on
# ``.bilibili.com`` so we hardcode it to avoid a per-cookie lookup.
BILIBILI_COOKIE_DOMAIN = ".bilibili.com"


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

    def render_pil(self, *, box_size: int = 10, border: int = 4) -> "PIL.Image.Image":
        """Render the QR as a real ``PIL.Image``.

        The GUI's :class:`LoginDialog` converts this into a ``QPixmap``
        so the QR renders sharply at any dialog size. The image is
        returned in ``L`` (8-bit grayscale) mode which ``QImage`` /
        ``QPixmap`` accept directly without an extra ``convert``.

        ``qrcode >= 7.4``'s ``PilImage`` class is **not** a subclass of
        ``PIL.Image.Image`` (its MRO is ``[PilImage, BaseImage, object]``),
        so a plain ``isinstance`` guard would skip the mode promotion.
        We unconditionally call ``.convert('L')`` — qrcode's
        ``BaseImage.convert`` delegates to the underlying PIL image and
        returns a real ``PIL.Image.Image`` in ``L`` mode. The only edge
        case is if a future qrcode version returns something exotic; we
        keep the size-check as a final safety net.
        """
        from PIL import Image
        import qrcode
        from qrcode.image.pil import PilImage

        qr = qrcode.QRCode(box_size=box_size, border=border)
        qr.add_data(self.url)
        qr.make(fit=True)
        raw = qr.make_image(
            image_factory=PilImage, fill_color="black", back_color="white"
        )
        img = raw.convert("L")
        # Final safety: if any of the above returned something that is
        # not a PIL Image (e.g. an exotic qrcode factory), reconstruct
        # from a fresh 8-bit grayscale canvas.
        if not isinstance(img, Image.Image):
            img = Image.new("L", (100, 100), 255)
        return img


@dataclass
class PollResult:
    """Result of a single poll."""

    status: QRStatus
    code: int                       # raw B 站 status code
    message: str = ""               # human-readable
    refresh_token: Optional[str] = None
    timestamp: int = 0              # server timestamp when polled
    # M6.30: on success, B 站 returns ``data.url`` — a redirect URL
    # that the client must GET in order to receive the actual
    # ``Set-Cookie`` headers (DedeUserID / SESSDATA / bili_jct / sid).
    # The poll response itself does **not** set those cookies. Callers
    # of :func:`bilibili_login_via_qr` need to follow this URL after
    # the SUCCESS poll to populate the httpx cookie jar.
    url: Optional[str] = None


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
            url=d.get("url"),
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


# ---------------------------------------------------------------------------
# Cookie extraction + Netscape serialization
# ---------------------------------------------------------------------------


def _cookies_from_client(client: httpx.AsyncClient) -> dict[str, str]:
    """Return the cookies the QR session has collected so far.

    After ``QRStatus.SUCCESS`` B 站 has issued ``SESSDATA`` /
    ``bili_jct`` / ``DedeUserID`` / ``sid`` via ``Set-Cookie`` on the
    poll response. The httpx client absorbs them into its jar
    automatically. We surface them as a flat ``{name: value}`` dict.

    We use the public ``client.cookies`` mapping (not the internal
    ``_client`` attribute) so unit tests can substitute a custom
    ``httpx.AsyncClient`` with pre-seeded cookies.
    """
    out: dict[str, str] = {}
    jar = client.cookies
    # ``httpx.Cookies`` is dict-shaped: iterating yields the cookie name;
    # ``jar[name]`` returns the value. Older ``cookielib`` style jars
    # are not used in our stack.
    for name in jar:
        value = jar.get(name)
        if value is not None:
            out[name] = value
    return out


def cookies_to_netscape(
    cookies: dict[str, str],
    *,
    domain: str = BILIBILI_COOKIE_DOMAIN,
    include_subdomains: bool = True,
) -> str:
    """Serialize a ``{name: value}`` cookie dict as a Netscape file.

    The format is the one yt-dlp / youtube-dl / curl all accept::

        # Netscape HTTP Cookie File
        .bilibili.com\tTRUE\t/\tFALSE\t9999999999\tSESSDATA\t<value>
        ...

    Tab-separated, 7 fields per row, ``include_subdomains`` maps to the
    second field (TRUE / FALSE). Expiry is set to ``9999999999`` (year
    2286) so downstream tools don't drop the cookies.
    """
    include_flag = "TRUE" if include_subdomains else "FALSE"
    expiry = "9999999999"
    lines = ["# Netscape HTTP Cookie File"]
    for name in REQUIRED_BILIBILI_COOKIES:
        value = cookies.get(name)
        if not value:
            continue
        lines.append(
            "\t".join([domain, include_flag, "/", "FALSE", expiry, name, value])
        )
    # Preserve any extra cookies the server may have set (e.g. ``bp_video_offset_...``)
    for name, value in cookies.items():
        if not name or not value:
            # Skip empty names and empty values — both would produce
            # invalid Netscape rows (e.g. ``... \t\tfoo``).
            continue
        if name in REQUIRED_BILIBILI_COOKIES:
            continue
        lines.append(
            "\t".join([domain, include_flag, "/", "FALSE", expiry, name, value])
        )
    return "\n".join(lines) + "\n"


def _ensure_login_drive_cookie_path(cookie_path: Path) -> Path:
    """Make sure the parent directory exists with reasonable perms.

    Mirrors what the auth command does for ``~/.doubi/cookies/*.txt``.
    """
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    return cookie_path


def save_cookies_to_drive(cookies: dict[str, str], cookie_path: Path) -> Path:
    """Persist a Netscape cookie file for the B 站 platform.

    ``cookie_path`` is typically ``<config_dir>/cookies/bilibili.txt``
    resolved by the caller (so the GUI's settings page and the CLI
    agree on the location).
    """
    text = cookies_to_netscape(cookies)
    _ensure_login_drive_cookie_path(cookie_path)
    cookie_path.write_text(text, encoding="utf-8")
    return cookie_path


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


async def bilibili_login_via_qr(
    cookie_path: Path,
    *,
    poll_interval: float = 2.0,
    max_wait: float = 180.0,
    on_qr_ready: Optional[Callable[["QRCode"], None]] = None,
    on_status: Optional[Callable[["PollResult"], None]] = None,
) -> Path:
    """Run the full QR login flow and persist the resulting cookies.

    ``on_qr_ready`` is invoked synchronously with a :class:`QRCode`
    instance as soon as B 站 hands one back — the GUI converts it to
    a ``QPixmap``. ``on_status`` is invoked with a :class:`PollResult`
    (or one of the constant :class:`QRStatus` members) on each poll
    tick so the dialog can update its "scan / confirm / done" label.

    Returns the resolved :class:`Path` of the cookie file on success.
    Raises :class:`RuntimeError` / :class:`TimeoutError` on failure.
    """
    async with QRSession() as s:
        qr = await s.generate()
        if on_qr_ready is not None:
            on_qr_ready(qr)
        result = await wait_for_login(
            s,
            qr.qrcode_key,
            poll_interval=poll_interval,
            max_wait=max_wait,
        )
        if on_status is not None:
            on_status(result)
        if result.status is not QRStatus.SUCCESS:
            raise RuntimeError(
                f"B 站 QR 登录失败:{result.message or result.status.name} "
                f"(code={result.code})"
            )

        # M6.31 历史: 之前在这里 GET ``result.url`` 试图让 Set-Cookie
        # 头落到 client.jar,但 B 站 web 端针对纯 API 路径反爬,Set-Cookie
        # 要么在 JS 写 cookie 里(纯 httpx 看不到),要么要求浏览器特定
        # header state——这条路径 2026-09 实测拿不到 cookies。
        # CLI 用户如果想用纯 web API 走 B 站,需要走 Playwright
        # 路径(M3.1 + M6.31);这里保持纯 API 但最终会落在「缺少关键
        # cookie」分支,跟原来 M6.25 行为一致。

        cookies = _cookies_from_client(s._client)  # noqa: SLF001
        missing = [c for c in REQUIRED_BILIBILI_COOKIES if c not in cookies]
        if missing:
            raise RuntimeError(
                "B 站扫码成功但缺少关键 cookie:"
                + ", ".join(missing)
                + "。请重试或改用「导入 Cookie」(或用 CLI 走 Playwright "
                + "的 ``doubi auth bilibili --browser``)。"
            )
        return save_cookies_to_drive(cookies, cookie_path)
