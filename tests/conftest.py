"""全测试共享的 autouse fixture。

qrouter 清墓（2026-11）：qfluentwidgets 的全局 Router（``qrouter``）用
普通 dict 强引用每个导航过的 QStackedWidget，且**没有任何注销 API**。
每个测试建一个主窗、从不关闭，不清理的话 qrouter 把几百个窗口连同整棵
控件树钉到进程结束；qfluentwidgets 的 ``set_theme`` 每次全量重刷所有
注册控件（实测 ~9ms/控件），累积窗口让它二次方劣化——全量单进程回归
跑到 ~91% 就慢到像卡死（test_ui_shell_regression_037 + 039 同进程
10 分钟跑不完；py-spy 抓栈卡在 StyleSheetCompose 递归）。

每个测试结束后先 ``gc.collect()``（打破 PySide6 wrapper 的引用环，让
无外部引用的窗口真正销毁），再清空 qrouter 的强引用表。对非 GUI 测试
是无害空转。theme.subscribe_theme 的两条泄漏链（_callbacks 强引用 +
qconfig 裸 lambda 连接）已在产品侧修掉，此处是 qfluentwidgets 内部
全局表的兜底。
"""
import gc

import pytest


@pytest.fixture(autouse=True)
def _purge_qrouter_and_gc():
    yield
    try:
        from qfluentwidgets.common.router import qrouter
    except ImportError:  # pragma: no cover - 无 GUI 环境
        qrouter = None
    if qrouter is not None:
        qrouter.stackHistories.clear()
        qrouter.history.clear()
    gc.collect()
