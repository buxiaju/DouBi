; 豆比下载 —— Windows 安装包脚本（NSIS 3.x / MUI2）
;
; 编译（推荐走 scripts/build_installer.py，它会先跑 PyInstaller）::
;
;     tools\nsis\nsis-3.11\makensis.exe /INPUTCHARSET UTF8 installer\doubi.nsi
;
; 三个可被 /D 覆盖的入参：
;
;     /DPRODUCT_VERSION=0.1.0          版本号（同时写进 exe 版本资源）
;     /DSRC_DIR=<PyInstaller onedir>   要打包的源目录
;     /DOUT_FILE=<安装包输出路径>
;
; 设计取舍：
;
; * **当前用户安装**（RequestExecutionLevel user + $LOCALAPPDATA）。
;   不写 Program Files，于是全程不弹 UAC；同时少一层杀软对
;   「未签名程序写系统目录」的启发式告警——PyInstaller 产物本身
;   已经容易误报（见 docs/BUILD.md §5.5），没必要再叠加。
; * **打 onedir 而不是 onefile**。onefile 每次启动都要把 235 MB
;   解包到 %TEMP%，慢 1-2 秒；而且 onefile 已经 LZMA 压过一遍，
;   再被 NSIS 压一遍收益极低、构建极慢。onedir 装完即用。
; * 卸载时**默认保留用户数据**（~/.doubi 里有 cookie / 配置 /
;   下载记录数据库），只在用户明确勾选时才删。

Unicode true
ManifestDPIAware true

;--------------------------------------------------------------------
; 入参默认值
;
; ${__FILEDIR__} 是本 .nsi 所在目录。用它拼默认路径，而不是写
; 相对路径——NSIS 的相对路径按 makensis 的工作目录解析，从别处
; 调用就会找不到文件。
;--------------------------------------------------------------------
; 兜底值刻意写成 0.0.0 而不是某个真实版本号：真源是
; src/doubi/__init__.py 的 __version__，由 scripts/build_installer.py
; 读出后用 /DPRODUCT_VERSION 注进来。万一漏传，产物会叫
; DouBi-Setup-0.0.0.exe，一眼能看出来没传版本号，而不是打出一个
; 版本号对不上的正式包。
;
; 不写成 0.0.0-dev 之类：下面 VIProductVersion 要求四段纯数字，
; 带字母后缀会让 makensis 直接编译失败。
!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "0.0.0"
!endif
!ifndef SRC_DIR
  !define SRC_DIR "${__FILEDIR__}\..\dist\doubi-gui"
!endif
!ifndef OUT_FILE
  !define OUT_FILE "${__FILEDIR__}\..\dist\DouBi-Setup-${PRODUCT_VERSION}.exe"
!endif

!define PRODUCT_NAME "豆比下载"
!define PRODUCT_NAME_EN "DouBi"
!define PRODUCT_PUBLISHER "DouBi"
!define PRODUCT_DESC "多平台视频下载器（抖音 / 哔哩哔哩）"
!define APP_EXE "doubi-gui.exe"
!define REG_UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME_EN}"
!define ICON_FILE "${__FILEDIR__}\..\src\doubi\ui\resources\icon.ico"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

;--------------------------------------------------------------------
; 基本属性
;--------------------------------------------------------------------
Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$LOCALAPPDATA\${PRODUCT_NAME_EN}"
; 重装时沿用上次的安装位置（HKCU，与 per-user 安装一致）
InstallDirRegKey HKCU "Software\${PRODUCT_NAME_EN}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${PRODUCT_NAME_EN} ${PRODUCT_VERSION}"

; VIProductVersion 必须是四段数字，不能直接用 0.1.0
VIProductVersion "${PRODUCT_VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=2052 "FileVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=2052 "FileDescription" "${PRODUCT_NAME} 安装程序"
VIAddVersionKey /LANG=2052 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "GPL-3.0"

;--------------------------------------------------------------------
; MUI2 界面
;--------------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON "${ICON_FILE}"
!define MUI_UNICON "${ICON_FILE}"

!define MUI_WELCOMEPAGE_TITLE "欢迎安装 ${PRODUCT_NAME}"
!define MUI_WELCOMEPAGE_TEXT "${PRODUCT_DESC}。$\r$\n$\r$\n本程序将安装到当前用户目录，不需要管理员权限。$\r$\n$\r$\n如果 ${PRODUCT_NAME} 正在运行，安装程序会先关闭它。$\r$\n$\r$\n点击「下一步」继续。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${__FILEDIR__}\..\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${PRODUCT_NAME}"
!define MUI_FINISHPAGE_NOREBOOTSUPPORT
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_COMPONENTS
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

;--------------------------------------------------------------------
; 确保主程序没在运行
;
; 便携版 NSIS 不带 nsProcess 插件，所以用系统自带命令：
;   tasklist ... | find  —— 找到返回 0、没找到返回 1，
; 拿退出码当判据，不需要解析字符串。
;--------------------------------------------------------------------
!macro EnsureAppClosed un
Function ${un}EnsureAppClosed
  nsExec::Exec 'cmd /c tasklist /FI "IMAGENAME eq ${APP_EXE}" /NH | find /I "${APP_EXE}"'
  Pop $0
  ${If} $0 != 0
    Return                      ; 没在跑，直接过
  ${EndIf}

  MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION \
    "检测到 ${PRODUCT_NAME} 正在运行。$\r$\n$\r$\n必须先关闭它，否则程序文件被占用、无法写入。$\r$\n点击「确定」立即关闭。" \
    IDOK doubi_kill
  Abort "请先手动关闭 ${PRODUCT_NAME} 后重试。"

doubi_kill:
  DetailPrint "正在关闭 ${PRODUCT_NAME}..."
  nsExec::Exec 'taskkill /F /IM "${APP_EXE}" /T'
  Pop $0
  ; 给系统一点时间真正释放文件句柄——taskkill 返回不代表句柄已回收
  Sleep 1500
FunctionEnd
!macroend
!insertmacro EnsureAppClosed ""
!insertmacro EnsureAppClosed "un."

;--------------------------------------------------------------------
; 安装
;--------------------------------------------------------------------
Section "${PRODUCT_NAME}（必需）" SEC_MAIN
  SectionIn RO
  Call EnsureAppClosed

  SetOutPath "$INSTDIR"
  SetOverwrite on

  ; /r 递归整个 PyInstaller onedir：exe + _internal 里成百上千个
  ; .dll / .pyd / Qt 插件。逐个 File 列出来不现实，也没必要。
  File /r "${SRC_DIR}\*.*"

  ; 开始菜单（放到用户自己的开始菜单，与 per-user 安装一致）
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" \
    "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\卸载 ${PRODUCT_NAME}.lnk" \
    "$INSTDIR\uninstall.exe"

  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "Software\${PRODUCT_NAME_EN}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\${PRODUCT_NAME_EN}" "Version" "${PRODUCT_VERSION}"

  ; 「应用和功能」里的条目。全部写 HKCU：per-user 安装不该出现在
  ; 其他账户的卸载列表里，写 HKLM 反而需要管理员权限。
  WriteRegStr HKCU "${REG_UNINST}" "DisplayName" "${PRODUCT_NAME} ${PRODUCT_VERSION}"
  WriteRegStr HKCU "${REG_UNINST}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${REG_UNINST}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${REG_UNINST}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${REG_UNINST}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${REG_UNINST}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegStr HKCU "${REG_UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${REG_UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${REG_UNINST}" "NoRepair" 1

  ; EstimatedSize 的单位是 KB。不写的话「应用和功能」显示空白。
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${REG_UNINST}" "EstimatedSize" "$0"
SectionEnd

Section "创建桌面快捷方式" SEC_DESKTOP
  CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" \
    "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN} "${PRODUCT_NAME} 主程序与全部运行时依赖。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} "在桌面放一个启动图标。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

;--------------------------------------------------------------------
; 卸载
;--------------------------------------------------------------------
Section "un.${PRODUCT_NAME}" UNSEC_MAIN
  SectionIn RO
  Call un.EnsureAppClosed

  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\卸载 ${PRODUCT_NAME}.lnk"
  RMDir "$SMPROGRAMS\${PRODUCT_NAME}"

  Delete "$INSTDIR\uninstall.exe"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\${APP_EXE}"
  ; 只在目录空了才删——RMDir 不带 /r，用户往安装目录里放过东西就保留
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "${REG_UNINST}"
  DeleteRegKey HKCU "Software\${PRODUCT_NAME_EN}"
SectionEnd

; 默认不勾选：里面是 cookie / 配置 / 下载记录数据库，
; 误删等于让用户重新扫码登录、丢掉全部历史。
Section /o "un.同时删除个人数据（配置、登录状态、下载记录）" UNSEC_DATA
  RMDir /r "$PROFILE\.doubi"
SectionEnd

!insertmacro MUI_UNFUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${UNSEC_MAIN} "删除程序文件、快捷方式与注册表项。"
  !insertmacro MUI_DESCRIPTION_TEXT ${UNSEC_DATA} "删除 $PROFILE\.doubi：配置、cookie、下载记录数据库。此操作不可恢复。"
!insertmacro MUI_UNFUNCTION_DESCRIPTION_END

;--------------------------------------------------------------------
; 卸载前确认目录合法
;
; $INSTDIR 来自注册表，理论上可能被改坏。带 RMDir /r 的卸载器
; 指向错目录会造成灾难，所以先确认主程序确实在那儿。
;--------------------------------------------------------------------
Function un.onInit
  IfFileExists "$INSTDIR\${APP_EXE}" +3 0
    MessageBox MB_OK|MB_ICONSTOP "在 $INSTDIR 找不到 ${APP_EXE}，卸载中止。"
    Abort
FunctionEnd
