"""GUI 启动器（诊断用）：挂 faulthandler，把所有输出落盘。

用法：python scripts/_run_gui_debug.py
日志：.scratch/gui_debug.log（stdout/stderr 合流 + 崩溃时 native 栈）
"""
import faulthandler
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

LOG = ROOT / ".scratch" / "gui_debug.log"
LOG.parent.mkdir(exist_ok=True)

# 崩溃时 faulthandler 会把 native + Python 栈写进 stderr → 日志文件
_logf = open(LOG, "w", buffering=1, encoding="utf-8", errors="replace")
sys.stdout = _logf
sys.stderr = _logf
faulthandler.enable(file=_logf, all_threads=True)

from doubi.ui.app import main  # noqa: E402

sys.exit(main())
