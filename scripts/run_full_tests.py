"""一次跑完全量测试的三个口径（0.3.1 新增）。

**背景**：本地裸跑 `python -m pytest` 会挂住，这个现象长期被当成「全量跑不动」，
于是发版前的回归数字一直靠 CHANGELOG 分批累加推算——0.3.1 的「901 passed /
3 skipped」就是这么来的，实测对不上（真值 913 / 7）。

真正的根因只有一个文件：`tests/test_theme_apply_gui.py`（28 例，`gui` + `slow`）
带真 PySide6 时会起 Qt 事件循环反复切主题，单跑就能把整轮拖挂。把它排除掉，
948 收集里的另外 920 条**约 3 分钟**就跑完了。

三个口径：

``local``（默认）
    本地装齐 extras，排除 `test_theme_apply_gui.py`。
    0.3.1 基线：**913 passed / 7 skipped**，164.67s / 181.81s 两次实测
    （948 收集 − 28 排除 = 920）。
    用途：发版前拿准确回归数字，写进 CHANGELOG / Release 正文。

``ci``
    往 `sys.meta_path` 插一个 Blocker 屏蔽 9 个可选依赖，复刻 CI 的
    `pytest -q --maxfail=5`（CI 只跑 `pip install .`，不带任何 extras）。
    0.3.1 基线：**670 passed / 175 skipped / 96.90s**。
    用途：`docs/BUILD.md` §7 那条「模拟 CI 依赖集跑一遍全量」检查——本地装齐
    extras 的口径比 CI **大一圈**，「测试里裸导入可选依赖」这类失效模式在本地
    必然漏过去（M6.21 血的教训，见 DEVELOPMENT §15.1）。

    注意报告总数：670 + 175 = 845 < local 口径的 920。这**不是**丢用例——
    模块级 `pytest.importorskip` 失败会把整份测试文件折叠成 **1 条 skip**，
    所以屏蔽依赖后总数必然变小。判绿标准是「passed + failed 与 CI 相等、
    skipped 也相等」，不是「没红」。

``gui-slow``
    只跑 `test_theme_apply_gui.py`。**已知会长时间挂住、可能跑不完**，
    仅在动过 `ui/theme.py` 时手工付这个代价。

用法（PowerShell）::

    python scripts/run_full_tests.py                       # local
    python scripts/run_full_tests.py --mode ci
    python scripts/run_full_tests.py --mode ci 2>&1 | Tee-Object .scratch\\ci.log
    python scripts/run_full_tests.py -k tray               # 未识别参数原样透传给 pytest

退出码即 pytest 退出码，可直接用于脚本判绿。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# CI 只跑 `pip install .`，这 9 个包全在 pyproject.toml 的
# [project.optional-dependencies]（gui / server / mcp 三组），runner 上一律不存在。
CI_ABSENT: tuple[str, ...] = (
    "pydantic",
    "fastapi",
    "uvicorn",
    "PySide6",
    "qfluentwidgets",
    "qasync",
    "psutil",
    "qrcode",
    "mcp",
)

# 带真 PySide6 会起 Qt 事件循环反复切主题，是「全量跑不动」的唯一根因。
SLOW_GUI_FILE = "tests/test_theme_apply_gui.py"


class _Blocker:
    """meta_path finder：对指定顶层包直接抛 ModuleNotFoundError。

    返回 None 表示「不管这个模块」，交给后面的 finder；抛 ModuleNotFoundError
    才能让 `pytest.importorskip` / `try: import` 走到缺包分支。
    """

    def __init__(self, blocked: tuple[str, ...]) -> None:
        self._blocked = set(blocked)

    def find_spec(self, fullname: str, path=None, target=None):  # noqa: ANN001
        if fullname.split(".", 1)[0] in self._blocked:
            raise ModuleNotFoundError(f"[ci-sim] blocked: {fullname}")
        return None


def _install_blocker(names: tuple[str, ...]) -> None:
    # 先清掉已经进 sys.modules 的同名模块，否则 import 直接命中缓存绕过 finder。
    for name in list(sys.modules):
        if name.split(".", 1)[0] in names:
            del sys.modules[name]
    sys.meta_path.insert(0, _Blocker(names))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="按指定口径跑全量测试；未识别的参数原样透传给 pytest。",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "ci", "gui-slow"),
        default="local",
        help="local=装齐 extras 排除 slow GUI（默认）；ci=屏蔽可选依赖复刻 CI；"
        "gui-slow=只跑 test_theme_apply_gui.py（会挂）",
    )
    args, passthrough = parser.parse_known_args()

    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT / "src"))
    # 无头跑 GUI 测试的前提；已显式设过就不覆盖。
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # 提示语用英文：中文在 cp936 控制台 + 管道下会乱码（实测「ֻ��」），
    # 而这个脚本的日志经常要 Tee-Object 存下来对照。
    if args.mode == "ci":
        _install_blocker(CI_ABSENT)
        argv = ["-q", "--maxfail=5"]
        print(f"[run_full_tests] mode=ci: blocking {len(CI_ABSENT)} optional deps, "
              f"mirroring CI command `pytest -q --maxfail=5`")
        print("[run_full_tests] 0.3.1 baseline: 670 passed / 175 skipped / ~102s")
    elif args.mode == "local":
        argv = ["-q", f"--ignore={SLOW_GUI_FILE}"]
        print(f"[run_full_tests] mode=local: excluding {SLOW_GUI_FILE}")
        print("[run_full_tests] 0.3.1 baseline: 913 passed / 7 skipped / ~165-185s")
    else:
        argv = ["-q", SLOW_GUI_FILE]
        print(f"[run_full_tests] mode=gui-slow: running {SLOW_GUI_FILE} only")
        print("[run_full_tests] WARNING: known to hang for a long time; Ctrl-C to abort")

    argv.extend(passthrough)
    sys.stdout.flush()

    import pytest  # 延后导入：ci 模式必须先装好 Blocker

    return pytest.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
