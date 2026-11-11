"""Pydantic schemas for the REST server.

These are defined at module level (not inside :func:`build_app`) so
Pydantic v2 can resolve them as proper types instead of forward
references. ``build_app`` imports them at runtime.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DownloadRequest(BaseModel):
    """Body for ``POST /api/v1/download``."""

    url: str = Field(..., min_length=1, description="The URL to download.")
    #: 分段下载（章节），如 ``"1:00-2:30"`` 或 ``"0:10-0:20,3:00-3:30"``。
    #: 时间戳支持 SS / MM:SS / HH:MM:SS。省略 = 下载完整视频。
    #: 不入 AppConfig——与 CLI ``--sections`` / GUI 弹窗同一待遇的
    #: 每请求临时覆盖。
    download_sections: Optional[str] = Field(
        None, description="Download only time ranges, e.g. '1:00-2:30' "
        "or '0:10-0:20,3:00-3:30'. Omit for the full video.",
    )


class ParseRequest(BaseModel):
    """Body for ``POST /api/v1/parse``.

    与 :class:`DownloadRequest` 分开定义而不是复用，是为了让两条路以后能
    各自长出不同字段（解析要嗅探开关，下载要覆盖项），不必互相牵连。
    """

    url: str = Field(..., min_length=1, description="The URL to parse.")
