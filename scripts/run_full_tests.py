"""一次跑完全量测试的两个口径（0.3.1 新增）。

**背景**：本地裸跑 `python -m pytest` 会挂住，这个现象长期被当成「全量跑不动」，
于是发版前的回归数字一直靠 CHANGELOG 分批累加推算——0.3.1 的「901 passed /
3 skipped」就是这么来的，实测对不上（真值 913 / 7）。

真正的根因只有一个文件：`tests/test_theme_apply_gui.py`（28 例，`gui` + `slow`）
带真 PySide6 时会起 Qt 事件循环反复切主题，单跑就能把整轮拖挂。把它排除掉，
948 收集里的另外 920 条**约 3 分钟**就跑完了。

两个口径（0.3.1 起曾有第三个 ``ci`` 口径，用于复刻 CI runner 的最小依赖集；
CI 已于 2026-11 整体移除，该口径随之删除——历史基线见 CHANGELOG 各版本段）：

``local``（默认）
    本地装齐 extras，排除 `test_theme_apply_gui.py`。
    0.3.1 基线：**913 passed / 7 skipped**，164.67s / 181.81s 两次实测
    （948 收集 − 28 排除 = 920）。
    用途：发版前拿准确回归数字，写进 CHANGELOG / Release 正文。

``gui-slow``
    只跑 `test_theme_apply_gui.py`。**已知会长时间挂住、可能跑不完**，
    仅在动过 `ui/theme.py` 时手工付这个代价。

用法（PowerShell）::

    python scripts/run_full_tests.py                       # local
    python scripts/run_full_tests.py -k tray               # 未识别参数原样透传给 pytest

退出码即 pytest 退出码，可直接用于脚本判绿。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 带真 PySide6 会起 Qt 事件循环反复切主题，是「全量跑不动」的唯一根因。
SLOW_GUI_FILE = "tests/test_theme_apply_gui.py"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="按指定口径跑全量测试；未识别的参数原样透传给 pytest。",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "gui-slow"),
        default="local",
        help="local=装齐 extras 排除 slow GUI（默认）；"
        "gui-slow=只跑 test_theme_apply_gui.py（会挂）",
    )
    args, passthrough = parser.parse_known_args()

    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT / "src"))
    # 无头跑 GUI 测试的前提；已显式设过就不覆盖。
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # 提示语用英文：中文在 cp936 控制台 + 管道下会乱码（实测「ֻ��」），
    # 而这个脚本的日志经常要 Tee-Object 存下来对照。
    if args.mode == "local":
        argv = ["-q", f"--ignore={SLOW_GUI_FILE}"]
        print(f"[run_full_tests] mode=local: excluding {SLOW_GUI_FILE}")
        print("[run_full_tests] 0.3.4 baseline: 1298 passed / 7 skipped / ~95s "
              "(0.3.3 was 1269/7, 0.3.2 was 1243/7)")
        print("[run_full_tests] 0.3.3 baseline: 1269 passed / 7 skipped / ~87s "
              "(0.3.2 was 1243/7, 0.3.1 was 913/7)")
    else:
        argv = ["-q", SLOW_GUI_FILE]
        print(f"[run_full_tests] mode=gui-slow: running {SLOW_GUI_FILE} only")
        print("[run_full_tests] WARNING: known to hang for a long time; Ctrl-C to abort")

    argv.extend(passthrough)
    sys.stdout.flush()

    import pytest

    return pytest.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
