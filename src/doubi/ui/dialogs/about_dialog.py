"""「关于」对话框——展示应用名 / 版本 / 版权。

仿 macOS / Win11 的 About 面板风格：上面是品牌区（大图标 + 应用名 +
副标题），下面是分组信息卡，最下面是版权行与关闭按钮。
"""

from __future__ import annotations


def build_about_dialog():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    )
    from qfluentwidgets import PushButton

    from ..resources import (
        APP_COPYRIGHT, APP_NAME, APP_TAGLINE, APP_VERSION,
        load_app_icon,
    )
    from ..theme import (
        FONT_FAMILY, SPACE_LG, SPACE_SM, TYPE_BODY, TYPE_CAPTION,
        card_qss, header_qss, muted_qss, token,
    )

    class AboutDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle(f"关于 {APP_NAME}")
            self.setModal(True)
            self.setFixedSize(440, 520)
            # 不设 icon 时 Windows 会回退到 python.exe 图标，跟品牌不符
            icon = load_app_icon()
            if icon is not None and not icon.isNull():
                self.setWindowIcon(icon)

            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, SPACE_LG)
            outer.setSpacing(SPACE_LG)

            # ---- 品牌区 ----
            outer.addWidget(self._build_hero())

            # ---- 信息卡 ----
            info_card = QLabel(self)
            info_card.setStyleSheet(card_qss() + "padding: 16px; margin: 0 16px;")
            info_text = (
                f"<div style='font-family:{FONT_FAMILY};"
                f"font-size:{TYPE_BODY}px;color:{token('text_primary')};'>"
                f"<p style='margin:4px 0'><b>应用名</b>　{APP_NAME} · {APP_TAGLINE}</p>"
                f"<p style='margin:4px 0'><b>版本</b>　{APP_VERSION}</p>"
                f"<p style='margin:4px 0'><b>平台</b>　Windows / macOS / Linux</p>"
                f"<p style='margin:4px 0'><b>技术栈</b>　PySide6 · qfluentwidgets · yt-dlp</p>"
                f"<p style='margin:4px 0'><b>许可</b>　GPL-3.0</p>"
                f"</div>"
            )
            info_card.setText(info_text)
            info_card.setWordWrap(True)
            outer.addWidget(info_card)

            # ---- 版权 ----
            cr = QLabel(APP_COPYRIGHT, self)
            cr.setStyleSheet(muted_qss())
            cr.setAlignment(Qt.AlignCenter)
            outer.addWidget(cr, 1, Qt.AlignBottom)

            # ---- 关闭 ----
            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(SPACE_LG, 0, SPACE_LG, 0)
            btn_row.addStretch(1)
            close_btn = PushButton("关闭", self)
            close_btn.setFixedWidth(96)
            close_btn.clicked.connect(self.accept)
            btn_row.addWidget(close_btn)
            outer.addLayout(btn_row)

        @staticmethod
        def _build_hero() -> QWidget:
            """品牌区：图标 + 应用名 + 副标题。"""
            hero = QWidget()
            hero.setObjectName("brandHero")
            hero.setStyleSheet(header_qss(1))

            h = QHBoxLayout(hero)
            h.setContentsMargins(SPACE_LG * 2, SPACE_LG * 2, SPACE_LG * 2, SPACE_LG * 2)
            h.setSpacing(SPACE_LG)

            # 96px：矢量渲染，比原先 72px 更有品牌存在感且不损失锐度
            icon = load_app_icon(96)
            if icon is not None and not icon.isNull():
                icon_label = QLabel()
                icon_label.setPixmap(icon.pixmap(96, 96))
                icon_label.setStyleSheet("background: transparent; border: none;")
                h.addWidget(icon_label, 0)

            text_col = QVBoxLayout()
            text_col.setSpacing(SPACE_SM)
            text_col.setContentsMargins(0, 0, 0, 0)

            title = QLabel(APP_NAME)
            title.setObjectName("brandHeroTitle")
            text_col.addWidget(title)

            sub = QLabel(APP_TAGLINE)
            sub.setObjectName("brandHeroSubtitle")
            text_col.addWidget(sub)

            version = QLabel(f"v{APP_VERSION}")
            version.setObjectName("brandHeroSubtitle")
            text_col.addWidget(version)

            text_widget = QWidget()
            text_widget.setStyleSheet("background: transparent; border: none;")
            text_widget.setLayout(text_col)
            h.addWidget(text_widget, 1)

            return hero

    return AboutDialog
