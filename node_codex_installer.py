# -*- coding: utf-8 -*-
"""
Node.js + Codex CLI 一键安装器（独立 exe 版）

版权所有 (C) 2026 小枳ai分享
本程序由 小枳ai分享 制作并分享，转载/二次分发请保留本版权声明。
"""
import base64
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

CREATE_NO_WINDOW = 0x08000000

APP_TITLE = "Node.js + Codex CLI 一键安装器"
APP_VENDOR = "小枳ai分享"
APP_VERSION = "1.1.0"

# ------------------------------------------------------------- 版权与水印 --
# © 小枳ai分享 · 作者标识以内置方式嵌入（暗水印），解码后即作者主页。
_WW_KEY = 0x5A
_WW_DATA = (0x32, 0x2E, 0x2E, 0x2A, 0x29, 0x60, 0x75, 0x75, 0x3D, 0x33,
            0x2E, 0x32, 0x2F, 0x38, 0x74, 0x39, 0x35, 0x37, 0x75, 0x02,
            0x33, 0x3B, 0x35, 0x77, 0x20, 0x32, 0x33, 0x33, 0x33)


def _wm() -> str:
    """作者标识（暗水印）：由混淆字节运行时还原。"""
    return bytes(b ^ _WW_KEY for b in _WW_DATA).decode("utf-8")
# ​‌‌​‌​​​​‌‌‌​‌​​​‌‌‌​‌​​​‌‌‌​​​​​‌‌‌​​‌‌​​‌‌‌​‌​​​‌​‌‌‌‌​​‌​‌‌‌‌​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​‌‌​​​​‌‌​‌​​‌​‌‌​​​​‌​‌‌​‌‌‌‌​​‌​‌‌​‌​‌‌‌‌​‌​​‌‌​‌​​​​‌‌​‌​​‌​‌‌​‌​​‌​‌‌​‌​​‌  # 作者签名（零宽字符水印，请勿删除本行）
NODE_VER = "v24.18.0"
NODE_MSI_NAME = f"node-{NODE_VER}-x64.msi"
NODE_MSI_URLS = [
    "https://registry.npmmirror.com/-/binary/node/" + NODE_VER + "/" + NODE_MSI_NAME,
    "https://nodejs.org/dist/" + NODE_VER + "/" + NODE_MSI_NAME,
]
CODEX_PKG = "@openai/codex"
MIRROR_REGISTRY = "https://registry.npmmirror.com"
MIRROR_TIMEOUT_SEC = 300        # 镜像源超过 5 分钟未成功 → 切换官方源（《命令.txt》要求）
OFFICIAL_TIMEOUT_SEC = 900      # 官方源最长等待
MSI_TIMEOUT_SEC = 1200

COMMON_NODE_DIRS = [
    r"C:\Program Files\nodejs",
    r"C:\Program Files (x86)\nodejs",
]


class OpCancelled(Exception):
    """用户点击了取消"""


# ---------------------------------------------------------------- 基础工具 --

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


# ---------------------------------------------------------------- 后台任务 --

class Installer:
    """
    在后台线程中工作，通过 self.q 向 UI 发消息：
        ("log", tag, text)      写日志行（tag: normal/ok/warn/err/dim）
        ("status", text)        底部任务状态（可被 tick 加时间后缀）
        ("tick", n)             心跳秒数
        ("info", dict)          更新检测结果标签
        ("done", ok, summary)   整个流程结束
    """

    def __init__(self, q: queue.Queue):
        self.q = q
        self.cancel = threading.Event()

    # ---- 消息 ----
    def log(self, text, tag="normal"):
        self.q.put(("log", tag, str(text)))

    def status(self, text):
        self.q.put(("status", text))

    def check_cancel(self):
        if self.cancel.is_set():
            raise OpCancelled()

    # ---- 入口 ----
    def run(self, want_node: bool, want_codex: bool):
        q = self.q
        try:
            self.cancel.clear()
            self._cancel_noted = False

            if want_node:
                info = detect()
                if info["node_dir"] and info["node_ver"]:
                    self.log(f"检测到本机已有 Node.js {info['node_ver']}，跳过 Node.js 安装。",
                             "ok")
                else:
                    self.install_node()

            if want_codex:
                info = detect()
                if not (info["npm_node"] and info["npm_cli"]):
                    raise RuntimeError("没有可用的 npm，无法安装 Codex CLI。请先安装 Node.js。")
                self.install_codex(info)

            q.put(("done", True, "全部任务已完成"))
        except OpCancelled:
            self.log("操作已被用户取消。", "warn")
            q.put(("done", False, "已取消"))
        except Exception as e:
            self.log("发生错误：" + str(e), "err")
            self.log(traceback.format_exc(limit=3), "err")
            q.put(("done", False, "失败：" + str(e)))

    # ---- Node.js ----
    def install_node(self):
        msi = locate_msi()
        if msi:
            size_mb = os.path.getsize(msi) / 1048576
            self.log(f"使用离线安装包：{os.path.basename(msi)}（{size_mb:.0f} MB）")
        else:
            self.log("exe 内未找到离线安装包，开始联网下载 Node.js ……", "warn")
            msi = self.download_msi()

        self.status("正在静默安装 Node.js（如弹出“用户账户控制”请点【是】）")
        self.log("正在静默安装 Node.js 到默认目录 C:\\Program Files\\nodejs\\，"
                 "约需 1~3 分钟，期间请不要关闭本程序。")

        args_list = ["/i", f'"{msi}"', "/qn", "/norestart"]
        joined = ",".join("'" + a + "'" for a in args_list)
        ps_cmd = (
            "$ErrorActionPreference='Stop';"
            "$p=Start-Process -FilePath 'msiexec.exe' "
            f"-ArgumentList {joined} -Verb RunAs -Wait -PassThru;"
            "if($null -eq $p){exit 1602}else{exit $p.ExitCode}"
        )
        enc = base64.b64encode(ps_cmd.encode("utf-16-le")).decode("ascii")

        ps_exe = shutil.which("powershell") or "powershell"
        proc = subprocess.Popen(
            [ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
            creationflags=CREATE_NO_WINDOW,
        )

        t0 = time.time()
        last_sec = -1
        rc = None
        while True:
            # 取消采用“软取消”：系统安装器无法安全中断，等它结束后再停止后续步骤
            if self.cancel.is_set() and not getattr(self, "_cancel_noted", False):
                self._cancel_noted = True
                self.log("已请求取消：将等待当前系统安装步骤结束后停止后续操作…", "warn")
            rc = proc.poll()
            if rc is not None:
                break
            sec = int(time.time() - t0)
            if sec != last_sec:
                last_sec = sec
                self.q.put(("tick", sec))
            if sec > MSI_TIMEOUT_SEC:
                kill_tree(proc.pid)
                proc.wait(timeout=30)
                rc = -1
                break
            time.sleep(0.25)

        cancelled = self.cancel.is_set()
        if rc in (0, 3010):
            note = "" if rc == 0 else "（提示：建议重启电脑以完全生效，一般可直接使用）"
            self.log(f"Node.js 安装完成{note}", "ok")
        elif cancelled:
            raise OpCancelled()   # 软取消：等系统安装器自然结束后停止
        elif rc == -1:
            raise TimeoutError("Node.js 安装超时，请重新运行本程序再试。")
        elif rc in (1223, 1602):
            raise PermissionError(
                "Windows 弹出的管理员授权被取消，无法静默安装 Node.js。\n"
                "请重新点击安装并在“用户账户控制”窗口点【是】。")
        else:
            hex_code = f"0x{rc:08X}" if isinstance(rc, int) and rc > 0 else str(rc)
            raise RuntimeError(
                f"msiexec 返回错误码 {rc}（{hex_code}）。"
                "可尝试右键本 exe 以管理员身份运行后重试。")

        for d in COMMON_NODE_DIRS:
            node = os.path.join(d, "node.exe")
            if os.path.isfile(node):
                _, out = run_quiet([node, "--version"])
                self.log(f"已验证：node.exe 位于 {d}，版本 {get_version(out) or '?'}", "ok")
                return
        raise RuntimeError("安装程序返回成功，但未找到 node.exe，请重启电脑后再次运行本程序。")

    def download_msi(self):
        dest = os.path.join(os.environ.get("TEMP", "."), NODE_MSI_NAME)
        last_err = None
        for url in NODE_MSI_URLS:
            try:
                self.log("下载源：" + url)
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                got = 0
                next_report = 0
                with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
                    cl = resp.headers.get("Content-Length")
                    total = int(cl) if cl else 0
                    while True:
                        self.check_cancel()
                        chunk = resp.read(131072)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        mb = got / 1048576
                        if mb >= next_report:
                            next_report = int(mb) + 1
                            tail = f"/{total / 1048576:.0f}MB" if total else ""
                            self.status(f"正在下载 Node.js 离线包… {mb:.1f}MB{tail}")
                if total and got < total:
                    raise IOError("下载不完整")
                self.log(f"下载完成：{dest}（{got / 1048576:.1f} MB）", "ok")
                return dest
            except OpCancelled:
                raise
            except Exception as e:
                last_err = e
                self.log(f"该下载源失败：{e}", "warn")
        raise RuntimeError(
            f"所有下载源均失败（{last_err}）。请检查网络，或手动把 {NODE_MSI_NAME} "
            f"放到本 exe 同目录后再试。")

    # ---- Codex CLI ----
    def set_execution_policy(self):
        """解除 PowerShell 脚本运行限制（npm/codex 的命令入口是 .ps1，
        Windows 默认策略为 Restricted，会导致“禁止运行脚本”报错）。
        管理员时设置 LocalMachine，否则退回 CurrentUser（无需管理员）。"""
        self.status("正在解除 PowerShell 脚本运行限制…")
        ps = shutil.which("powershell") or "powershell"

        def get_policy_list():
            rc, out = run_quiet([ps, "-NoProfile", "-Command",
                                 "Get-ExecutionPolicy -List"], timeout=30)
            result = {}
            if rc == 0:
                for line in out.splitlines():
                    mm = re.match(r"\s*(\w+)\s+(Undefined|Restricted|AllSigned|"
                                  r"RemoteSigned|Unrestricted|Bypass)\s*$", line)
                    if mm:
                        result[mm.group(1)] = mm.group(2)
            return result

        tried = []
        if is_admin():
            tried.append("LocalMachine")
            rc, out = run_quiet([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                                 "Set-ExecutionPolicy -Scope LocalMachine "
                                 "-ExecutionPolicy RemoteSigned -Force"], timeout=60)
        else:
            rc, out = 1, ""
        if rc != 0:
            tried.append("CurrentUser")
            rc, out = run_quiet([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                                 "Set-ExecutionPolicy -Scope " + tried[-1] +
                                 " -ExecutionPolicy RemoteSigned -Force"], timeout=60)
        self.log("已执行：Set-ExecutionPolicy RemoteSigned（作用域 "
                 + "、".join(tried) + "）")

        policies = get_policy_list()
        gpo = policies.get("MachinePolicy") or policies.get("UserPolicy")
        if gpo and gpo != "Undefined":
            self.log(f"检测到组策略已固定 PowerShell 执行策略为 {gpo}"
                     f"（允许运行脚本），无需再修改。", "ok")
            return
        effective = policies.get("CurrentUser") or "Undefined"
        if effective in ("RemoteSigned", "Unrestricted", "Bypass"):
            self.log(f"PowerShell 脚本限制已解除（当前用户策略：{effective}），"
                     "codex 命令可以正常运行。", "ok")
        else:
            self.log(f"设置执行策略未完全生效（当前用户策略：{effective}）。",
                     "warn")
            self.log("不影响本工具安装（npm 由 node 直接调用）；"
                     "若之后在 PowerShell 运行 codex 报“禁止运行脚本”，"
                     "请以管理员身份手动执行：Set-ExecutionPolicy RemoteSigned", "warn")

    def install_codex(self, info):
        node_exe, npm_js = info["npm_node"], info["npm_cli"]
        env = make_env(info["node_dir"])
        if info.get("codex_ver"):
            self.log(f"检测到 Codex CLI 已存在（版本 {info['codex_ver']}），将重新安装以确保最新。",
                     "warn")

        self.set_execution_policy()

        attempts = [
            ("npmmirror 国内镜像", ["--registry=" + MIRROR_REGISTRY], MIRROR_TIMEOUT_SEC),
            ("npm 官方源", [], OFFICIAL_TIMEOUT_SEC),
        ]
        for name, extra_args, limit in attempts:
            label = f"正在通过{name}安装 Codex CLI …"
            self.status(label)
            self.log(label)
            cmd = [node_exe, npm_js, "install", "-g", "--no-fund", "--no-audit"] \
                  + extra_args + [CODEX_PKG]
            t0 = time.time()
            timed_out = False
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW, env=env,
                    cwd=os.environ.get("TEMP") or None,
                )
            except Exception as e:
                self.log(f"启动 npm 失败：{e}", "err")
                continue

            def reader(pipe=proc.stdout):
                for line in iter(pipe.readline, b""):
                    s = decode_bytes(line).strip()
                    if s:
                        self.q.put(("log", "dim", s))

            th = threading.Thread(target=reader, daemon=True)
            th.start()

            rc_ = None
            last_sec = -1
            while True:
                rc_ = proc.poll()
                if rc_ is not None:
                    break
                if self.cancel.is_set():
                    kill_tree(proc.pid)
                    th.join(timeout=3)
                    raise OpCancelled()
                sec = int(time.time() - t0)
                if sec != last_sec:
                    last_sec = sec
                    self.q.put(("tick", sec))
                if sec > limit:
                    timed_out = True
                    kill_tree(proc.pid)
                    break
                time.sleep(0.25)
            th.join(timeout=5)

            if timed_out:
                self.log(f"{name}超过 {int(limit)} 秒仍未完成，准备切换下一来源重试。", "warn")
                continue
            if rc_ == 0:
                self.log(f"通过{name}安装成功。", "ok")
                break
            self.log(f"{name}安装失败（退出码 {rc_}）。", "warn")
        else:
            raise RuntimeError("两个来源均未能安装 Codex CLI，请检查网络（防火墙/代理）后重试。")

        new_info = detect()
        ver = new_info.get("codex_ver")
        shim = new_info.get("codex_shim")
        if not ver:
            raise RuntimeError("npm 报告安装成功，但未找到 @openai/codex 包信息。")
        self.log(f"Codex CLI 安装完成，版本 {ver}", "ok")
        if shim:
            self.log(f"命令入口：{shim}")
        self.log("使用方法：打开【新的】PowerShell 或 CMD 窗口，输入 codex 即可启动；"
                 "首次使用前需设置 OPENAI_API_KEY 环境变量。", "ok")


# ---------------------------------------------------------------- GUI -------

import tkinter as tk
from tkinter import messagebox, ttk

BG = "#F1F5F9"
CARD = "#FFFFFF"
BORDER = "#E2E8F0"
TXT = "#0F172A"
SUB = "#64748B"
PRIMARY = "#2563EB"
PRIMARY_D = "#1D4ED8"
GREEN_BG, GREEN_FG = "#DCFCE7", "#166534"
RED_BG, RED_FG = "#FEE2E2", "#991B1B"
AMBER_FG = "#B45309"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE + " · " + APP_VENDOR)
        root.geometry("700x650")
        root.minsize(640, 590)
        root.configure(bg=BG)
        try:
            ico = res_path("installer.ico")
            if ico:
                root.iconbitmap(ico)
        except Exception:
            pass

        self.q = queue.Queue()
        self.worker = Installer(self.q)
        self.busy = False
        self.base_status = ""
        self._final_shown = False

        self._build_ui()
        self._startup_notice()
        self.root.after(150, lambda: threading.Thread(target=self._detect_job,
                                                      daemon=True).start())
        self._poll_queue()

    def _startup_notice(self):
        """启动时告知用户建议使用管理员模式运行。"""
        if is_admin():
            self._append_log("✓ 已以管理员身份运行，安装过程将最顺畅。", "ok")
            return
        self._append_log("⚠ 当前未以管理员身份运行。建议关闭后右键本程序 →"
                         "【以管理员身份运行】，以确保各步骤顺利完成。", "warn")
        self.root.after(400, self._suggest_admin)

    def _suggest_admin(self):
        try:
            ans = messagebox.askyesno(
                "建议使用管理员模式",
                "当前程序未以管理员身份运行。\n\n"
                "以管理员模式运行可以确保 Node.js 静默安装、PowerShell 执行策略设置"
                "等步骤顺利完成（否则安装 Node.js 时会单独弹出授权窗口）。\n\n"
                "是否立即以管理员身份重新启动？",
                parent=self.root)
        except Exception:
            return
        if ans:
            if relaunch_as_admin():
                self.root.destroy()
                return
            messagebox.showwarning(
                "未能以管理员身份重启",
                "可能是取消了授权或系统策略限制，将继续以普通权限运行。",
                parent=self.root)
        self._append_log("以普通权限继续：安装 Node.js 时会单独弹出授权窗口，请点【是】。",
                         "warn")

    # ---------- UI 构建 ----------
    def _card(self, title=None):
        c = tk.Frame(self.root, bg=CARD, highlightbackground=BORDER,
                     highlightthickness=1, padx=14, pady=10)
        c.pack(fill="x", padx=14, pady=(10, 0))
        if title:
            tk.Label(c, text=title, bg=CARD, fg=TXT,
                     font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        return c

    def _build_ui(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", pady=(12, 0), padx=4)
        tk.Label(head, text=APP_TITLE, bg=BG, fg=TXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left", padx=10)
        admin = is_admin()
        tk.Label(head, text=("✓ 当前已以管理员模式运行" if admin else
                             "⚠ 未以管理员运行：建议右键 → 以管理员身份运行本程序"),
                 bg="#ECFDF5" if admin else "#FFF7ED",
                 fg=GREEN_FG if admin else AMBER_FG,
                 font=("Microsoft YaHei UI", 9, "bold" if not admin else "normal"),
                 padx=10, pady=4
                 ).pack(side="right", padx=10)

        # ① 检测状态卡
        card = self._card("① 环境检测")
        grid = tk.Frame(card, bg=CARD)
        grid.pack(fill="x", side="top", anchor="w", pady=(4, 2))
        self.rows = {}
        for i, (key, name) in enumerate([("node", "Node.js"), ("npm", "npm"),
                                         ("codex", "Codex CLI")]):
            tk.Label(grid, text=name, bg=CARD, fg=TXT,
                     font=("Microsoft YaHei UI", 10)).grid(row=i, column=0, sticky="w",
                                                           padx=(2, 10), pady=3)
            badge = tk.Label(grid, text="检测中…", bg="#E2E8F0", fg=SUB,
                             font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=2)
            badge.grid(row=i, column=1, sticky="w")
            detail = tk.Label(grid, text="", bg=CARD, fg=SUB,
                              font=("Microsoft YaHei UI", 9))
            detail.grid(row=i, column=2, sticky="w", padx=12)
            grid.columnconfigure(2, weight=1)
            self.rows[key] = (badge, detail)
        btn_recheck = tk.Button(card, text="↻ 重新检测", command=self.on_detect_click,
                                font=("Microsoft YaHei UI", 9), bg="#F8FAFC", fg=TXT,
                                relief="groove", activebackground="#EEF2FF",
                                bd=1, padx=10, cursor="hand2")
        btn_recheck.pack(anchor="ne", side="bottom")

        # ② 操作卡
        card2 = self._card("② 开始安装")
        self.big_btn = tk.Button(card2, text="一键安装 Node.js 和 Codex CLI",
                                 font=("Microsoft YaHei UI", 11, "bold"),
                                 bg=PRIMARY, fg="white", activebackground=PRIMARY_D,
                                 activeforeground="white", relief="flat", cursor="hand2",
                                 disabledforeground="#93C5FD",
                                 padx=16, pady=9, command=lambda: self.start_task(True, True))
        self.big_btn.pack(fill="x", pady=(6, 8))

        row = tk.Frame(card2, bg=CARD)
        row.pack(fill="x")
        small_opts = dict(font=("Microsoft YaHei UI", 9), relief="groove", bd=1,
                          bg="#F8FAFC", fg=TXT, activebackground="#EEF2FF",
                          disabledforeground="#94A3B8", cursor="hand2")
        self.btn_node_only = tk.Button(row, text="仅安装 Node.js", padx=10, pady=6,
                                       command=lambda: self.start_task(True, False),
                                       **small_opts)
        self.btn_codex_only = tk.Button(row, text="仅安装 Codex CLI", padx=10, pady=6,
                                        command=lambda: self.start_task(False, True),
                                        **small_opts)
        self.btn_cancel = tk.Button(row, text="取消", padx=14, pady=6,
                                    font=("Microsoft YaHei UI", 9, "bold"),
                                    bg="#FEF2F2", fg=RED_FG, relief="groove", bd=1,
                                    state=tk.DISABLED, disabledforeground="#DC2626",
                                    cursor="hand2", command=self.on_cancel)
        self.btn_node_only.pack(side="left")
        self.btn_codex_only.pack(side="left", padx=8)
        self.btn_cancel.pack(side="right")
        tk.Label(card2, text="镜像策略：npmmirror ≥5 分钟未完成 → 自动切换 npm 官方源重试",
                 bg=CARD, fg=SUB, font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(8, 0))

        # 进度卡
        card3 = self._card()
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Installer.Horizontal.TProgressbar", thickness=8,
                        background=PRIMARY, troughcolor="#E2E8F0", borderwidth=0)
        self.bar = ttk.Progressbar(card3, mode="indeterminate", maximum=24,
                                   style="Installer.Horizontal.TProgressbar")
        self.bar.pack(fill="x", pady=(2, 6))
        row3 = tk.Frame(card3, bg=CARD)
        row3.pack(fill="x")
        self.lbl_status = tk.Label(row3, text="就绪。正在检测本机环境…", bg=CARD, fg=TXT,
                                   font=("Microsoft YaHei UI", 10), anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)

        # 版权页脚（点击查看关于）
        foot = tk.Label(self.root, text=f"© 2026 {APP_VENDOR}",
                        bg=BG, fg=SUB, font=("Microsoft YaHei UI", 8),
                        cursor="hand2")
        foot.pack(side="bottom", pady=(2, 5))
        foot.bind("<Button-1>", self._about)

        # ③ 日志卡
        card4 = tk.Frame(self.root, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=1, padx=10, pady=8)
        card4.pack(fill="both", expand=True, padx=14, pady=(10, 12))
        log_head = tk.Frame(card4, bg=CARD)
        log_head.pack(fill="x")
        tk.Label(log_head, text="③ 详细日志", bg=CARD, fg=TXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Button(log_head, text="清空日志", font=("Microsoft YaHei UI", 8),
                  bg="#F8FAFC", relief="groove", bd=1, cursor="hand2",
                  command=self._clear_log).pack(side="right")
        self.txt = tk.Text(card4, height=10, bg=CARD, fg=TXT, font=("Consolas", 9),
                           wrap="word", relief="flat", state=tk.DISABLED, takefocus=0)
        self.txt.pack(fill="both", expand=True, side="left")
        sb = tk.Scrollbar(card4, command=self.txt.yview)
        sb.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=sb.set)
        for tag, color in [("ok", GREEN_FG), ("warn", AMBER_FG), ("err", "#DC2626"),
                           ("dim", SUB), ("normal", TXT)]:
            self.txt.tag_configure(tag, foreground=color)

        self._append_log("欢迎使用 Node.js + Codex CLI 一键安装器。", "ok")
        self._append_log("Node.js 使用内置离线安装包（无需联网）；Codex CLI 通过 npm 联网安装，"
                         "优先 npmmirror 镜像。", "normal")
        self._append_log(f"© 2026 {APP_VENDOR} · 本程序仅供个人学习与分享使用", "dim")

    def _about(self, event=None):
        messagebox.showinfo(
            "关于本程序",
            f"Node.js + Codex CLI 一键安装器  v{APP_VERSION}\n\n"
            f"© 2026 {APP_VENDOR} · 版权所有\n"
            f"作者主页：{_wm()}\n\n"
            f"本程序由 {APP_VENDOR} 制作并分享，仅供个人学习使用，\n"
            f"转载/二次分发请保留版权声明。",
            parent=self.root)

    # ---------- 日志 ----------
    def _append_log(self, text, tag="normal"):
        stamp = time.strftime("%H:%M:%S ")
        self.txt.configure(state="normal")
        was_end = self.txt.yview()[1] > 0.98
        self.txt.insert("end", stamp + text.replace("\n", "\n          ") + "\n", tag)
        if was_end:
            self.txt.see("end")
        self.txt.configure(state="disable")

    def _clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disable")

    # ---------- 动作 ----------
    def on_detect_click(self):
        threading.Thread(target=self._detect_job, daemon=True).start()

    def _detect_job(self):
        idle = (not self.busy) and (not self._final_shown)
        if idle:
            self.q.put(("status", "正在检测本机环境…"))
        info = detect()
        self.q.put(("info", info))
        if idle:
            self.q.put(("status", "检测完成。点击上方按钮即可开始安装。"))

    def start_task(self, want_node: bool, want_codex: bool):
        if self.busy:
            return
        self.busy = True
        self._final_shown = False
        self.big_btn.configure(state=tk.DISABLED)
        self.btn_node_only.configure(state=tk.DISABLED)
        self.btn_codex_only.configure(state=tk.DISABLED)
        self.btn_cancel.configure(state="normal")
        self.bar.start(40)
        parts = []
        if want_node:
            parts.append("Node.js")
        if want_codex:
            parts.append("Codex CLI")
        task = "+".join(parts)
        self._append_log(f"—— 开始安装：{task} ——", "ok")
        self.worker_thread = threading.Thread(target=self.worker.run,
                                              args=(want_node, want_codex), daemon=True)
        self.worker_thread.start()

    def on_cancel(self):
        self.worker.cancel.set()
        self._append_log("收到取消请求…", "warn")

    # ---------- 检测结果渲染 ----------
    def render_info(self, info):
        def badge(key, text, kind):
            colors = {"ok": (GREEN_BG, GREEN_FG), "bad": (RED_BG, RED_FG),
                      "na": ("#E2E8F0", SUB)}[kind]
            b, _d = self.rows[key]
            b.configure(text=text, bg=colors[0], fg=colors[1])

        has_node = bool(info.get("node_dir") and info.get("node_ver"))
        badge("node", f"✓ v{info['node_ver']}" if has_node else "✗ 未安装",
              "ok" if has_node else "bad")
        _, d1 = self.rows["node"]
        d1.configure(text=info.get("node_dir") or "")

        has_npm = bool(info.get("npm_ver"))
        badge("npm", f"✓ v{info['npm_ver']}" if has_npm else "✗ 不可用",
              "ok" if has_npm else "bad")
        _, d2 = self.rows["npm"]
        d2.configure(text=info.get("npm_prefix") or "")

        cod_v = info.get("codex_ver")
        badge("codex", f"✓ v{cod_v}" if cod_v else "✗ 未安装", "ok" if cod_v else "bad")
        _, d3 = self.rows["codex"]
        d3.configure(text=info.get("codex_shim") or "")

    # ---------- 队列轮询 ----------
    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    _, tag, text = msg
                    self._append_log(text, tag)
                elif kind == "status":
                    self.base_status = msg[1]
                    self.lbl_status.configure(text=msg[1])
                elif kind == "tick":
                    lbl = self.base_status.split("（")[0] if self.base_status else ""
                    if lbl:
                        self.lbl_status.configure(text=f"{lbl}（已进行 {msg[1]} 秒）")
                elif kind == "info":
                    self.render_info(msg[1])
                elif kind == "done":
                    _, ok, summary = msg
                    self.bar.stop()
                    self.busy = False
                    self.btn_cancel.configure(state=tk.DISABLED)
                    self.big_btn.configure(state="normal")
                    self.btn_node_only.configure(state="normal")
                    self.btn_codex_only.configure(state="normal")
                    final = ("✔ 已完成：" if ok else "⚠ 已结束：") + summary
                    self.base_status = final
                    self._final_shown = True
                    self.lbl_status.configure(text=final)
                    # 结束后自动刷新一次检测结果
                    self.on_detect_click()
        except queue.Empty:
            pass
        except Exception:
            pass  # 单条消息处理异常不能拖垮 after 循环
        self.root.after(90, self._poll_queue)


def main():
    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    except Exception:
        err = traceback.format_exc()
        try:
            log_file = os.path.join(os.environ.get("TEMP", "."), "NodeCodexSetup_crash.log")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(time.strftime("\n==== %Y-%m-%d %H:%M:%S ====\n") + err)
        except Exception:
            pass
        try:
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(APP_TITLE + " 启动失败", err[-1500:])
        except Exception:
            print(err, file=sys.stderr)


if __name__ == "__main__":
    main()
