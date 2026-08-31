# -*- coding: utf-8 -*-
"""常量集中地：应用信息、下载源、水印、路径。"""
import os

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010

APP_TITLE = "Codex 小帮手"
APP_VENDOR = "小枳ai分享"
APP_VERSION = "1.8.1"

# ------------------------------------------------------------- 版权与水印 --
# © 小枳ai分享 · 作者标识以内置方式嵌入（暗水印），解码后即作者主页。
_WW_KEY = 0x5A
_WW_DATA = (0x32, 0x2E, 0x2E, 0x2A, 0x29, 0x60, 0x75, 0x75, 0x3D, 0x33,
            0x2E, 0x32, 0x2F, 0x38, 0x74, 0x39, 0x35, 0x37, 0x75, 0x02,
            0x33, 0x3B, 0x35, 0x77, 0x20, 0x32, 0x33, 0x33, 0x33)


def _wm() -> str:
    """作者标识（暗水印）：由混淆字节运行时还原。"""
    return bytes(b ^ _WW_KEY for b in _WW_DATA).decode("utf-8")
# ​‌‌​‌​​​​‌‌‌​‌​​​‌‌‌​‌​​​‌‌‌​​​​​‌‌‌​​‌‌​​‌‌‌​‌​​​‌​‌‌‌‌​​‌​‌‌‌‌​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌‌‌​‌‌​‌​​‌​‌‌‌‌​‌​‌‌​​​​‌‌​‌​​‌​‌‌​​​​‌​‌‌​‌‌‌‌​​‌​‌‌​‌​‌‌‌‌​‌​​‌‌​‌​​​​‌‌​‌​​‌​‌‌​‌​​‌​‌‌​‌‌‌‌  # 作者签名（零宽字符水印，请勿删除本行）

NODE_VER = "v24.18.0"
NODE_MSI_NAME = f"node-{NODE_VER}-x64.msi"
NODE_MSI_URLS = [
    "https://registry.npmmirror.com/-/binary/node/" + NODE_VER + "/" + NODE_MSI_NAME,
    "https://nodejs.org/dist/" + NODE_VER + "/" + NODE_MSI_NAME,
]
CODEX_PKG = "@openai/codex"
MIRROR_REGISTRY = "https://registry.npmmirror.com"
MIRROR_TIMEOUT_SEC = 300        # 镜像源超过 5 分钟未成功 → 切换官方源
OFFICIAL_TIMEOUT_SEC = 900      # 官方源最长等待
MSI_TIMEOUT_SEC = 1200

# ---- Codex 插件修复 ----
SKILL_REPO = "Xiao-zhiii/codex-windows-fast-patch-skill"
SKILL_DIR_NAME = "codex-windows-fast-patch-skill"
SKILL_ZIP_URLS = [
    "https://codeload.github.com/" + SKILL_REPO + "/zip/refs/heads/main",
    "https://codeload.github.com/" + SKILL_REPO + "/zip/refs/heads/master",
    "https://ghproxy.net/https://github.com/" + SKILL_REPO + "/archive/refs/heads/main.zip",
    "https://gh-proxy.com/https://github.com/" + SKILL_REPO + "/archive/refs/heads/main.zip",
]
# 用户指定的修复目标提示词（自动输入到 codex TUI）
FIX_PROMPT = ("排查并修复本机codex桌面端无法调用chrome插件，浏览器插件，"
              "computer use插件无法使用的问题")
FIX_COMMAND = "/goal " + FIX_PROMPT
CODEX_BOOT_WAIT_SEC = 10        # codex 窗口出现后再等 TUI 就绪的秒数
GOAL_MD_BODY = """请先完整阅读本机已安装的技能文件：~/.codex/skills/codex-windows-fast-patch-skill/SKILL.md

该技能用于恢复 Windows Codex Desktop 升级后失效的补丁与能力开关（Chrome / 浏览器插件、Computer Use 等）。
请严格按照 SKILL.md 中的步骤执行。

本次目标：{prompt}

完成后请逐项验证 Chrome 插件 / 浏览器插件 / Computer Use 是否恢复可用，并给出结果摘要。"""

COMMON_NODE_DIRS = [
    r"C:\Program Files\nodejs",
    r"C:\Program Files (x86)\nodejs",
]

# ---- Codex 桌面端降级/升级（v1.5.0 新增）----
APPX_MIRROR_REPO = "Wangnov/codex-app-mirror"
APPX_PKG_NAME = "OpenAI.Codex"
APPX_ARCH = "arm64" if os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() == "ARM64" else "x64"
GHPROXYLIST = "https://ghproxylist.com/"
APPX_DL_TIMEOUT_SEC = 1800     # 单版本 MSIX 约 800MB，给足下载时间
APPX_INSTALL_TIMEOUT_SEC = 1800
