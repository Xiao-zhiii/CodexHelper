# -*- coding: utf-8 -*-
"""ChatGPT（OpenAI.Codex 桌面应用）启动修复后端。"""
import glob
import json
import os
import shutil
import subprocess
import time

from .constants import CREATE_NO_WINDOW
from .util import decode_bytes, get_user_env, run_quiet, set_user_env  # noqa: F401

GPT_ERROR_TEXT = ("ChatGPT failed to start. Unable to locate the Codex CLI binary.\n"
                  "Set CODEX_CLI_PATH or ensure the Electron resources include bin/codex.")


def _ps_json_out(ps_cmd, timeout=90):
    """静默执行 PowerShell 命令并返回 stdout 文本；失败返回空串。"""
    ps_exe = shutil.which("powershell") or "powershell"
    try:
        p = subprocess.run([ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", ps_cmd], capture_output=True,
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except Exception:
        return ""
    return decode_bytes(p.stdout).strip()


def find_codex_desktop(log=print):
    """检测 OpenAI.Codex 桌面应用（ChatGPT）安装包（取最新版本）。
    返回 dict（name/version/location/family）；未安装返回 None。"""
    out = _ps_json_out(
        "Get-AppxPackage -Name 'OpenAI.Codex' | "
        "Sort-Object Version -Descending | Select-Object -First 1 | "
        "ConvertTo-Json")
    if not out:
        return None
    try:
        pkg = json.loads(out)
        if isinstance(pkg, list):
            pkg = pkg[0] if pkg else None
        if not pkg or not pkg.get("InstallLocation"):
            return None
        return {"name": pkg.get("Name"),
                "version": pkg.get("Version"),
                "location": pkg.get("InstallLocation"),
                "family": pkg.get("PackageFamilyName")}
    except Exception as e:
        log(f"解析 OpenAI.Codex 桌面包信息失败：{e}", "warn")
        return None


def locate_codex_cli(location):
    """定位 codex CLI 二进制：先按教程 repair.ps1 的候选顺序在桌面包内找；
    包内没有时回退到 npm 版 Codex CLI 的原生 codex.exe。"""
    candidates = [os.path.join(location, "app", "resources", "codex.exe"),
                  os.path.join(location, "app", "bin", "codex.exe"),
                  os.path.join(location, "app", "Codex.exe")]
    for p in candidates:
        if os.path.isfile(p):
            return p
    appdata = os.environ.get("APPDATA", "")
    for p in glob.glob(os.path.join(
            appdata, "npm", "node_modules", "@openai", "codex-win32-*",
            "vendor", "*", "bin", "codex.exe")):
        return p
    return None


def restart_chatgpt_app(log=print) -> bool:
    """关闭 ChatGPT 应用并重新启动（explorer shell:AppsFolder\\<family>!App）。"""
    subprocess.run(["taskkill", "/IM", "ChatGPT.exe", "/T", "/F"],
                   capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=20)
    time.sleep(2)
    pkg = find_codex_desktop(log=log)
    if not pkg or not pkg.get("family"):
        log("未找到 OpenAI.Codex 桌面包，无法自动重启 ChatGPT 应用。", "warn")
        return False
    try:
        subprocess.Popen(["explorer.exe",
                          "shell:AppsFolder\\" + pkg["family"] + "!App"])
        return True
    except Exception as e:
        log("重启 ChatGPT 应用失败：" + str(e), "warn")
        return False


def detect_gpt_env():
    """【ChatGPT 启动修复】分页的环境检测结果。"""
    info = {"pkg": None, "cli": None, "env": get_user_env("CODEX_CLI_PATH")}
    pkg = find_codex_desktop(log=lambda *a, **k: None)
    info["pkg"] = pkg
    if pkg and pkg.get("location"):
        info["cli"] = locate_codex_cli(pkg["location"])
    return info
