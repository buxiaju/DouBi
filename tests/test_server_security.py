"""REST 鉴权与监听地址审查的测试。

分成两段：

* 前半段只碰 :mod:`doubi.server.security`，不依赖 fastapi——安全判断不该
  因为可选依赖缺失就失去测试覆盖。
* 后半段用 ``TestClient`` 打真实路由，验证「配了 token 就必须带对 token」
  这条端到端契约。

判据取向：断言的是**不变量**（能被外部连上的端口必须有鉴权、比较必须是
常数时间函数、拿不准的主机名倒向要求鉴权），而不是某条具体文案。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.server import security  # noqa: E402
from doubi.server.security import (  # noqa: E402
    TOKEN_ENV_VAR,
    InsecureBindingError,
    audit_binding,
    extract_request_token,
    generate_token,
    is_loopback,
    resolve_token,
    token_matches,
)


# ---------------------------------------------------------------------------
# is_loopback —— 审查的地基。判错方向就等于安全模型失效。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", [
    "127.0.0.1",
    "127.0.0.2",       # 整个 127/8 都是本机
    "localhost",
    "LocalHost",       # 主机名大小写不敏感
    "::1",
    "[::1]",           # 命令行里常见的方括号写法
    "::1%lo0",         # 带 scope id
    " 127.0.0.1 ",     # 复制粘贴带来的空白
])
def test_loopback_addresses_are_recognized(host):
    assert is_loopback(host) is True


@pytest.mark.parametrize("host", [
    "0.0.0.0",         # 全部网卡
    "::",              # 全部网卡（v6）
    "192.168.1.10",
    "10.0.0.5",        # 内网也是「别的机器能连」
    "203.0.113.7",
    "",                # uvicorn 把空 host 当作监听全部网卡
    None,
    "example.com",
    "my-nas.local",
])
def test_non_loopback_addresses_are_treated_as_exposed(host):
    assert is_loopback(host) is False


def test_unresolvable_hostname_fails_towards_requiring_auth():
    """拿不准的输入必须倒向「要求鉴权」。

    这里刻意用一个既非 IP 字面量、也不做 DNS 解析的名字。若实现改成去查
    DNS，同一份配置在两台机器上可能得出不同的安全结论——安全审查的结果
    不确定本身就不可接受。
    """
    assert is_loopback("definitely-not-a-real-host-zzz") is False
    with pytest.raises(InsecureBindingError):
        audit_binding("definitely-not-a-real-host-zzz", token=None)


# ---------------------------------------------------------------------------
# resolve_token —— 空串必须当作「没有」，否则鉴权会静默全放行。
# ---------------------------------------------------------------------------


def test_explicit_token_wins_over_env(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "from-env")
    assert resolve_token("explicit") == "explicit"


def test_token_falls_back_to_env(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "from-env")
    assert resolve_token(None) == "from-env"


def test_no_token_anywhere_is_none(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    assert resolve_token(None) is None


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_token_is_not_a_token(monkeypatch, blank):
    """``DOUBI_API_TOKEN=`` 这种写法不能被当成一个长度为 0 的合法 token。

    若当成合法值，token_matches 会对任何请求都成立，鉴权表面上开着、
    实际全放行——最危险的那类失败。
    """
    monkeypatch.setenv(TOKEN_ENV_VAR, blank)
    assert resolve_token(None) is None
    assert resolve_token(blank) is None


def test_token_is_stripped(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "  padded  ")
    assert resolve_token(None) == "padded"


def test_generated_tokens_are_unique_and_long_enough():
    a, b = generate_token(), generate_token()
    assert a != b
    # 32 字节 urlsafe base64 ≈ 43 字符；给下限留点余量即可。
    assert len(a) >= 32


# ---------------------------------------------------------------------------
# token_matches
# ---------------------------------------------------------------------------


def test_matching_token_passes():
    assert token_matches("s3cret", "s3cret") is True


@pytest.mark.parametrize("provided", ["wrong", "s3cre", "s3secret", "", None])
def test_mismatched_token_fails(provided):
    assert token_matches("s3cret", provided) is False


def test_no_expected_token_never_matches():
    """没配 token 时不能变成「任何 token 都算对」。

    是否放行由调用方判断（build_app 里 expected is None 直接 return），
    这个纯函数自己必须给出 False。
    """
    assert token_matches(None, "anything") is False
    assert token_matches("", "anything") is False


def test_comparison_uses_a_constant_time_primitive():
    """``==`` 会在首个不同字节处提前返回，泄露「猜对了几位前缀」。

    直接断言实现调用了 :func:`secrets.compare_digest`：计时行为无法稳定
    地在单测里测出来，但「用了哪个原语」可以。
    """
    calls = []
    original = security.secrets.compare_digest

    def _spy(a, b):
        calls.append((a, b))
        return original(a, b)

    security.secrets.compare_digest = _spy
    try:
        token_matches("s3cret", "s3cret")
    finally:
        security.secrets.compare_digest = original
    assert calls, "token_matches 必须走 secrets.compare_digest，不能用 =="


# ---------------------------------------------------------------------------
# extract_request_token
# ---------------------------------------------------------------------------


def test_bearer_header_is_parsed():
    assert extract_request_token({"authorization": "Bearer abc123"}) == "abc123"


def test_bearer_scheme_is_case_insensitive():
    """RFC 6750 规定 scheme 大小写不敏感。"""
    assert extract_request_token({"authorization": "bearer abc"}) == "abc"
    assert extract_request_token({"authorization": "BEARER abc"}) == "abc"


def test_x_api_token_header_is_supported():
    assert extract_request_token({"x-api-token": "abc"}) == "abc"


def test_header_lookup_tolerates_original_casing():
    assert extract_request_token({"Authorization": "Bearer abc"}) == "abc"
    assert extract_request_token({"X-API-Token": "abc"}) == "abc"


@pytest.mark.parametrize("headers", [
    {},
    {"authorization": ""},
    {"authorization": "Bearer"},        # 有 scheme 没值
    {"authorization": "Bearer    "},
    {"authorization": "Basic dXNlcjpwdw=="},  # 不是我们支持的方案
    {"x-api-token": "   "},
])
def test_absent_or_unusable_token_is_none(headers):
    assert extract_request_token(headers) is None


def test_query_string_is_not_a_token_source():
    """凭据不从 URL 取。

    query string 会被 access log、反向代理日志、浏览器历史记下来，等于
    长期泄露。这里断言的是「即使调用方把它塞进类 header 的映射，也不会
    被当成 token」这一实现取向。
    """
    assert extract_request_token({"token": "abc", "api_token": "abc"}) is None


# ---------------------------------------------------------------------------
# audit_binding —— 核心不变量：对外可达的端口必须有鉴权。
# ---------------------------------------------------------------------------


def test_loopback_without_token_is_allowed_silently():
    """单机自用不该被迫填 token，也不该被警告刷屏。"""
    assert audit_binding("127.0.0.1", token=None) is None


def test_loopback_with_token_is_also_silent():
    assert audit_binding("127.0.0.1", token="s3cret") is None


@pytest.mark.parametrize("host", ["0.0.0.0", "", None, "192.168.1.10", "::"])
def test_exposed_binding_without_token_is_refused(host):
    with pytest.raises(InsecureBindingError):
        audit_binding(host, token=None)


def test_refusal_message_tells_the_user_how_to_fix_it():
    """报错必须可行动——三条出路都要给到，否则用户只会去加 --allow-insecure。"""
    with pytest.raises(InsecureBindingError) as ei:
        audit_binding("0.0.0.0", token=None)
    msg = str(ei.value)
    assert "127.0.0.1" in msg          # 出路 1：绑回环
    assert TOKEN_ENV_VAR in msg        # 出路 2：配 token
    assert "--allow-insecure" in msg   # 出路 3：明知风险
    assert "0.0.0.0" in msg            # 说清是哪个地址触发的


def test_exposed_binding_with_token_warns_but_proceeds():
    warning = audit_binding("0.0.0.0", token="s3cret")
    assert warning
    assert "0.0.0.0" in warning


def test_allow_insecure_downgrades_refusal_to_warning():
    warning = audit_binding("0.0.0.0", token=None, allow_insecure=True)
    assert warning
    assert "--allow-insecure" in warning


def test_allow_insecure_does_not_silence_the_warning():
    """显式豁免只解除拦截，不解除告警：裸奔状态必须一直看得见。"""
    assert audit_binding("0.0.0.0", token=None, allow_insecure=True) is not None


def test_allow_insecure_is_irrelevant_for_loopback():
    """回环本来就没问题，不该因为传了危险开关而产生噪音。"""
    assert audit_binding("127.0.0.1", token=None, allow_insecure=True) is None


# ---------------------------------------------------------------------------
# 端到端：真实路由 + TestClient
# ---------------------------------------------------------------------------

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from doubi.server.app import build_app  # noqa: E402

#: 受保护的 GET 路由。POST /download 单独测，因为它要带 body。
_PROTECTED_GETS = ["/api/v1/platforms", "/api/v1/jobs", "/api/v1/jobs/whatever"]


@pytest.fixture
def secure_client(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    return TestClient(build_app(token="s3cret"))


@pytest.fixture
def open_client(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    return TestClient(build_app())


def test_auth_disabled_by_default(open_client):
    """没配 token → 不鉴权。既有的本机用法与测试不受影响。"""
    assert open_client.app.state.auth_enabled is False
    assert open_client.get("/api/v1/platforms").status_code == 200


def test_env_var_alone_turns_auth_on(monkeypatch):
    """不传参数、只设环境变量也要生效——容器部署基本只有这条路。"""
    monkeypatch.setenv(TOKEN_ENV_VAR, "env-token")
    client = TestClient(build_app())
    assert client.app.state.auth_enabled is True
    assert client.get("/api/v1/platforms").status_code == 401
    r = client.get("/api/v1/platforms", headers={"Authorization": "Bearer env-token"})
    assert r.status_code == 200


@pytest.mark.parametrize("path", _PROTECTED_GETS)
def test_protected_routes_reject_missing_token(secure_client, path):
    assert secure_client.get(path).status_code == 401


@pytest.mark.parametrize("path", _PROTECTED_GETS)
def test_protected_routes_reject_wrong_token(secure_client, path):
    r = secure_client.get(path, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/platforms", "/api/v1/jobs"])
def test_protected_routes_accept_bearer_token(secure_client, path):
    r = secure_client.get(path, headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/platforms", "/api/v1/jobs"])
def test_protected_routes_accept_x_api_token(secure_client, path):
    r = secure_client.get(path, headers={"X-API-Token": "s3cret"})
    assert r.status_code == 200


def test_unknown_job_still_404s_when_authenticated(secure_client):
    """鉴权通过后语义必须回归原样，不能把 404 也吞成 401。"""
    r = secure_client.get("/api/v1/jobs/does-not-exist",
                          headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 404


def test_download_requires_token(secure_client):
    """最要紧的一条：无 token 不能驱动本机下载并写盘。"""
    r = secure_client.post("/api/v1/download", json={"url": "https://x/1"})
    assert r.status_code == 401


def test_download_rejects_wrong_token_before_touching_the_queue(secure_client):
    """401 必须发生在 submit 之前，否则未授权请求已经产生了副作用。"""
    r = secure_client.post("/api/v1/download", json={"url": "https://x/1"},
                           headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    listed = secure_client.get("/api/v1/jobs",
                               headers={"Authorization": "Bearer s3cret"}).json()
    assert listed["jobs"] == []


def test_download_accepts_valid_token(secure_client):
    async def _ok(url):
        return {"total": 1, "succeeded": 1, "failed": 0}
    secure_client.app.state.job_manager._executor = _ok

    r = secure_client.post("/api/v1/download", json={"url": "https://x/1"},
                           headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert "job_id" in r.json()


def test_health_stays_open_for_liveness_probes(secure_client):
    """编排系统的存活探针通常带不了凭据，而 /health 没有可滥用的能力。"""
    r = secure_client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_advertises_whether_auth_is_on(secure_client, open_client):
    """运维要能不翻启动参数就知道这个实例有没有开鉴权。"""
    assert secure_client.get("/api/v1/health").json()["auth_required"] is True
    assert open_client.get("/api/v1/health").json()["auth_required"] is False


def test_health_never_leaks_the_token(secure_client):
    body = secure_client.get("/api/v1/health").text
    assert "s3cret" not in body


def test_401_advertises_the_bearer_scheme(secure_client):
    """带 WWW-Authenticate，客户端才知道该用哪种方案重试。"""
    r = secure_client.get("/api/v1/platforms")
    assert r.status_code == 401
    assert "bearer" in r.headers.get("www-authenticate", "").lower()


def test_401_detail_does_not_distinguish_missing_from_wrong():
    """不要帮攻击者确认某个 token 是否存在。"""
    client = TestClient(build_app(token="s3cret"))
    missing = client.get("/api/v1/platforms").json()
    wrong = client.get("/api/v1/platforms",
                       headers={"Authorization": "Bearer nope"}).json()
    assert missing == wrong


def test_every_capability_route_is_protected(monkeypatch):
    """结构性守护：新增路由若忘了挂鉴权，这里会失败。

    做法是枚举 app 上真实注册的路由，而不是维护一张手写清单——手写清单
    的失效方式恰好是「加了新路由但没人想起来更新清单」。
    ``/health`` 与 FastAPI 自带的文档路由是有意的例外。
    """
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    app = build_app(token="s3cret")
    exempt = {"/api/v1/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

    unprotected = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None or path in exempt:
            continue
        deps = getattr(route, "dependant", None)
        names = []
        if deps is not None:
            names = [d.call.__name__ for d in deps.dependencies if d.call is not None]
        if "require_token" not in names:
            unprotected.append(path)

    assert not unprotected, f"这些路由没挂鉴权: {unprotected}"


def test_auth_guard_does_not_add_phantom_query_parameters(monkeypatch):
    """回归守护：鉴权闸门不能把 ``Request`` 变成一个必填 query 参数。

    这是一个真实踩过的坑，且它的失败方式极其安静——代码读起来完全正确，
    只有真的发一次请求才会暴露。

    成因是两个各自合理的决定相撞：``app.py`` 有
    ``from __future__ import annotations``（注解全变字符串），而 ``fastapi``
    必须懒导入（缺可选依赖时 ``import doubi.server`` 不能崩），于是 ``Request``
    只存在于 ``build_app()`` 的局部作用域。FastAPI 求值字符串注解时用的是
    ``get_type_hints(fn, fn.__globals__)``，只看模块全局——找不到 ``Request``，
    就把参数当成普通 query 参数处理，结果**所有**受保护路由一律返回 422，
    跟有没有带 token 完全无关。

    修法是把闸门放进 :mod:`doubi.server.deps`，那里 ``Request`` 是模块级名字。
    本测试直接检查 FastAPI 的解析结果，而不是只看某个状态码，这样即便未来
    换了写法，只要 ``Request`` 又变得不可解析就会立刻失败。
    """
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    app = build_app(token="s3cret")

    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for sub in dependant.dependencies:
            if sub.call is None or sub.call.__name__ != "require_token":
                continue
            # FastAPI 认出了请求对象 → 记在 request_param_name 上。
            assert sub.request_param_name == "request", (
                f"{route.path} 的鉴权闸门没被识别成请求对象；"
                "注解大概又变成不可求值的字符串了（见本测试 docstring）"
            )
            # 且绝不能把它当成待校验的输入参数。
            assert not sub.query_params, (
                f"{route.path} 的鉴权闸门产生了幽灵 query 参数: "
                f"{[p.name for p in sub.query_params]}"
            )


def test_protected_route_without_token_is_401_not_422(open_client, secure_client):
    """把上面那个结构性断言钉到用户可见的行为上。

    422 和 401 都是「请求失败」，但含义天差地别：422 说的是「你的参数写错了」，
    会把使用者引向去检查自己的调用代码，而真正的原因在服务端。分开断言两种
    客户端，是为了确认无 token 实例是真放行（200），有 token 实例是真拦截
    （401）——都不该出现 422。
    """
    assert open_client.get("/api/v1/platforms").status_code == 200
    assert secure_client.get("/api/v1/platforms").status_code == 401
