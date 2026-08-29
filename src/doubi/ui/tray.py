"""System tray icon for DouBi.

Why a tray icon at all?
-----------------------
The user's mental model is "fire-and-forget": they paste a URL, click
download, and walk away. The 0.3.0 release added a «minimize to tray on
close» affordance so closing the window no longer kills in-flight
downloads. Without a tray icon, the user has no way to bring the
window back — they'd have to hunt through Task Manager or restart
``doubi-gui`` and reconnect to an already-running task manager.

The tray icon doubles as the surface for ``QSystemTrayIcon.showMessage``
toasts. Windows 10/11 routes those through Action Center so the user
sees them even when the main window is hidden.

Public surface
--------------
* :class:`TrayController` — the only thing main_window should import.
  It owns the ``QSystemTrayIcon``, builds the right-click menu, and
  exposes three thin signals the rest of the app wires up to:
  - ``show_window_requested`` — user picked "显示主窗口" or double-clicked
  - ``quit_requested``         — user picked "退出"
  - ``pause_all_requested`` / ``resume_all_requested`` — task manager
    hooks in via the standard signal/slot mechanism

* :func:`notify_completion` — pure function that decides whether to
  show a toast based on the current ``notify_on_completion`` setting
  and the event (success/failure). The actual ``QSystemTrayIcon.showMessage``
  call lives here too, so the "what shows" rule is in one place.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..core.models import MediaItem  # noqa: F401  (kept for future per-task toasts)

logger = logging.getLogger("doubi.ui.tray")

# Notification mode constants. The string values are the persisted
# form (AppConfig + YAML) and the keys in the settings page dropdown.
NOTIFY_SUCCESS = "success"
NOTIFY_ALL = "all"
NOTIFY_SUMMARY = "summary"
NOTIFY_MODES = (NOTIFY_SUCCESS, NOTIFY_ALL, NOTIFY_SUMMARY)


def _tray_icon() -> QIcon:
    """Return the app icon for the tray.

    The app already builds a per-theme ``QIcon`` for the title bar via
    :func:`doubi.ui.app.load_app_icon`. We pull the existing
    ``QApplication.windowIcon()`` to stay in sync — same icon, same
    recoloring, one source of truth. If the window icon is empty
    (e.g. during early boot) Qt will fall back to a default and the
    tray still works; we don't bother constructing one from scratch
    here.
    """
    app = QApplication.instance()
    if app is None:
        return QIcon()
    return app.windowIcon()


class TrayController(QObject):
    """Owns the ``QSystemTrayIcon`` and its context menu.

    Lifecycle
    ---------
    Constructed once in :class:`MainWindow`; lives as long as the
    process does. ``closeEvent`` calls :meth:`hide` to send the
    window to the tray; the user brings it back via the tray menu
    or a double-click on the icon. The :meth:`shutdown` path is for
    real exit ("退出" from the menu or the user picked "Quit" from
    a notification).
    """

    show_window_requested = Signal()
    quit_requested = Signal()
    pause_all_requested = Signal()
    resume_all_requested = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        # Some headless / minimal Linux distros disable the system tray
        # (e.g. CI containers, no notification daemon). On Windows this
        # is always available, but the guard keeps the import safe
        # during offscreen tests where QSystemTrayIcon may not be
        # backed by a real desktop.
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("[tray] system tray not available on this platform")
            self._icon: Optional[QSystemTrayIcon] = None
            return
        self._icon = QSystemTrayIcon(_tray_icon(), parent)
        self._icon.setToolTip("DouBi")
        self._build_menu()
        # Double-click / single-click (Windows defaults to single) on
        # the tray icon = bring the window back. The activated signal
        # fires for both clicks; we treat any of them as "show".
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

    # ---- menu / actions ----------------------------------------

    def _build_menu(self) -> None:
        """Construct the right-click menu. Idempotent."""
        if self._icon is None:
            return
        menu = QMenu()

        show_action = QAction("显示主窗口", menu)
        show_action.triggered.connect(self.show_window_requested.emit)
        menu.addAction(show_action)

        menu.addSeparator()

        self._pause_action = QAction("全部暂停", menu)
        self._pause_action.triggered.connect(self.pause_all_requested.emit)
        menu.addAction(self._pause_action)

        self._resume_action = QAction("全部继续", menu)
        self._resume_action.triggered.connect(self.resume_all_requested.emit)
        menu.addAction(self._resume_action)

        menu.addSeparator()

        quit_action = QAction("退出", menu)
        # ``triggered`` is fine; ``aboutToShow`` is not needed since
        # the menu is static. We *do* refresh the enabled state of
        # the pause/resume actions just before showing, so the user
        # sees the current state (e.g. "全部继续" greyed out if
        # nothing is paused).
        quit_action.triggered.connect(self._on_quit_triggered)
        menu.addAction(quit_action)

        # Refresh pause/resume availability every time the menu opens.
        # We don't connect to task manager state directly here — main
        # window does, via :meth:`update_running_state`. The
        # aboutToShow hook just kicks off a repaint.
        menu.aboutToShow.connect(self._refresh_action_labels)
        # 必须自己留一个 Python 引用：``setContextMenu`` 不转移所有权
        # （Qt 文档明确说托盘图标销毁时不会删这个菜单），局部变量
        # 出了作用域就可能被 GC 掉，菜单会变成空的或直接不弹。
        self._menu = menu
        self._icon.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # ``Trigger`` is the single-click on Windows; ``DoubleClick``
        # is the double-click on Linux/macOS. We accept both — the
        # most common case (Windows single-click) lands in Trigger.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window_requested.emit()

    def _on_quit_triggered(self) -> None:
        # Tear down the icon before emitting so any re-entrant code
        # that checks ``tray.isVisible()`` sees a clean state.
        self.shutdown()
        self.quit_requested.emit()

    # ---- public API ---------------------------------------------

    def update_running_state(self, *, running: int, paused: int) -> None:
        """Update the enabled state of pause / resume based on counts.

        Called by main_window whenever the task manager changes (the
        signal hook is set up there). Putting the logic in the tray
        controller keeps the rule "no running tasks → can't pause"
        next to the menu construction.
        """
        if self._icon is None:
            return
        self._pause_action.setEnabled(running > 0)
        self._resume_action.setEnabled(paused > 0)

    def _refresh_action_labels(self) -> None:
        """Hook for ``aboutToShow`` — the enabled state is updated
        via :meth:`update_running_state`, this method just exists to
        give :meth:`_build_menu` a stable callback target.
        """
        return

    def show_message(
        self,
        title: str,
        body: str,
        *,
        icon_kind: str = "info",
        msec: int = 5000,
    ) -> None:
        """Forward to ``QSystemTrayIcon.showMessage`` if available.

        Wrapping the API call lets the rest of the codebase stay
        blissfully unaware of whether the tray exists — headless test
        runs and the rare «tray not available» desktop both silently
        no-op rather than crashing.
        """
        if self._icon is None:
            return
        kind = {
            "info": QSystemTrayIcon.MessageIcon.Information,
            "warning": QSystemTrayIcon.MessageIcon.Warning,
            "critical": QSystemTrayIcon.MessageIcon.Critical,
        }.get(icon_kind, QSystemTrayIcon.MessageIcon.Information)
        self._icon.showMessage(title, body, kind, msec)

    def notify_completion(
        self,
        *,
        mode: str,
        success: bool,
        title: str,
        error: str = "",
    ) -> None:
        """Show a download-completion toast according to ``mode``.

        ``mode`` is the value of :attr:`AppConfig.notify_on_completion`:
        * ``"success"`` (default) — only successful completions notify.
        * ``"all"``               — success and failure both notify.
        * ``"summary"``           — single tasks are silent; the
          queue-level "all done" summary is fired by the caller.

        ``success`` selects success vs. failure tone. ``title`` is the
        task title (used in the toast body). ``error`` is shown only
        for failure toasts and is truncated to keep the notification
        compact.
        """
        if mode not in NOTIFY_MODES:
            # Defensive: settings page validates this, but a hand-
            # edited config.yml could still hand us garbage.
            mode = NOTIFY_SUCCESS

        if mode == NOTIFY_SUCCESS and not success:
            return
        if mode == NOTIFY_SUMMARY:
            # ``summary`` is fired by a different code path
            # (queue-empty), not per-task. If we get here it's a
            # caller bug, not a user preference.
            return

        if success:
            self.show_message(
                "下载完成",
                title or "（无标题）",
                icon_kind="info",
            )
        else:
            # Truncate so the toast stays a toast, not a wall of text.
            snippet = (error or "未知原因").strip().splitlines()[0][:80]
            body = title or "（无标题）"
            self.show_message(
                "下载失败",
                f"{body}\n{snippet}",
                icon_kind="warning",
            )

    def notify_summary(self, *, succeeded: int, failed: int) -> None:
        """Fire the queue-empty summary toast.

        Called once when the active list drains (i.e. all enqueued
        tasks have reached a terminal state). The user's preference
        is already on the controller's call site — this is a
        deliberate, separate API so we don't have to peek at
        AppConfig from here.
        """
        if succeeded == 0 and failed == 0:
            return
        body_parts = [f"完成 {succeeded} 项"]
        if failed:
            body_parts.append(f"失败 {failed} 项")
        self.show_message(
            "下载汇总",
            "，".join(body_parts),
            icon_kind="info",
        )

    def shutdown(self) -> None:
        """Hide and detach the tray icon. Idempotent."""
        if self._icon is None:
            return
        try:
            self._icon.hide()
        except Exception:
            # ``hide()`` has been known to raise on Windows when the
            # shell has dropped the icon — we still want to drop our
            # reference so the GC cleans it up.
            logger.exception("[tray] hide() raised during shutdown")
        self._icon = None
