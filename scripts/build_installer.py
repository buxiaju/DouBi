"""把 dist/doubi-gui/ 打成 NSIS 安装包。

用法（项目根目录）::

    python scripts/build_installer.py            # 先跑 PyInstaller onedir，再编译安装包
    python scripts/build_installer.py --skip-build  # 复用现有 dist/doubi-gui/

产物：``dist/DouBi-Setup-<version>.exe``

为什么要有这层脚本，而不是直接敲 makensis：

* 版本号只有 ``pyproject.toml`` 一处真源。手抄进 .nsi 迟早对不上，
  所以这里读出来用 ``/D`` 注进去。
* NSIS 解析相对路径是按 **makensis 自己的工作目录**，不是按 .nsi
  所在目录。传绝对路径是唯一稳的做法。
* 便携版 NSIS 不在 PATH 里，得自己找 makensis.exe。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NSI = ROOT / "installer" / "doubi.nsi"
SRC_DIR = ROOT / "dist" / "doubi-gui"
APP_EXE = SRC_DIR / "doubi-gui.exe"

# 便携版解压位置。makensis.exe 在根目录和 Bin/ 下都有一份，
# 按顺序探测，谁在用谁。
MAKENSIS_CANDIDATES = (
    ROOT / "tools" / "nsis" / "nsis-3.11" / "makensis.exe",
    ROOT / "tools" / "nsis" / "nsis-3.11" / "Bin" / "makensis.exe",
)


def read_version() -> str:
    """从 pyproject.toml 抠出 version。

    不用 tomllib 是因为只要一个字段，正则足够，也省得关心
    ``[project]`` 之外还有没有同名 key——这里锚定了行首。
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("pyproject.toml 里找不到 version")
    return m.group(1)


def find_makensis() -> Path:
    for path in MAKENSIS_CANDIDATES:
        if path.is_file():
            return path
    raise SystemExit(
        "找不到 makensis.exe，看看 tools/nsis/ 下的便携版是否解压完整：\n"
        + "\n".join(f"  已试 {p}" for p in MAKENSIS_CANDIDATES)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="跳过 PyInstaller，直接用现有 dist/doubi-gui/",
    )
    args = parser.parse_args()

    if not NSI.is_file():
        print(f"缺少 {NSI}", file=sys.stderr)
        return 1

    makensis = find_makensis()
    version = read_version()

    if not args.skip_build:
        print(f">>> PyInstaller onedir 构建中（这一步几分钟）...")
        rc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_exe.py"), "--onedir"],
            cwd=ROOT,
        ).returncode
        if rc != 0:
            print("PyInstaller 构建失败，安装包不打了", file=sys.stderr)
            return rc

    # 校验放在构建之后：--skip-build 时这是唯一的把关点，
    # 不校验的话 NSIS 会打出一个「装完就闪退」的空壳安装包。
    if not APP_EXE.is_file():
        print(
            f"缺少 {APP_EXE}\n先跑 python scripts/build_exe.py --onedir",
            file=sys.stderr,
        )
        return 1

    out_file = ROOT / "dist" / f"DouBi-Setup-{version}.exe"
    cmd = [
        str(makensis),
        # .nsi 里有中文字符串，不指定的话 makensis 会按 ACP 猜，
        # 猜错就是安装界面全是乱码
        "/INPUTCHARSET", "UTF8",
        f"/DPRODUCT_VERSION={version}",
        f"/DSRC_DIR={SRC_DIR}",
        f"/DOUT_FILE={out_file}",
        str(NSI),
    ]
    print(">>>", " ".join(cmd))
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0:
        return rc

    if not out_file.is_file():
        print(f"makensis 报成功但没产物：{out_file}", file=sys.stderr)
        return 1

    size_mb = out_file.stat().st_size / 1024 / 1024
    print(f"OK → {out_file}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
