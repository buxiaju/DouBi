"""run_supervised_subprocess 的 CREATE_NO_WINDOW 默认注入守护。

打包后的 GUI 是 windowed（无控制台）。不设 ``CREATE_NO_WINDOW`` 时，
Windows 会为每个控制台子进程（N_m3u8DL-CLI / ffmpeg）分配一个新
控制台——用户表现为下载嗅探视频时黑色终端反复弹出。

背景：m3u8.py 早期只在同步探针（subprocess.run）加了 _NO_WINDOW，
异步主管道（run_supervised_subprocess）漏了，nm3u8dl 引擎整条链路
都从 supervisor 拉起，弹窗在 0.4.1 被 用户实锤报障。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import doubi.engines._subproc as sp


def _spy_create_subprocess_exec(monkeypatch, captured: dict):
    """包一层记录 kwargs 的 create_subprocess_exec，真实执行不拦截。"""
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        captured.update(kwargs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)


def test_supervisor_injects_create_no_window_on_windows(monkeypatch):
    """Windows 上默认注入 CREATE_NO_WINDOW；非 Windows 不碰 creationflags。"""
    captured: dict = {}
    _spy_create_subprocess_exec(monkeypatch, captured)
    rc, _ = asyncio.run(sp.run_supervised_subprocess(
        [sys.executable, "-c", "print(42)"],
        watchdog_seconds=30.0,
    ))
    assert rc == 0
    if sys.platform == "win32":
        assert captured.get("creationflags") == subprocess.CREATE_NO_WINDOW
    else:
        assert "creationflags" not in captured


def test_supervisor_respects_caller_creationflags(monkeypatch):
    """调用方显式传 creationflags 时不覆盖——尊重调用方语义。"""
    captured: dict = {}
    _spy_create_subprocess_exec(monkeypatch, captured)
    rc, _ = asyncio.run(sp.run_supervised_subprocess(
        [sys.executable, "-c", "print(42)"],
        creationflags=0,
        watchdog_seconds=30.0,
    ))
    assert rc == 0
    assert captured.get("creationflags") == 0


def test_no_window_constant_matches_create_no_window():
    """_NO_WINDOW 取值正确（Windows 上是 0x08000000，其他平台 0）。"""
    if sys.platform == "win32":
        assert sp._NO_WINDOW == subprocess.CREATE_NO_WINDOW == 0x08000000
    else:
        assert sp._NO_WINDOW == 0
