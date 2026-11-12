"""M3u8Engine aiohttp 降级路径的 AES-128 解密与 EXT-X-MAP 测试。

ffmpeg 路径由 ffmpeg 理解这些标签；aiohttp 降级路径必须自己解析。
此前加密流会把密文拼成打不开的「视频」，fMP4 流会漏掉初始化段
（缺 moov 不可播）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doubi.core.models import DownloadOptions  # noqa: E402
from doubi.engines.m3u8 import (  # noqa: E402
    M3u8Engine,
    _decrypt_segment,
    _parse_iv,
    _parse_segment_specs,
)


def _specs(text: str, base: str = "https://cdn.example.com/v/index.m3u8"):
    return _parse_segment_specs(text, base)


# ---- 解析：AES-128 -------------------------------------------------------


def test_aes128_with_explicit_iv():
    text = (
        "#EXTM3U\n"
        '#EXT-X-KEY:METHOD=AES-128,URI="https://cdn.example.com/v/key.bin",IV=0x10ef8f75ca1085cf15d0630ec27080dc\n'
        "#EXTINF:10.0,\n"
        "seg-001.ts\n"
    )
    specs = _specs(text)
    assert len(specs) == 1
    assert specs[0].key_uri == "https://cdn.example.com/v/key.bin"
    assert specs[0].iv == bytes.fromhex("10ef8f75ca1085cf15d0630ec27080dc")
    assert specs[0].iv is not None and len(specs[0].iv) == 16


def test_aes128_without_iv_derives_from_media_seq():
    """无 IV 属性 → 按规范用媒体序列号的 128-bit big-endian 派生。"""
    text = (
        "#EXTM3U\n"
        "#EXT-X-MEDIA-SEQUENCE:7\n"
        '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n'
        "#EXTINF:10.0,\n"
        "seg-001.ts\n"
        "#EXTINF:10.0,\n"
        "seg-002.ts\n"
    )
    specs = _specs(text)
    assert specs[0].iv is None
    assert specs[0].media_seq == 7
    assert specs[1].media_seq == 8
    # 下载时派生：7 → 16 字节 BE
    assert specs[0].media_seq.to_bytes(16, "big")[-1] == 7


def test_sample_aes_raises():
    """SAMPLE-AES（DRM 语义）明确报错而不是静默产出垃圾。"""
    text = (
        "#EXTM3U\n"
        '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://key"\n'
        "#EXTINF:10.0,\n"
        "seg-001.ts\n"
    )
    with pytest.raises(ValueError, match="SAMPLE-AES"):
        _specs(text)


def test_method_none_clears_key():
    """加密段之后跟 METHOD=NONE 段：后面的分片不再解密。"""
    text = (
        "#EXTM3U\n"
        '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n'
        "#EXTINF:10.0,\n"
        "enc.ts\n"
        '#EXT-X-KEY:METHOD=NONE\n'
        "#EXTINF:10.0,\n"
        "plain.ts\n"
    )
    specs = _specs(text)
    assert specs[0].key_uri is not None
    assert specs[1].key_uri is None


def test_parse_iv_short_value_left_padded():
    assert _parse_iv("0xab") == b"\x00" * 15 + b"\xab"


# ---- 解密往返 -------------------------------------------------------------


def test_decrypt_segment_roundtrip():
    """真实 AES-128-CBC + PKCS7：加密→解密回到原文。"""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = bytes(range(16))
    iv = bytes(range(16, 32))
    plaintext = b"x" * 1000 + b"TAIL"
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = enc.update(padded) + enc.finalize()

    assert _decrypt_segment(ciphertext, key, iv) == plaintext


# ---- EXT-X-MAP ------------------------------------------------------------


def test_ext_x_map_init_segment_prepended():
    text = (
        "#EXTM3U\n"
        '#EXT-X-MAP:URI="init.mp4"\n'
        "#EXTINF:10.0,\n"
        "seg-001.m4s\n"
        "#EXTINF:10.0,\n"
        "seg-002.m4s\n"
    )
    specs = _specs(text)
    assert specs[0].is_init is True
    assert specs[0].url == "https://cdn.example.com/v/init.mp4"
    assert [s.url for s in specs[1:]] == [
        "https://cdn.example.com/v/seg-001.m4s",
        "https://cdn.example.com/v/seg-002.m4s",
    ]


# ---- 端到端：加密分片下载 + 解密合并 ----------------------------------------


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data

    def raise_for_status(self):
        return None

    async def read(self):
        return self._data


class _FakeSession:
    """按 URL 返回预设字节；记录请求序列。"""

    def __init__(self, pages: dict[str, bytes]):
        self._pages = pages
        self.requested: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, proxy=None):
        self.requested.append(url)
        if url not in self._pages:
            raise AssertionError(f"unexpected request: {url}")
        return _FakeCtx(self._pages[url])


class _FakeCtx:
    def __init__(self, data):
        self._data = data

    async def __aenter__(self):
        return _FakeResp(self._data)

    async def __aexit__(self, *a):
        return False


class _FakeAiohttp:
    def __init__(self, session):
        self._session = session

    def ClientSession(self, timeout=None):
        return self._session

    def ClientTimeout(self, **kwargs):
        return object()


def test_encrypted_download_end_to_end(tmp_path):
    """加密列表 → key 预取一次 → 分片解密 → 按序合并出明文。"""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = bytes(range(16))
    iv = bytes(range(16, 32))

    def encrypt(plain: bytes) -> bytes:
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plain) + padder.finalize()
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return enc.update(padded) + enc.finalize()

    plain0 = b"SEGMENT-ZERO" * 20
    plain1 = b"segment-one-" * 20
    session = _FakeSession({
        "https://cdn.example.com/v/index.m3u8": (
            "#EXTM3U\n"
            '#EXT-X-KEY:METHOD=AES-128,URI="https://cdn.example.com/v/key.bin",IV=0x'
            + iv.hex() + "\n"
            "#EXTINF:10.0,\nseg-0.ts\n"
            "#EXTINF:10.0,\nseg-1.ts\n"
        ).encode(),
        "https://cdn.example.com/v/key.bin": key,
        "https://cdn.example.com/v/seg-0.ts": encrypt(plain0),
        "https://cdn.example.com/v/seg-1.ts": encrypt(plain1),
    })
    engine = M3u8Engine()
    out = tmp_path / "out.mp4"

    events: list = []
    asyncio.run(engine._download_and_concat(
        _FakeAiohttp(session),
        _specs(
            '#EXT-X-KEY:METHOD=AES-128,URI="https://cdn.example.com/v/key.bin",IV=0x'
            + iv.hex() + "\nseg-0.ts\nseg-1.ts\n",
        ),
        out,
        DownloadOptions(output_root=tmp_path),
        events.append,
    ))

    assert out.read_bytes() == plain0 + plain1
    # key 只拉一次（两个分片共用）
    assert session.requested.count("https://cdn.example.com/v/key.bin") == 1
    assert events[-1].fraction == 1.0


def test_fmp4_download_includes_init_segment(tmp_path):
    """EXT-X-MAP：init 段作为第一个字节块进入合并输出。"""
    session = _FakeSession({
        "https://cdn.example.com/v/index.m3u8": (
            b'#EXT-X-MAP:URI="init.mp4"\nseg-0.m4s\nseg-1.m4s\n'
        ),
        "https://cdn.example.com/v/init.mp4": b"MOOV-INIT",
        "https://cdn.example.com/v/seg-0.m4s": b"FRAG0",
        "https://cdn.example.com/v/seg-1.m4s": b"FRAG1",
    })
    engine = M3u8Engine()
    out = tmp_path / "out.mp4"

    asyncio.run(engine._download_and_concat(
        _FakeAiohttp(session),
        _specs('#EXT-X-MAP:URI="init.mp4"\nseg-0.m4s\nseg-1.m4s\n'),
        out,
        DownloadOptions(output_root=tmp_path),
        None,
    ))

    assert out.read_bytes() == b"MOOV-INITFRAG0FRAG1"


def test_bad_key_length_fails_loud(tmp_path):
    """key 不是 16 字节 → 明确失败，不产半截文件。"""
    session = _FakeSession({
        "https://cdn.example.com/v/index.m3u8": (
            b'#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\nseg-0.ts\n'
        ),
        "https://cdn.example.com/v/key.bin": b"short",
        "https://cdn.example.com/v/seg-0.ts": b"DATA",
    })
    engine = M3u8Engine()
    out = tmp_path / "out.mp4"
    with pytest.raises(RuntimeError, match="AES key"):
        asyncio.run(engine._download_and_concat(
            _FakeAiohttp(session),
            _specs('#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\nseg-0.ts\n'),
            out,
            DownloadOptions(output_root=tmp_path),
            None,
        ))
    assert not out.exists()
