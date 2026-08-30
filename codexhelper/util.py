# -*- coding: utf-8 -*-
"""基础工具：进程执行、路径、环境检测、环境变量读写。"""
import json
import os
import re
import shutil
import subprocess
import sys

from .constants import (COMMON_NODE_DIRS, CREATE_NO_WINDOW, NODE_MSI_NAME)


class OpCancelled(Exception):
    """用户点击了取消"""


def is_admin() -> bool:
    if os.name != "nt":
        return True
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """以管理员身份重启自身。成功返回 True（调用方应随即退出当前实例）。"""
    if os.name != "nt":
        return False
    import ctypes
    try:
        if getattr(sys, "frozen", False):
            target, args = sys.executable, None
        else:
            target, args = sys.executable, f'"{os.path.abspath(__file__)}"'
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, args, None, 1)
        return int(ret) > 32
    except Exception:
        return False


def decode_bytes(b) -> str:
    if not b:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, AttributeError):
            continue
    return b.decode("utf-8", "replace")


def run_quiet(args, timeout=25):
    """执行命令并返回 (returncode, 合并后的文本)。不弹任何窗口。"""
    try:
        p = subprocess.run(
            args, capture_output=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        text = decode_bytes(p.stdout) + "\n" + decode_bytes(p.stderr)
        return p.returncode, text.strip()
    except Exception as e:  # FileNotFoundError、TimeoutExpired 等
        return -1, str(e)


def kill_tree(pid: int):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=CREATE_NO_WINDOW,
                       timeout=15)
    except Exception:
        pass


def res_path(name: str):
    """取随包资源：frozen 时在 _MEIPASS(assets) 下，否则在脚本目录。"""
    bases = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(os.path.join(meipass, "assets"))
        bases.append(meipass)
    base_file = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    bases += [base_file, os.getcwd()]
    for b in bases:
        p = os.path.join(b, "assets", name)
        if os.path.isfile(p):
            return p
    for b in bases:
        p = os.path.join(b, name)
        if os.path.isfile(p):
            return p
    return None


def locate_msi():
    """优先内置资源；其次 exe 同目录 / 脚本目录里现成的 msi。找不到返回 None。"""
    from .constants import NODE_MSI_URLS  # noqa: F401  (仅文档用)
    p = res_path(NODE_MSI_NAME)
    if p:
        return p
    for d in dict.fromkeys([os.path.dirname(os.path.abspath(sys.executable)),
                            os.getcwd()]):
        p = os.path.join(d, NODE_MSI_NAME)
        if os.path.isfile(p):
            return p
    return None


# ---------------------------------------------------------------- 环境检测 --

def find_node_dir():
    which = shutil.which("node")
    if which and os.path.isfile(which):
        return os.path.dirname(os.path.abspath(which))
    for d in COMMON_NODE_DIRS:
        if os.path.isfile(os.path.join(d, "node.exe")):
            return d
    return None


def get_version(text):
    m = re.search(r"\d+\.\d+(?:\.\d+)?(?:[-+][\w.\-]+)?", text or "")
    return m.group(0) if m else None


def make_env(node_dir=None):
    env = dict(os.environ)
    extra = []
    if node_dir:
        extra.insert(0, node_dir)
    appdata_npm = os.path.join(env.get("APPDATA", ""), "npm")
    if os.path.isdir(appdata_npm):
        extra.append(appdata_npm)
    if extra:
        env["PATH"] = ";".join(extra) + ";" + env.get("PATH", "")
    return env


def detect():
    """返回当前环境信息字典。所有子进程均静默执行。"""
    info = {
        "node_dir": None, "node_ver": None,
        "npm_node": None, "npm_cli": None, "npm_prefix": None, "npm_ver": None,
        "codex_ver": None, "codex_shim": None,
    }
    node_dir = find_node_dir()
    if not node_dir:
        # 无 node.exe 时仍看看 codex 是否全局可用（极端情况）
        w = shutil.which("codex")
        if w:
            info["codex_shim"] = w
            info["codex_ver"] = "已安装"
        return info
    info["node_dir"] = node_dir
    rc, out = run_quiet([os.path.join(node_dir, "node.exe"), "--version"])
    if rc == 0:
        info["node_ver"] = get_version(out)

    npm_js = os.path.join(node_dir, "node_modules", "npm", "bin", "npm-cli.js")
    node_exe = os.path.join(node_dir, "node.exe")
    if os.path.isfile(npm_js):
        info["npm_cli"], info["npm_node"] = npm_js, node_exe
        env = make_env(node_dir)
        try:
            p = subprocess.run([node_exe, npm_js, "--version"], capture_output=True,
                               timeout=30, creationflags=CREATE_NO_WINDOW, env=env)
            if p.returncode == 0:
                info["npm_ver"] = get_version(decode_bytes(p.stdout))
                p2 = subprocess.run([node_exe, npm_js, "config", "get", "prefix"],
                                    capture_output=True, timeout=30,
                                    creationflags=CREATE_NO_WINDOW, env=env)
                if p2.returncode == 0:
                    lines = decode_bytes(p2.stdout).strip().splitlines()
                    if lines:
                        info["npm_prefix"] = lines[0].strip()
        except Exception:
            pass

    prefix = info.get("npm_prefix")
    pkg_json = os.path.join(prefix or "", "node_modules", "@openai", "codex",
                            "package.json")
    if os.path.isfile(pkg_json):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            info["codex_ver"] = data.get("version") or "已安装"
        except Exception:
            info["codex_ver"] = "已安装"
        shim = os.path.join(prefix, "codex.cmd")
        if os.path.isfile(shim):
            info["codex_shim"] = shim
    else:
        w = shutil.which("codex")
        if w:
            info["codex_shim"] = w
            info["codex_ver"] = "已安装"
    return info


# ------------------------------------------------------------ 环境变量 ----

def get_user_env(name) -> str:
    """读取用户环境变量（直接查注册表 HKCU\\Environment，无需重启验证）。"""
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        v, _ = winreg.QueryValueEx(k, name)
        winreg.CloseKey(k)
        return v
    except Exception:
        return ""


def set_user_env(name, value, log=print) -> bool:
    """写入用户环境变量。PowerShell 的 SetEnvironmentVariable 会广播
    WM_SETTINGCHANGE，之后新启动的应用立即可见，无需注销或重启电脑。"""
    import base64
    ps_cmd = ("[Environment]::SetEnvironmentVariable('%s', '%s', 'User')"
              % (name, str(value).replace("'", "''")))
    enc = base64.b64encode(ps_cmd.encode("utf-16-le")).decode("ascii")
    ps_exe = shutil.which("powershell") or "powershell"
    rc, out = run_quiet([ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-EncodedCommand", enc], timeout=60)
    if rc != 0:
        log(f"写入环境变量失败（退出码 {rc}）：{out[:200]}", "warn")
        return False
    return get_user_env(name) == value
