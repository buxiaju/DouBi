"""Tests for M6.48 Douyin signing: ms-token / tt-wid / x-secsdk-web-signature.

These tests pin the algorithm to known-good vectors so any drift in the
canonical encoding, SALT, or URL whitelist shows up as a test failure
rather than a silent 403 in production.

M6.53 — Survey §8.1 item #6. Adds tests that pin the real ``strData``
blob + ``TOKEN`` from TikTokDL's mssdk extract. These constants get
re-captured whenever 抖音 rotates ``runtime_bundler_*.js``; the pin tests
turn that rotation into a deliberate, visible decision rather than a
silent 403 regression.
"""

from __future__ import annotations

import httpx
import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SRC))

from doubi.platforms.douyin.sign import (  # noqa: E402
    DOUYIN_SIGNED_PATHS,
    SALT,
    TtWidFetcher,
    is_sign_protected,
    normalize_query,
    websign_sign,
)
from doubi.platforms.douyin.sign.ms_token import (  # noqa: E402
    MsTokenFetcher,
    _MSSDK_DEFAULT_TOKEN,
    _MSSDK_STRDATA,
)
from doubi.platforms.douyin.webapi import DouyinWebAPI  # noqa: E402


# ---------------------------------------------------------------------------
# DOUYIN_SIGNED_PATHS whitelist
# ---------------------------------------------------------------------------


def test_signed_paths_includes_doubi_used_endpoints():
    """Three paths DouBie's webapi calls must all be in the whitelist."""
    assert "/aweme/v1/web/aweme/detail/" in DOUYIN_SIGNED_PATHS
    assert "/aweme/v1/web/aweme/post/" in DOUYIN_SIGNED_PATHS
    assert "/aweme/v1/web/mix/aweme/" in DOUYIN_SIGNED_PATHS


def test_is_sign_protected_matches_with_and_without_trailing_slash():
    """whitelist uses /foo/bar/ form, urlsplit must normalise both sides."""
    assert is_sign_protected("https://www.douyin.com/aweme/v1/web/mix/aweme/")
    assert is_sign_protected("https://www.douyin.com/aweme/v1/web/mix/aweme")
    # Relative path with leading slash
    assert is_sign_protected("aweme/v1/web/mix/aweme/")
    # Unknown endpoint should NOT be matched
    assert not is_sign_protected("https://www.douyin.com/aweme/v1/web/unknown/")


# ---------------------------------------------------------------------------
# SALT — pin to TikTokDL's known value; drift = re-reverse-engineer required
# ---------------------------------------------------------------------------


def test_salt_matches_tiktokdl_capture():
    """SALT comes from runtime_bundler_34.js; a change means Douyin
    pushed a new secsdk bundle."""
    assert SALT == "A96D855A08C0A9707F8BEF0D9A527E4E"


# ---------------------------------------------------------------------------
# WebSign canonical query encoding + sign()
# ---------------------------------------------------------------------------


def test_normalize_query_idempotent_on_websign_output():
    """TikTokDL invariant: normalising a WebSign-signed query must be
    a fixed point — re-running the encoder yields the same string."""
    query = (
        "aid=6383&device_platform=webapp&uifid=abc123&"
        "verifyFp=test&timestamp=1234567890&x-secsdk-web-signature=deadbeef"
    )
    once = normalize_query(query)
    twice = normalize_query(once)
    assert once == twice, (
        f"normalize_query must be idempotent — TikTokDL's encoding is "
        f"a fixed point. once={once!r} twice={twice!r}"
    )


def test_sign_produces_known_md5_vector():
    """M6.48 critical pinning vector — drift = silent 403 in production.

    Fixed input (uifid=test12345678, timestamp=1234567890, query as
    below) → fixed signature. If this fails, either SALT rotated,
    canonical encoding drifted, or webapi's WebSign no longer matches
    Douyin's server.
    """
    query = (
        "aid=6383&device_platform=webapp&uifid=test12345678"
        "&verifyFp=test"
    )
    signed, sig = websign_sign(query, "test12345678", timestamp=1234567890)
    assert signed.endswith(f"&x-secsdk-web-signature={sig}")
    # The exact MD5 — pinning any drift
    assert sig == "a39b52f20615d3876f8bf4187479a2be"
    # Signed query must carry timestamp + signature
    assert "&timestamp=1234567890" in signed
    assert "&uifid=test12345678" in signed


def test_sign_appends_uifid_when_missing():
    """sign() must append uifid if not already in query (M6.48 behaviour)."""
    query = "aid=6383&device_platform=webapp"  # no uifid
    signed, _ = websign_sign(query, "filler_uid", timestamp=1700000000)
    assert "&uifid=filler_uid" in signed


def test_sign_empty_uifid_raises():
    """Empty uifid must raise — caller must fill it in first; do not
    silently produce a signature the platform rejects."""
    with pytest.raises(ValueError, match="uifid must be a non-empty string"):
        websign_sign("aid=6383", "", timestamp=1234567890)


# ---------------------------------------------------------------------------
# MsTokenFetcher — best-effort, soft-fail
# ---------------------------------------------------------------------------


class _FakeTransport(httpx.AsyncBaseTransport):
    """Minimal async transport for testing httpx clients without network."""

    def __init__(self, response: httpx.Response):
        self._response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._response


def _build_client(transport: httpx.AsyncBaseTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, timeout=5.0)


@pytest.mark.asyncio
async def test_mstoken_fetch_returns_none_on_http_error(monkeypatch):
    """Network failure -> returns None, never raises."""
    fetcher = MsTokenFetcher(timeout=5.0)
    # Patch httpx.AsyncClient to raise
    class _BoomClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise httpx.ConnectError(
                "DNS lookup failed",
                request=httpx.Request(
                    "POST", "https://mssdk.bytedance.com/web/common",
                ),
            )
    monkeypatch.setattr("httpx.AsyncClient", _BoomClient)
    token = await fetcher.fetch()
    assert token is None
    assert fetcher.cached is None


@pytest.mark.asyncio
async def test_mstoken_fetch_returns_none_on_non_200(monkeypatch):
    """Non-200 -> returns None, does not write cache."""
    fetcher = MsTokenFetcher(timeout=5.0)
    resp = httpx.Response(503, text="service unavailable")
    async with _build_client(_FakeTransport(resp)) as client:
        class _StubFactory:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return client

            async def __aexit__(self, *a):
                return False
        import doubi.platforms.douyin.sign.ms_token as ms_mod
        original = ms_mod.httpx.AsyncClient
        ms_mod.httpx.AsyncClient = _StubFactory
        try:
            token = await fetcher.fetch()
        finally:
            ms_mod.httpx.AsyncClient = original
    assert token is None
    assert fetcher.cached is None


@pytest.mark.asyncio
async def test_mstoken_fetch_parses_set_cookie_and_caches(monkeypatch):
    """Normal 200 + Set-Cookie with msToken -> returns parsed value + cache."""
    fetcher = MsTokenFetcher(timeout=5.0)
    resp = httpx.Response(
        200,
        headers={
            "Set-Cookie": "msToken=abcDEF123_realToken; Path=/; Domain=.bytedance.com",
            "Content-Type": "application/json",
        },
    )
    async with _build_client(_FakeTransport(resp)) as client:
        class _StubFactory:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return client

            async def __aexit__(self, *a):
                return False
        import doubi.platforms.douyin.sign.ms_token as ms_mod
        original = ms_mod.httpx.AsyncClient
        ms_mod.httpx.AsyncClient = _StubFactory
        try:
            token = await fetcher.fetch()
        finally:
            ms_mod.httpx.AsyncClient = original
    assert token == "abcDEF123_realToken"
    assert fetcher.cached == "abcDEF123_realToken"


@pytest.mark.asyncio
async def test_mstoken_fetch_returns_none_on_200_without_set_cookie(monkeypatch):
    """200 OK but Set-Cookie lacks msToken -> returns None."""
    fetcher = MsTokenFetcher(timeout=5.0)
    resp = httpx.Response(
        200,
        headers={"Set-Cookie": "other_cookie=foo; Path=/"},
    )
    async with _build_client(_FakeTransport(resp)) as client:
        class _StubFactory:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return client

            async def __aexit__(self, *a):
                return False
        import doubi.platforms.douyin.sign.ms_token as ms_mod
        original = ms_mod.httpx.AsyncClient
        ms_mod.httpx.AsyncClient = _StubFactory
        try:
            token = await fetcher.fetch()
        finally:
            ms_mod.httpx.AsyncClient = original
    assert token is None
    assert fetcher.cached is None


def test_mstoken_fetcher_invalidate_clears_cache():
    """invalidate() must clear cached value."""
    fetcher = MsTokenFetcher(timeout=5.0)
    fetcher._cached = "fake"
    fetcher.invalidate()
    assert fetcher.cached is None


# ---------------------------------------------------------------------------
# TtWidFetcher — same pattern, key name differs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ttwid_fetch_parses_set_cookie_and_caches(monkeypatch):
    fetcher = TtWidFetcher(timeout=5.0)
    resp = httpx.Response(
        200,
        headers={
            "Set-Cookie": "ttwid=tt_wid_value_xyz; Path=/; Domain=.bytedance.com",
        },
    )
    async with _build_client(_FakeTransport(resp)) as client:
        class _StubFactory:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return client

            async def __aexit__(self, *a):
                return False
        import doubi.platforms.douyin.sign.tt_wid as tt_mod
        original = tt_mod.httpx.AsyncClient
        tt_mod.httpx.AsyncClient = _StubFactory
        try:
            token = await fetcher.fetch()
        finally:
            tt_mod.httpx.AsyncClient = original
    assert token == "tt_wid_value_xyz"
    assert fetcher.cached == "tt_wid_value_xyz"


@pytest.mark.asyncio
async def test_ttwid_fetch_returns_none_on_http_error(monkeypatch):
    fetcher = TtWidFetcher(timeout=5.0)

    class _BoomClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise httpx.ConnectError(
                "boom",
                request=httpx.Request(
                    "POST", "https://ttwid.bytedance.com/",
                ),
            )
    monkeypatch.setattr("httpx.AsyncClient", _BoomClient)
    token = await fetcher.fetch()
    assert token is None


def test_ttwid_fetcher_invalidate_clears_cache():
    fetcher = TtWidFetcher(timeout=5.0)
    fetcher._cached = "fake"
    fetcher.invalidate()
    assert fetcher.cached is None


# ---------------------------------------------------------------------------
# DouyinWebAPI integration — M6.48 stable uifid + cookie injection
# ---------------------------------------------------------------------------


def test_webapi_uifid_is_stable_per_session_16_hex():
    """_uifid must be 16 hex chars (UUID4 hex truncated); instances differ."""
    api1 = DouyinWebAPI()
    api2 = DouyinWebAPI()
    assert len(api1._uifid) == 16
    assert all(c in "0123456789abcdef" for c in api1._uifid)
    assert api1._uifid != api2._uifid


def test_webapi_signed_url_appends_websign_for_protected_path():
    """Protected endpoint -> signed URL must end with x-secsdk-web-signature."""
    api = DouyinWebAPI()
    api._uifid = "abcdef0123456789"
    url = api._signed_url(
        "/aweme/v1/web/mix/aweme/",
        {"device_platform": "webapp", "aid": "6383",
         "msToken": "fakems", "uifid": api._uifid},
    )
    assert "x-secsdk-web-signature=" in url
    assert "timestamp=" in url


def test_webapi_signed_url_skips_websign_for_unprotected_path():
    """Unprotected endpoint -> URL must NOT carry WebSign (no waste CPU)."""
    api = DouyinWebAPI()
    api._uifid = "abcdef0123456789"
    url = api._signed_url(
        "/aweme/v1/web/some/unprotected/",
        {"device_platform": "webapp", "aid": "6383",
         "msToken": "fakems", "uifid": api._uifid},
    )
    assert "x-secsdk-web-signature=" not in url


def test_webapi_invalidate_tokens_resets_cached():
    api = DouyinWebAPI()
    api._ms_token_fetcher._cached = "old"
    api._tt_wid_fetcher._cached = "old"
    api._tokens_ready = True
    api.invalidate_tokens()
    assert api._ms_token_fetcher.cached is None
    assert api._tt_wid_fetcher.cached is None
    assert api._tokens_ready is False


@pytest.mark.asyncio
async def test_webapi_ensure_tokens_idempotent(monkeypatch):
    """_ensure_tokens() called multiple times -> only first call hits the
    network, subsequent calls return immediately.

    Pre-condition: cookies must NOT have msToken/ttwid already (dev
    environment usually doesn't but explicit clear avoids CI flake).
    """
    api = DouyinWebAPI()
    api.cookies.pop("msToken", None)
    api.cookies.pop("ttwid", None)
    call_count = {"n": 0}

    async def _stub_fetch(self, **kwargs):
        call_count["n"] += 1
        self._cached = f"ms_{call_count['n']}"
        return self._cached

    monkeypatch.setattr(MsTokenFetcher, "fetch", _stub_fetch)

    async def _stub_tt(self, **kwargs):
        call_count["n"] += 1
        self._cached = f"tt_{call_count['n']}"
        return self._cached

    monkeypatch.setattr(TtWidFetcher, "fetch", _stub_tt)

    await api._ensure_tokens()
    await api._ensure_tokens()
    await api._ensure_tokens()
    assert call_count["n"] == 2, (
        f"_ensure_tokens must call each fetcher exactly once across 3 calls; "
        f"got {call_count['n']} (1 expected per fetcher, 2 total)"
    )


# ---------------------------------------------------------------------------
# M6.53 — Survey §8.1 item #6. Real strData blob + TOKEN installation.
# ---------------------------------------------------------------------------
#
# TikTokDL extracts ``strData`` from ``runtime_bundler_34.js`` (the
# encrypted device-fingerprint blob mssdk validates server-side). M6.48
# shipped the fetch plumbing with ``strData=""`` placeholder; M6.53
# installs the real blob as a module-level constant and points the
# fetcher default at it.
#
# Tests below pin the blob + TOKEN so any unintended modification shows
# up as a test failure (rolling the blob should be a deliberate decision
# tied to a 抖音 ``runtime_bundler`` rotation, not a typo).


def test_mstoken_default_strdata_is_populated():
    """``_MSSDK_STRDATA`` must be a non-empty base64 blob (~3.5 KB
    decoded ~3 KB raw). Before M6.53 this was ``""`` and mssdk
    rejected the empty payload server-side."""
    assert isinstance(_MSSDK_STRDATA, str)
    assert len(_MSSDK_STRDATA) > 3000, (
        f"strData blob looks too small ({len(_MSSDK_STRDATA)} chars); "
        "TikTokDL's extract is ~4036 chars"
    )
    # base64 alphabet
    import re as _re
    assert _re.fullmatch(r"[A-Za-z0-9+/=]+", _MSSDK_STRDATA), (
        "strData must be base64 (M6.48 placeholder was plain empty)"
    )


def test_mstoken_default_token_is_populated():
    """``_MSSDK_DEFAULT_TOKEN`` must be a non-empty base64 string.
    Before M6.53 this was ``""``."""
    assert isinstance(_MSSDK_DEFAULT_TOKEN, str)
    assert len(_MSSDK_DEFAULT_TOKEN) > 80, (
        f"TOKEN looks too small ({len(_MSSDK_DEFAULT_TOKEN)} chars); "
        "TikTokDL's extract is 128 chars"
    )
    import re as _re
    assert _re.fullmatch(r"[A-Za-z0-9_=-]+", _MSSDK_DEFAULT_TOKEN)


def test_mstoken_fetcher_default_picks_up_real_blob():
    """``MsTokenFetcher()`` with no overrides must auto-load the real
    blob (Survey §8.1 item #6). The blob+token are large + non-empty."""
    fetcher = MsTokenFetcher(timeout=5.0)
    assert fetcher._str_data_override == _MSSDK_STRDATA
    assert fetcher._token_override == _MSSDK_DEFAULT_TOKEN
    # Sanity: blob isn't the old empty-string placeholder
    assert fetcher._str_data_override != ""
    assert fetcher._token_override != ""


def test_mstoken_fetcher_explicit_str_data_overrides_default():
    """Explicit ``str_data=...`` (incl. ``""`` to force empty) wins
    over the module default — tests can still inject sentinel values."""
    fetcher_custom = MsTokenFetcher(timeout=5.0, str_data="custom_blob")
    assert fetcher_custom._str_data_override == "custom_blob"

    fetcher_empty = MsTokenFetcher(timeout=5.0, str_data="")
    assert fetcher_empty._str_data_override == ""  # forces empty


def test_mstoken_fetcher_explicit_default_token_overrides():
    """Same for ``default_token``."""
    fetcher = MsTokenFetcher(timeout=5.0, default_token="custom_tok")
    assert fetcher._token_override == "custom_tok"


def test_mstoken_strdata_pinned_to_tiktokdl_extract():
    """Pin the blob's exact length + first/last segments against
    TikTokDL ``src/encrypt/msToken.py:30-71``. If 抖音 rotates
    ``runtime_bundler_*.js`` the blob must be re-captured and this
    pin updated deliberately (not by accident).

    Prefix + suffix pin (not full hash) keeps the test readable while
    still detecting rotation / corruption.
    """
    # TikTokDL capture: 4036 chars base64
    assert len(_MSSDK_STRDATA) == 4036, (
        f"strData length drifted ({len(_MSSDK_STRDATA)} chars, expected 4036). "
        "This means the blob needs re-capture from a fresh mssdk extract."
    )
    # First 32 chars from TikTokDL line 30
    assert _MSSDK_STRDATA.startswith(
        "fWOdJTQR3/jwmZqBBsPO6tdNEc1jX7"
    ), "strData prefix drift"
    # Last 32 chars from TikTokDL line 71
    assert _MSSDK_STRDATA.endswith(
        "TS2BGfsHadR3d5j8lNhBPzA5e+mE=="
    ), "strData suffix drift"


def test_mstoken_token_pinned_to_tiktokdl_extract():
    """Pin the TOKEN against TikTokDL ``src/encrypt/msToken.py:75-78``."""
    assert len(_MSSDK_DEFAULT_TOKEN) == 128, (
        f"TOKEN length drifted ({len(_MSSDK_DEFAULT_TOKEN)}, expected 128)"
    )
    # TikTokDL line 76-77 (concatenated)
    assert _MSSDK_DEFAULT_TOKEN.startswith("9cguMjz4GIfQV50B_D49quM")
    assert _MSSDK_DEFAULT_TOKEN.endswith("KDrc5H9nfN3pLw=")


# ---------------------------------------------------------------------------
# P3-2：签名白名单与真实请求的偏离守卫
# ---------------------------------------------------------------------------
#
# ROADMAP P3-2 的诉求：任何被真正调用的抖音 web API 端点，如果在
# DOUYIN_SIGNED_PATHS 里缺席，应当在测试阶段就失败，而不是等到线上
# 收到 403 才发现「少签了一个路径」。
#
# 这里用 AST 静态扫描而不是人工维护的第二份清单——人工清单本身就会
# 和代码一起漂移，正是要防的东西。扫描范围是抖音包内所有模块里出现的
# 字面量 /aweme/v1/web/... 路径。

import ast  # noqa: E402

_DOUYIN_PKG = SRC / "doubi" / "platforms" / "douyin"


def _literal_web_api_paths() -> dict[str, set[str]]:
    """Return ``{path: {files that mention it}}`` for every literal path.

    Only string literals matching ``/aweme/v1/web/`` are collected. Paths
    assembled at runtime from f-strings would not be caught — but the
    codebase currently uses literals exclusively at call sites.
    """
    found: dict[str, set[str]] = {}
    for py in sorted(_DOUYIN_PKG.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — 语法错误另有测试兜住
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("/aweme/v1/web/"):
                    found.setdefault(node.value, set()).add(py.name)
    return found


def test_every_used_web_api_path_is_whitelisted():
    """每个被调用的端点都必须在 DOUYIN_SIGNED_PATHS 里。

    不过签名的后果不对称：漏签在受保护端点上直接 403（功能不可用），
    多签只是多算一个哈希（无害，TikTokDL 明确记录过这一点）。因此这条
    断言的正确方向是「调用即需在白名单」，而不是反过来。
    """
    used = _literal_web_api_paths()
    assert used, "AST 扫描没找到任何 /aweme/v1/web/ 路径，扫描逻辑本身失效了"

    missing = {p: sorted(f) for p, f in used.items() if p not in DOUYIN_SIGNED_PATHS}
    assert not missing, (
        "以下端点被真实调用但不在 DOUYIN_SIGNED_PATHS 里，会导致 403：\n"
        + "\n".join(f"  {p}  (出现在 {', '.join(files)})" for p, files in sorted(missing.items()))
        + "\n\n修法：把路径加进 sign/websign.py 的 DOUYIN_SIGNED_PATHS（over-signing 无害）。"
    )


def test_signed_paths_drift_is_surfaced_for_review():
    """反向检查：白名单里当前未被调用的路径应可见，便于定期复核。

    这条**只提示不失败**——白名单来源是平台 secsdk 的 protectedHost 表，
    平台的受保护集合本就可能比 DouBi 当前用到的更大（预留项是有意的，
    例如 M6.50 的 Collects 家族在 M6.48 就已登记）。断言相等反而会制造
    假失败，因此这里只把差集打印出来。
    """
    used = set(_literal_web_api_paths())
    stale = sorted(DOUYIN_SIGNED_PATHS - used)
    # 预留项存在是正常的；给出可读清单便于人工复核，不设为失败条件。
    print(f"\n[P3-2] 白名单共 {len(DOUYIN_SIGNED_PATHS)} 条，"
          f"当前被调用 {len(used)} 条，未调用（多为有意预留）{len(stale)} 条：")
    for path in stale:
        print(f"    {path}")
