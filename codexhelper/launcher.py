# -*- coding: utf-8 -*-
"""应用启动器（v1.6.0 起替代 tkinter 界面）：
启动本地 Web 服务 → 用 Edge/Chrome 以 App 模式打开页面 → 浏览器关闭后
空闲 45 秒自动退出。单实例：端口已被本工具占用时直接唤起已开页面。"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import urllib.request

from .constants import APP_TITLE
from .util import is_admin, relaunch_as_admin
from .webui import cfgcenter
from .webui.server import CHServer, RequestHandler, set_pusher

BASE_PORTS = (17653, 17654, 17655)   # 避开 Windows 保留端口段（Hyper-V 会整段排除）
IDLE_TIMEOUT_SEC = 45
PORT_FILE = (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
             / "CodexHelper" / "port.txt")


def _save_port(port: int):
    try:
        PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(str(port), encoding="utf-8")
    except Exception:
        pass


def _looks_like_ours(port: int) -> bool:
    """探测端口上是否已运行本工具（供单实例唤起判断）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as resp:
            server = resp.headers.get("Server", "")
            body = resp.read(64)
        return SERVER_BRAND.split("/")[0] in server or b"ok" in body
    except Exception:
        return False


def _running_instance_url() -> str | None:
    """读端口文件找已运行实例；ping 通过才认定。"""
    try:
        port = int(PORT_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    return f"http://127.0.0.1:{port}/" if _looks_like_ours(port) else None


def _try_bind(port: int) -> CHServer | None:
    try:
        return CHServer(("127.0.0.1", port), RequestHandler)
    except OSError:
        return None


def _acquire_server() -> tuple[CHServer | None, str]:
    """获取服务端口。返回 (server, url)：
    - server 非 None：新启动的服务（url 指向它）；
    - server 为 None：已有实例在跑（url 指向它，仅唤起页面）。
    端口策略：已有实例 → 首选固定端口 → 动态端口兜底
    （固定段可能落在 Windows 保留端口范围内，必须能动态兜底）。"""
    existing = _running_instance_url()
    if existing:
        return None, existing
    for port in BASE_PORTS:
        server = _try_bind(port)
        if server:
            _save_port(port)
            return server, f"http://127.0.0.1:{port}/"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = _try_bind(port)
    if server:
        _save_port(port)
        return server, f"http://127.0.0.1:{port}/"
    return None, "http://127.0.0.1:{port}/".format(port=BASE_PORTS[0])


def _log_line(message: str) -> None:
    """启动期日志：写到 exe 旁边的 Codex Helper.log（复用收编后端的 write_log）。"""
    try:
        cfgcenter.write_log("INFO", message)
    except Exception:
        pass


def open_browser(url: str) -> bool:
    """优先 Edge/Chrome 的 --app 模式（无地址栏，观感接近桌面应用）；
    失败回退系统默认浏览器。返回是否已尝试启动。"""
    launched = False
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates = [
            Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        for browser in candidates:
            try:
                if browser.exists():
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    subprocess.Popen([str(browser), f"--app={url}"],
                                     creationflags=creationflags)
                    _log_line(f"已启动浏览器：{browser.name} → {url}")
                    launched = True
                    break
            except OSError as exc:
                _log_line(f"启动 {browser} 失败：{exc}")
    if not launched:
        try:
            import webbrowser
            webbrowser.open(url)
            _log_line(f"已使用系统默认浏览器打开：{url}")
            launched = True
        except Exception as exc:
            _log_line(f"打开系统默认浏览器失败：{exc}")
    return launched


def monitor_idle(server: CHServer, timeout_seconds: int = IDLE_TIMEOUT_SEC,
                 window_mode: str = "browser") -> None:
    """空闲退出：界面关闭（无任何请求）后自动结束进程。
    browser 模式：首次连接前不计时，10s/25s 重试打开浏览器；
    webview 模式：窗口自己会连页面，无需重试（WebView2 首次初始化可能较慢，
    给 5 分钟宽限），超时未连接则退出。"""
    retries = 0
    grace = 300 if window_mode == "webview" else 600
    while True:
        time.sleep(5)
        now = time.time()
        if server.first_seen is None:
            age = now - server.boot_time
            if window_mode == "browser":
                if retries < 1 and age > 10:
                    retries += 1
                    _log_line("浏览器尚未连接，重试打开页面。")
                    open_browser(server.url)
                elif retries < 2 and age > 25:
                    retries += 2
                    _log_line("浏览器仍未连接，再次重试打开页面。")
                    open_browser(server.url)
            if age > grace:
                _log_line("长时间无任何连接，程序退出。")
                server.shutdown()
                return
            continue
        if now - server.first_seen > timeout_seconds:
            server.shutdown()
            return


def main() -> None:
    try:
        _main_impl()
    except SystemExit:
        raise
    except Exception:
        import os
        import traceback
        err = traceback.format_exc()
        try:
            log_file = os.path.join(os.environ.get("TEMP", "."), "NodeCodexSetup_crash.log")
            stamp = time.strftime("==== %Y-%m-%d %H:%M:%S ====")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("\n" + stamp + "\n" + err)
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(APP_TITLE + " 启动失败", err[-1500:])
        except Exception:
            print(err, file=sys.stderr)
        return


# --------------------------------------------------------- 界面自检逻辑 ----
# 需求：打开软件后先自检，有 WebView2 就用原生窗口，没有就降级 tkinter。
# 降级链：WebView2 → tkinter → 浏览器 --app 模式。
# 每一级降级原因都写进日志，避免"界面变了但不留痕迹"这种最难排查的情况。

_WV2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _webview2_installed() -> bool:
    """检测 WebView2 运行时是否已安装。

    三个来源任一命中即认为可用：
    1. 独立 WebView2 Runtime（注册表 EdgeUpdate\\Clients）
    2. Edge 自带的 msedgewebview2.exe

    非 Windows 平台不做检测，交回 pywebview 自己尝试。
    """
    if os.name != "nt":
        return True
    try:
        import winreg
    except ImportError:
        return True

    paths = tuple(
        base + "\\" + _WV2_GUID for base in (
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients",
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients",
        ))
    # 32/64 位视图都要看，运行时可能只装在其中一个
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for path in paths:
            for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view):
                        return True
                except OSError:
                    continue
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        d = os.environ.get(env)
        if d and (Path(d) / "Microsoft" / "Edge" / "Application"
                  / "msedgewebview2.exe").is_file():
            return True
    return False


def detect_webview_runtime() -> tuple[bool, str]:
    """自检 WebView2 是否可用。返回 (可用, 不可用原因)。"""
    try:
        import webview  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"pywebview 未安装（{exc}）"
    if not _webview2_installed():
        return False, "未检测到 WebView2 运行时"
    return True, ""


def _release_server(server) -> None:
    """降级时释放已绑定端口。

    不释放的话，下次启动会走"已有实例"分支去唤起一个不存在的服务。
    """
    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass


def _start_webview() -> bool:
    """启动 WebView2 原生窗口。正常退出时不会返回（os._exit）；失败返回 False。"""
    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        _log_line(f"pywebview 导入失败：{exc}")
        return False

    server, url = _acquire_server()
    if server is None:
        return True          # 自检期间被其它实例抢先启动，视为已处理
    server.url = url
    _log_line(f"服务已启动：{url}（管理员={is_admin()}）")

    if os.environ.get("CH_DEBUG"):
        import logging
        debug_log = os.path.join(os.environ.get("TEMP", "."), "ch_debug.log")
        logging.basicConfig(
            filename=debug_log, level=logging.DEBUG,
            format="%(asctime)s %(name)s %(message)s")
        _log_line("pywebview 调试日志 → " + debug_log)

    try:
        _log_line("正在创建 WebView2 原生窗口…")
        window = webview.create_window(
            APP_TITLE, url, width=1280, height=920, min_size=(980, 620))
        _log_line("窗口已创建，进入消息循环…")
    except Exception as exc:  # noqa: BLE001
        _log_line(f"创建 WebView2 窗口失败：{exc}")
        _release_server(server)
        return False

    # 关键：webview.start() 会阻塞主线程，HTTP 服务必须放进后台线程，
    # 否则端口只监听不 accept，页面请求永远挂起（窗口一直转圈）
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # 推送器：Python 每秒把任务状态直接推进页面（evaluate_js），
    # 不依赖页面定时器/轮询——WebView2 里它们可能被节流冻结
    def _pusher(payload):
        js = "window.__applyJob && window.__applyJob(" + \
            json.dumps(payload, ensure_ascii=False) + ")"
        try:
            window.evaluate_js(js)
        except Exception:
            pass

    try:
        set_pusher(_pusher)
        threading.Thread(target=monitor_idle, args=(server,),
                         kwargs={"window_mode": "webview"},
                         daemon=True).start()
        webview.start(debug=bool(os.environ.get("CH_DEBUG")))
    except Exception as exc:  # noqa: BLE001
        set_pusher(None)
        _log_line(f"WebView2 消息循环异常：{exc}")
        _release_server(server)
        return False

    set_pusher(None)
    _log_line("窗口已关闭，程序退出。")
    server.shutdown()
    server.server_close()
    os._exit(0)   # WebView2 后台线程可能延迟退出，确保干净收尾


def _start_tkinter(reason: str) -> bool:
    """降级到 tkinter 界面。用户关掉窗口后返回 True；不可用返回 False。

    已知降级：tkinter 界面只有 4 个分页（安装 / ChatGPT 修复 / 桌面端 /
    环境检测），没有 WebView2 版的"历史管理""日志"等分页。
    装上 WebView2 运行时后会自动恢复完整界面。

    即使走 tkinter，仍在后台起本地服务（不打开浏览器），
    这样 AI 依然能通过 /api/helper-status 等接口排查问题。
    """
    try:
        import tkinter  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        _log_line(f"tkinter 不可用：{exc}")
        return False

    server = None
    try:
        from .app import main as tk_main
        server, url = _acquire_server()
        if server is not None:
            server.url = url
            threading.Thread(target=server.serve_forever, daemon=True).start()
            _log_line(f"tkinter 界面已就绪，后台服务仍监听 {url}（供 AI 排查）")
        _log_line(f"启动 tkinter 界面（原因：{reason}）")
        tk_main()
    except Exception as exc:  # noqa: BLE001
        _log_line(f"tkinter 界面启动失败：{exc}")
        return False
    finally:
        if server is not None:
            _release_server(server)
    return True


def _start_browser_mode() -> None:
    """最终兜底：Edge/Chrome --app 模式。"""
    server, url = _acquire_server()
    if server is None:
        # 已有实例在跑，唤起即可
        threading.Timer(0.2, open_browser, args=(url,)).start()
        return
    server.url = url
    _log_line(f"浏览器模式：服务已启动 {url}")
    set_pusher(None)
    threading.Thread(target=monitor_idle, args=(server,),
                     kwargs={"window_mode": "browser"},
                     daemon=True).start()
    threading.Timer(0.3, open_browser, args=(url,)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _main_impl() -> None:
    args = sys.argv[1:]
    if "--self-test" in args:
        raise SystemExit(self_test())
    no_browser = "--no-browser" in args
    # CH_WEB 可强制某种界面，便于排查：webview / tk / edge
    force = os.environ.get("CH_WEB", "").strip().lower()

    # ---- 单实例：已有实例在跑就唤起它 ----
    existing = _running_instance_url()
    if existing:
        if not no_browser:
            threading.Timer(0.2, open_browser, args=(existing,)).start()
        _log_line(f"已有实例在运行，唤起页面：{existing}")
        return

    # ---- 只起服务不开窗口（AI 排查用）----
    if no_browser:
        server, url = _acquire_server()
        if server is None:
            return
        server.url = url
        _log_line(f"无窗口模式：服务已启动 {url}")
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return

    # ---- 启动自检：决定用哪种界面 ----
    wv_ok, wv_reason = detect_webview_runtime()
    _log_line("界面自检：WebView2 "
              + ("可用" if wv_ok else f"不可用（{wv_reason}）"))

    # 降级原因必须准确：日志写错原因比不写更坑人——曾经把"用户手动指定 tk"
    # 记成"WebView2 不可用"，排查时直接被带偏方向。
    if wv_ok and force not in ("edge", "tk"):
        # 返回 True 表示"已处理"（如自检期间被别的实例抢先启动）；
        # 返回 False 表示启动失败，需要降级。
        # 正常成功时 _start_webview 内部会 os._exit，根本不会返回到这里。
        try:
            handled = _start_webview()
        except Exception as exc:  # noqa: BLE001
            handled = False
            _log_line(f"WebView2 启动异常：{exc}")
        if handled:
            return
        tk_reason = "WebView2 启动失败，降级"
        _log_line("WebView2 未成功接管，尝试降级…")
    elif wv_ok:
        tk_reason = f"已由 CH_WEB={force} 指定（非故障）"
    else:
        tk_reason = wv_reason

    if force != "edge":
        if _start_tkinter(tk_reason):
            return
        _log_line("tkinter 界面也不可用，回退浏览器模式。")

    _start_browser_mode()


def self_test() -> int:
    import json
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    server = _try_bind(free_port)
    assert server is not None, "测试端口不可用"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    ok = True
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % server.server_address[1],
                                    timeout=5) as resp:
            ok &= resp.status == 200
        with urllib.request.urlopen("http://127.0.0.1:%d/" % server.server_address[1],
                                    timeout=10) as resp:
            html = resp.read().decode("utf-8")
            ok &= "Codex 小帮手" in html and "tab-install" in html
        with urllib.request.urlopen("http://127.0.0.1:%d/api/snapshot?sensitive=0"
                                    % server.server_address[1], timeout=60) as resp:
            snap = json.loads(resp.read().decode("utf-8"))
            ok &= all(k in snap for k in ("system", "config", "auth", "ccSwitch", "codexPlus"))
        with urllib.request.urlopen("http://127.0.0.1:%d/api/state"
                                    % server.server_address[1], timeout=10) as resp:
            state = json.loads(resp.read().decode("utf-8"))
            ok &= state["version"] and "is_admin" in state
        with urllib.request.urlopen("http://127.0.0.1:%d/api/helper-status"
                                    % server.server_address[1], timeout=10) as resp:
            hstatus = json.loads(resp.read().decode("utf-8"))
            ok &= hstatus.get("ok") and hstatus.get("pid") and hstatus.get("port")
    finally:
        server.shutdown()
        server.server_close()
    return 0 if ok else 1

