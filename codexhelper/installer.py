# -*- coding: utf-8 -*-
"""后台任务编排：安装/修复主流程 + v1.5.0 新增的镜像安装与环境扫描任务。
所有方法都在后台线程运行，通过 self.q 发消息给 UI：
    ("log", tag, text) / ("status", text) / ("tick", n) / ("progress", frac|None)
    ("done", ok, summary) 及各分页注册的自定义消息（mirror_list / appx_info / env_report）
"""
import base64
import os
import re
import shutil
import subprocess
import threading
import time
import traceback

from . import mirror
from .constants import (APPX_DL_TIMEOUT_SEC, CODEX_PKG, CREATE_NO_WINDOW,
                        MIRROR_REGISTRY, MIRROR_TIMEOUT_SEC, MSI_TIMEOUT_SEC,
                        NODE_MSI_NAME, NODE_MSI_URLS, OFFICIAL_TIMEOUT_SEC)
from .codex_fix import (ensure_full_access, ensure_goal_prompt,
                        find_patch_skill, install_patch_skill)
from .gpt_fix import detect_gpt_env, find_codex_desktop, locate_codex_cli, restart_chatgpt_app
from .netenv import build_opener, detect_proxy, scan_codex_env
from .util import (OpCancelled, decode_bytes, get_version, kill_tree, locate_msi,
                   make_env, run_quiet)
from .winops import (_set_clipboard_text, find_new_console_window,  # noqa: F401
                     launch_codex_window, send_enter_to_window,
                     snapshot_windows, type_text_into_window)
from .constants import FIX_COMMAND, CODEX_BOOT_WAIT_SEC


class Installer:
    def __init__(self, q):
        self.q = q
        self.cancel = threading.Event()
        self._cancel_noted = False

    # ---- 消息 ----
    def log(self, text, tag="normal"):
        self.q.put(("log", tag, str(text)))

    def status(self, text):
        self.q.put(("status", text))

    def check_cancel(self):
        if self.cancel.is_set():
            raise OpCancelled()

    def _heartbeat(self, t0, last_ref):
        """长任务秒级心跳：返回更新后的 last 秒数。"""
        sec = int(time.time() - t0)
        if sec != last_ref[0]:
            last_ref[0] = sec
            self.q.put(("tick", sec))
        return sec

    # ================= 安装 Node.js / Codex CLI =================
    def run(self, want_node: bool, want_codex: bool):
        q = self.q
        try:
            self.cancel.clear()
            self._cancel_noted = False

            if want_node:
                info = detect_run()
                if info["node_dir"] and info["node_ver"]:
                    self.log(f"检测到本机已有 Node.js {info['node_ver']}，跳过 Node.js 安装。",
                             "ok")
                else:
                    self.install_node()

            if want_codex:
                info = detect_run()
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
        last_ref = [-1]
        rc = None
        while True:
            # 取消采用“软取消”：系统安装器无法安全中断，等它结束后再停止后续步骤
            if self.cancel.is_set() and not self._cancel_noted:
                self._cancel_noted = True
                self.log("已请求取消：将等待当前系统安装步骤结束后停止后续操作…", "warn")
            rc = proc.poll()
            if rc is not None:
                break
            sec = self._heartbeat(t0, last_ref)
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

        from .constants import COMMON_NODE_DIRS
        for d in COMMON_NODE_DIRS:
            node = os.path.join(d, "node.exe")
            if os.path.isfile(node):
                _, out = run_quiet([node, "--version"])
                self.log(f"已验证：node.exe 位于 {d}，版本 {get_version(out) or '?'}", "ok")
                return
        raise RuntimeError("安装程序返回成功，但未找到 node.exe，请重启电脑后再次运行本程序。")

    def download_msi(self):
        import urllib.request
        dest = os.path.join(os.environ.get("TEMP", "."), NODE_MSI_NAME)
        last_err = None
        for url in NODE_MSI_URLS:
            try:
                self.log("下载源：" + url)
                self.q.put(("progress", 0.0))
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                got = 0
                next_report = 0
                last_pct = -1
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
                        pct = int(got * 100 / total) if total else -1
                        if mb >= next_report or (pct >= 0 and pct != last_pct):
                            next_report = int(mb) + 1
                            last_pct = pct
                            if total:
                                # Progress Bar（determinate）+ 状态栏百分比
                                self.status(f"正在下载 Node.js 离线包… {mb:.1f}/"
                                            f"{total / 1048576:.0f}MB（{pct}%）")
                                self.q.put(("progress", got / total))
                            else:
                                self.status(f"正在下载 Node.js 离线包… {mb:.1f}MB")
                if total and got < total:
                    raise IOError("下载不完整")
                self.log(f"下载完成：{dest}（{got / 1048576:.1f} MB）", "ok")
                self.q.put(("progress", None))
                return dest
            except OpCancelled:
                raise
            except Exception as e:
                last_err = e
                self.log(f"该下载源失败：{e}", "warn")
        raise RuntimeError(
            f"所有下载源均失败（{last_err}）。请检查网络，或手动把 {NODE_MSI_NAME} "
            f"放到本 exe 同目录后再试。")

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
        from .util import is_admin
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
            last_ref = [-1]
            while True:
                rc_ = proc.poll()
                if rc_ is not None:
                    break
                if self.cancel.is_set():
                    kill_tree(proc.pid)
                    th.join(timeout=3)
                    raise OpCancelled()
                sec = self._heartbeat(t0, last_ref)
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

        new_info = detect_run()
        ver = new_info.get("codex_ver")
        shim = new_info.get("codex_shim")
        if not ver:
            raise RuntimeError("npm 报告安装成功，但未找到 @openai/codex 包信息。")
        self.log(f"Codex CLI 安装完成，版本 {ver}", "ok")
        if shim:
            self.log(f"命令入口：{shim}")
        self.log("使用方法：打开【新的】PowerShell 或 CMD 窗口，输入 codex 即可启动；"
                 "首次使用前需设置 OPENAI_API_KEY 环境变量。", "ok")

    # ================= Codex 插件修复 =================
    def run_fix(self):
        """一键修复 Codex 桌面端插件：
        ① 设置 Full Access 权限 ② 检测/安装 fast-patch 修复技能
        ③ 写入 /goal 自定义指令 ④ 打开 codex CLI 并自动输入 /goal 修复指令。"""
        q = self.q
        try:
            self.cancel.clear()
            self._cancel_noted = False

            self.status("正在检测 Codex CLI …")
            info = detect_run()
            if not (info.get("codex_shim") or shutil.which("codex")):
                raise RuntimeError(
                    "未检测到 Codex CLI。请先在上方安装 Codex CLI 后，再使用插件修复。")

            self.set_execution_policy()

            self.status("正在设置 Codex 权限为 Full Access …")
            ensure_full_access(self.log)

            self.status("正在检查修复技能 …")
            skill_dir = find_patch_skill()
            if skill_dir:
                self.log(f"修复技能已安装：{skill_dir}", "ok")
            else:
                self.log("本机未安装修复技能，开始从 GitHub 下载安装 …")
                install_patch_skill(self.log)

            ensure_goal_prompt(self.log)
            if _set_clipboard_text(FIX_COMMAND):
                self.log("修复提示词已复制到剪贴板（自动输入未成功时，"
                         "在 Codex 窗口内【鼠标右键】即可粘贴）。", "dim")

            marker = "Codex插件修复-" + time.strftime("%H%M%S")
            self.status("正在打开 Codex CLI 窗口 …")
            before = snapshot_windows()
            launch_codex_window(marker, make_env(info.get("node_dir")),
                                cwd=os.path.expanduser("~"))
            self.log("Codex CLI 正在新 PowerShell 窗口启动（Full Access 模式）。")

            hwnd = find_new_console_window(before, marker, timeout=25,
                                           cancel_event=self.cancel)
            if self.cancel.is_set():
                raise OpCancelled()
            if not hwnd:
                raise RuntimeError(
                    "未找到新打开的 Codex 窗口。请手动打开 PowerShell 输入 codex；"
                    "修复提示词已复制到剪贴板，在窗口内【鼠标右键】即可粘贴，"
                    "回车开始修复。")

            for s in range(CODEX_BOOT_WAIT_SEC, 0, -1):
                self.check_cancel()
                self.status(f"Codex 启动中… {s} 秒后自动输入 /goal 修复指令")
                time.sleep(1)

            # codex 启动时可能先显示“是否信任当前目录”确认页（1. Yes / 2. No），
            # 先发一次回车确认（若已直接进入主界面，空的回车不会有任何影响），
            # 等 TUI 切换完成后再键入 /goal 修复指令。
            if send_enter_to_window(hwnd):
                self.log("已发送目录信任确认（如出现）。")
                time.sleep(3)
            # 不用 Ctrl+V：codex TUI 把 Ctrl+V 绑定为“粘贴剪贴板图片”，
            # 会报 “no image on clipboard” 且文本进不去（Win10 传统控制台尤甚）。
            # 改为逐字符键入，等效人工打字，两种控制台都适用。
            if type_text_into_window(hwnd, FIX_COMMAND):
                self.log("已自动键入 /goal 修复指令并回车，请在 Codex 窗口中确认执行。",
                         "ok")
                self.log("若窗口内未出现输入内容：修复提示词已复制到剪贴板，"
                         "点击该窗口【鼠标右键】即可粘贴（注意不要按 Ctrl+V，"
                         "codex 会把它当作粘贴图片），回车开始修复。", "dim")
                q.put(("done", True, "插件修复已发起，请查看弹出的 Codex 窗口"))
            else:
                self.log("自动输入未成功。修复提示词已复制到剪贴板。", "warn")
                self.log("请点击刚打开的 Codex（PowerShell）窗口 → 【鼠标右键】即可粘贴"
                         "→ 按回车开始修复（注意：不要按 Ctrl+V，codex 会把它"
                         "当作粘贴图片）。", "warn")
                q.put(("fix_manual", None))
                q.put(("done", False, "提示词已复制，请到 Codex 窗口右键粘贴并回车"))
        except OpCancelled:
            self.log("操作已被用户取消（已打开的 Codex 窗口不受影响）。", "warn")
            q.put(("done", False, "已取消"))
        except Exception as e:
            self.log("发生错误：" + str(e), "err")
            self.log(traceback.format_exc(limit=3), "err")
            q.put(("done", False, "失败：" + str(e)))

    # ================= ChatGPT 启动修复 =================
    def run_fix_gpt(self, restart=True):
        """修复 ChatGPT 桌面应用启动报错：
        定位 OpenAI.Codex 桌面包内的 codex.exe → 写入用户环境变量
        CODEX_CLI_PATH → 重启 ChatGPT 应用。"""
        q = self.q
        try:
            self.cancel.clear()
            self._cancel_noted = False

            self.status("正在检测 OpenAI.Codex 桌面应用 …")
            pkg = find_codex_desktop(self.log)
            if not pkg:
                raise RuntimeError(
                    "本机未安装 OpenAI.Codex 桌面应用（ChatGPT）。"
                    "请先从 Microsoft Store 安装后再使用本修复。")
            self.log(f"已找到 ChatGPT 桌面应用：v{pkg['version']}", "ok")
            self.log(f"安装位置：{pkg['location']}")

            self.status("正在定位 codex CLI 二进制 …")
            cli = locate_codex_cli(pkg["location"])
            if not cli:
                raise RuntimeError(
                    "桌面包内与 npm 全局包中均未找到 codex.exe。"
                    "请先在本工具【安装 · 插件修复】页安装 Codex CLI 后重试。")
            self.log(f"Codex CLI 二进制：{cli}", "ok")

            self.status("正在写入 CODEX_CLI_PATH 环境变量 …")
            from .util import set_user_env
            if not set_user_env("CODEX_CLI_PATH", cli, self.log):
                raise RuntimeError(
                    "写入用户环境变量 CODEX_CLI_PATH 失败，请以管理员身份运行本工具后重试。")
            self.log("已写入用户环境变量：CODEX_CLI_PATH = " + cli, "ok")

            q.put(("gpt_info", detect_gpt_env()))

            if restart:
                self.status("正在重启 ChatGPT 应用 …")
                if restart_chatgpt_app(self.log):
                    self.log("ChatGPT 应用已重启，请查看是否正常启动。", "ok")
                else:
                    self.log("请手动完全关闭并重新打开 ChatGPT 应用，修复即可生效。",
                             "warn")
            else:
                self.log("修复完成。请完全关闭并重新打开 ChatGPT 应用。", "ok")

            q.put(("done", True, "ChatGPT 启动修复完成"
                   + ("，应用已重启" if restart else "")))
        except OpCancelled:
            self.log("操作已被用户取消。", "warn")
            q.put(("done", False, "已取消"))
        except Exception as e:
            self.log("发生错误：" + str(e), "err")
            self.log(traceback.format_exc(limit=3), "err")
            q.put(("done", False, "失败：" + str(e)))

    # ================= 桌面端降级/升级（v1.5.0）=================
    def detect_appx(self):
        """检测当前 OpenAI.Codex 桌面端版本并发给 UI。"""
        try:
            self.q.put(("appx_info", find_codex_desktop(self.log)))
        except Exception as e:
            self.log("检测桌面端版本失败：" + str(e), "warn")

    def run_fetch_mirror(self):
        """拉取 codex-app-mirror 的版本列表。先检测本机代理：
        有代理 → GitHub API 走代理；无代理 → 直连，失败再走代理兜底。"""
        q = self.q
        try:
            self.cancel.clear()
            self._cancel_noted = False
            self.detect_appx()

            proxy = detect_proxy()
            opener = None
            if proxy["enabled"]:
                opener = build_opener(proxy["url"])
                self.log(f"检测到{proxy['source']}：{proxy['server']}，下载将优先走代理。", "ok")
            else:
                self.log("未检测到系统代理（如网络不畅，可开启代理后重试）。", "dim")

            releases = mirror.fetch_releases(self.log, opener=opener,
                                             api_fallback_via=build_opener(detect_proxy()["url"]))
            q.put(("mirror_list", releases))
            q.put(("done", True, f"获取到 {len(releases)} 个镜像版本"))
        except OpCancelled:
            self.log("操作已被用户取消。", "warn")
            q.put(("done", False, "已取消"))
        except Exception as e:
            self.log("发生错误：" + str(e), "err")
            q.put(("done", False, "失败：" + str(e)))

    def run_appx_install(self, release):
        """下载所选版本的 MSIX → SHA256 校验 → 关闭 ChatGPT → 安装（允许降级）。"""
        q = self.q
        dest = None
        try:
            self.cancel.clear()
            self._cancel_noted = False

            proxy = detect_proxy()
            opener = build_opener(proxy["url"]) if proxy["enabled"] else None

            tag = release["tag"]
            msix = release.get("msix")
            sha_url = release.get("sha_url")
            expected = None
            if msix:
                url, fname = msix["url"], msix["name"]
                version = msix["version"]
            else:
                # 列表来自降级路径：从 SHA256SUMS-windows.txt 解析文件名与哈希
                if not sha_url:
                    raise RuntimeError("该版本缺少 SHA256SUMS 资产，无法解析文件名。")
                self.log("正在解析该版本的实际文件名（SHA256SUMS）…")
                fname, expected, _ = mirror.resolve_asset_from_sha(
                    opener, sha_url, tag, self.log)
                url = (f"https://github.com/{mirror.APPX_MIRROR_REPO}"
                       f"/releases/download/{tag}/{fname}")
                mm = re.search(r"_([\d.]+)_", fname)
                version = mm.group(1) if mm else "?"

            size_mb = (msix["size"] / 1048576) if msix else None
            size_note = f"约 {size_mb:.0f} MB" if size_mb else "体积较大（数百 MB）"
            self.log(f"目标版本：{version}（{tag}，{size_note}）")

            # ---- 下载（ghproxylist 优先 / 代理加持 / 直连兜底）----
            self.status(f"正在下载 Codex 桌面端 {version} …")
            dest = os.path.join(os.environ.get("TEMP", "."), fname)
            last_pct = [-1]

            def progress(got, total):
                if total:
                    pct = int(got * 100 / total)
                    if pct != last_pct[0]:
                        last_pct[0] = pct
                        self.status(f"正在下载 Codex 桌面端 {version}… "
                                    f"{got / 1048576:.1f}/{total / 1048576:.0f}MB（{pct}%）")
                        q.put(("progress", got / total))

            try:
                mirror.download_to(url, dest, opener=opener, log=self.log,
                                   progress=progress, cancel=self.cancel,
                                   timeout=60, max_seconds=APPX_DL_TIMEOUT_SEC)
            except KeyboardInterrupt:
                if dest and os.path.isfile(dest):
                    try:
                        os.remove(dest)
                    except OSError:
                        pass
                raise OpCancelled()
            finally:
                q.put(("progress", None))
            self.log("下载完成。", "ok")

            # ---- SHA256 校验（列表未带哈希时从 SHA256SUMS-windows.txt 现取）----
            if expected is None and sha_url:
                for cand in mirror.candidate_urls(sha_url):
                    try:
                        sha_text = mirror.http_get_bytes(
                            opener, cand, timeout=45).decode("utf-8", "replace")
                        for line in sha_text.splitlines():
                            parts_ = line.strip().split(None, 1)
                            if len(parts_) == 2 and \
                                    parts_[1].strip().lstrip("*") == fname:
                                expected = parts_[0].lower()
                                break
                        if expected:
                            break
                    except Exception as e:
                        self.log(f"获取 SHA256SUMS 失败（{cand[:60]}…）：{e}", "warn")
            if expected:
                self.status("正在校验 SHA256 …")
                actual = mirror.sha256_of(dest, progress=lambda g, t: None,
                                          cancel=self.cancel)
                if actual != expected:
                    raise RuntimeError(
                        f"SHA256 校验失败！文件可能损坏或被篡改。\n期望 {expected}\n实际 {actual}\n"
                        f"已保留文件：{dest}")
                self.log("SHA256 校验通过。", "ok")
            else:
                self.log("未获取到官方 SHA256（跳过校验，镜像源直出）。", "warn")

            # ---- 安装（降级需先卸载当前版本）----
            self.status(f"正在安装 Codex 桌面端 {version}（关闭 ChatGPT 后执行）…")
            mirror.close_desktop_app(self.log)

            pkg_now = find_codex_desktop(self.log)
            installed_v = pkg_now["version"] if pkg_now else None
            if mirror.needs_uninstall(version, installed_v):
                self.log(f"目标版本 {version} 低于当前 {installed_v}：先卸载当前版本再安装。"
                         "卸载只移除应用本体与其本地缓存，不会动 ~/.codex"
                         "（技能/配置/密钥等用户数据）；应用内登录状态需重装后重新登录。",
                         "warn")
                last_ref = [-1]
                t0u = time.time()

                def unins_progress(_sec, _total):
                    self._heartbeat(t0u, last_ref)

                ok_u, out_u = mirror.uninstall_desktop(
                    log=self.log, progress=unins_progress, cancel=self.cancel)
                if not ok_u:
                    self.log("卸载输出（末尾）：", "warn")
                    self.log(out_u, "dim")
                    raise RuntimeError(
                        "卸载当前版本失败，已中止降级（未做任何更改）。"
                        "可尝试手动在“设置 → 应用”卸载 ChatGPT 后重试。")
                self.log("当前版本已卸载。", "ok")

            self.log("正在执行 Add-AppxPackage 安装（含降级开关），约需 1~5 分钟…")
            last_ref = [-1]
            t0 = time.time()

            def install_progress(_sec, _total):
                self._heartbeat(t0, last_ref)

            ok, out = mirror.install_msix(dest, log=self.log,
                                          progress=install_progress,
                                          cancel=self.cancel)
            if not ok:
                self.log("Add-AppxPackage 输出（末尾）：", "warn")
                self.log(out, "dim")
                raise RuntimeError(
                    "MSIX 安装失败。常见原因：① 磁盘空间不足（需约 2× 安装包体积）；"
                    "② 包与系统架构不符；③ 系统策略限制。请截图日志反馈。")

            pkg = find_codex_desktop(self.log)
            q.put(("appx_info", pkg))
            ver_now = pkg["version"] if pkg else "?"
            q.put(("done", True, f"Codex 桌面端已切换到 v{ver_now}"))
            self.log(f"安装完成，当前版本：v{ver_now}", "ok")
            self.log("如 ChatGPT 未自动打开，可从开始菜单手动启动。", "dim")
        except OpCancelled:
            self.log("操作已被用户取消。", "warn")
            q.put(("done", False, "已取消"))
        except Exception as e:
            self.log("发生错误：" + str(e), "err")
            q.put(("done", False, "失败：" + str(e)))

    # ================= Codex 环境检测（v1.5.0）=================
    def run_env_scan(self):
        """扫描 ~/.codex 的 .env 与三级环境变量中的代理/密钥/Codex 条目。"""
        q = self.q
        try:
            self.cancel.clear()
            self._cancel_noted = False
            self.status("正在扫描 Codex 环境配置 …")
            report = scan_codex_env()
            q.put(("env_report", report))
            q.put(("done", True, "环境扫描完成"))
        except OpCancelled:
            q.put(("done", False, "已取消"))
        except Exception as e:
            self.log("发生错误：" + str(e), "err")
            q.put(("done", False, "失败：" + str(e)))


def detect_run():
    """延迟导入避免循环依赖：Installer → util.detect。"""
    from .util import detect
    return detect()
