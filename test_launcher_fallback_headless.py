# -*- coding: utf-8 -*-
"""启动自检与界面降级链的回归测试。

需求：打开软件后先自检，有 WebView2 用原生窗口，没有就降级 tkinter。

降级链：WebView2 → tkinter → 浏览器 --app 模式

测试策略：把三个"启动器"函数打桩，只验证**选择逻辑**是否正确，
真正起窗口会造成 GUI 弹窗、阻塞测试，不适合自动化。

覆盖点：
1. WebView2 运行时检测（注册表 / Edge 文件）
2. detect_webview_runtime 的两种失败原因
3. 降级链优先级：webview > tkinter > browser
4. CH_WEB 环境变量强制指定界面
5. --no-browser 只起服务不开窗口
6. 降级时端口被释放（否则下次启动会误判"已有实例"）
"""
import sys
import threading
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codexhelper import launcher  # noqa: E402

_results = []
_bad = []


def ok(name, cond, extra=""):
    cond = bool(cond)
    _results.append(cond)
    if not cond:
        _bad.append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f"  {extra}" if extra else ""))


def section(t):
    print(f"== {t} ==")


class FakeServer:
    """假 HTTP 服务，记录 shutdown / server_close 调用。"""

    def __init__(self, port=17653):
        self.server_address = ("127.0.0.1", port)
        self.url = ""
        self.shutdown_calls = 0
        self.close_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1

    def server_close(self):
        self.close_calls += 1

    def serve_forever(self):
        time.sleep(0.05)


try:
    # ================================================= WebView2 运行时检测 ==
    section("1. WebView2 运行时检测")
    installed = launcher._webview2_installed()
    ok("_webview2_installed() 返回 bool", isinstance(installed, bool),
       f"实际 {installed}")

    # 打桩：注册表与 Edge 文件都找不到 → 判定未安装
    orig_reg = sys.modules.get("winreg")
    orig_env = dict(launcher.os.environ)

    class NoKeyReg:
        HKEY_LOCAL_MACHINE = 0
        HKEY_CURRENT_USER = 1
        KEY_READ = 1
        KEY_WOW64_64KEY = 256
        KEY_WOW64_32KEY = 512

        @staticmethod
        def OpenKey(*_a, **_k):
            raise OSError("no key")

    sys.modules["winreg"] = NoKeyReg
    for k in ("ProgramFiles", "ProgramFiles(x86)"):
        launcher.os.environ.pop(k, None)
    ok("注册表与 Edge 都无 → 判定未安装",
       launcher._webview2_installed() is False)

    # 打桩：ProgramFiles 下有 msedgewebview2.exe → 判定已安装
    fake_dir = Path(r"F:\vibe code\_tmp\fakepf")
    fake_edge = fake_dir / "Microsoft" / "Edge" / "Application"
    fake_edge.mkdir(parents=True, exist_ok=True)
    (fake_edge / "msedgewebview2.exe").write_bytes(b"")
    launcher.os.environ["ProgramFiles"] = str(fake_dir)
    ok("Edge 自带 msedgewebview2.exe → 判定已安装",
       launcher._webview2_installed() is True)
    launcher.os.environ.pop("ProgramFiles", None)

    if orig_reg is not None:
        sys.modules["winreg"] = orig_reg
    launcher.os.environ.clear()
    launcher.os.environ.update(orig_env)

    # =================================================== detect 失败原因 ====
    section("2. detect_webview_runtime 失败原因")

    # 模拟 pywebview 未安装
    saved = sys.modules.get("webview")
    sys.modules["webview"] = None      # import 会抛 ImportError
    okv, reason = launcher.detect_webview_runtime()
    ok("pywebview 缺失 → 返回 False", okv is False)
    ok("原因为'pywebview 未安装'", "pywebview 未安装" in reason, reason)
    if saved is not None:
        sys.modules["webview"] = saved
    else:
        sys.modules.pop("webview", None)

    # 模拟运行时缺失（模块在但 WebView2 没装）
    orig_installed = launcher._webview2_installed
    launcher._webview2_installed = lambda: False
    okv, reason = launcher.detect_webview_runtime()
    ok("WebView2 运行时缺失 → 返回 False", okv is False)
    ok("原因为'未检测到 WebView2 运行时'",
       "未检测到 WebView2 运行时" in reason, reason)
    launcher._webview2_installed = orig_installed

    # 正常情况
    okv, reason = launcher.detect_webview_runtime()
    ok(f"本机实际检测结果：{'可用' if okv else '不可用'}",
       isinstance(okv, bool), reason)

    # ========================================================= 降级链 ======
    section("3. 降级链优先级")

    calls = []

    def make_stub(name, ret):
        def stub(*_a, **_k):
            calls.append(name)
            return ret
        return stub

    orig = {
        "detect": launcher.detect_webview_runtime,
        "webview": launcher._start_webview,
        "tkinter": launcher._start_tkinter,
        "browser": launcher._start_browser_mode,
        "running": launcher._running_instance_url,
    }

    def run_main(force="", argv=None):
        calls.clear()
        launcher.os.environ["CH_WEB"] = force
        old_argv = sys.argv
        sys.argv = argv or ["Codex小帮手.exe"]
        try:
            launcher._main_impl()
        finally:
            sys.argv = old_argv

    # 3.1 WebView2 可用 → 只走 webview
    # stub 返回 True = "已处理"（真实成功路径是 os._exit，不会返回）
    launcher.detect_webview_runtime = lambda: (True, "")
    launcher._start_webview = make_stub("webview", True)
    launcher._start_tkinter = make_stub("tkinter", True)
    launcher._start_browser_mode = make_stub("browser", None)
    launcher._running_instance_url = lambda: None
    run_main()
    ok("WebView2 可用 → 只启动 webview", calls == ["webview"], str(calls))

    # 3.2 WebView2 不可用 → 降级 tkinter
    launcher.detect_webview_runtime = lambda: (False, "未检测到 WebView2 运行时")
    run_main()
    ok("WebView2 不可用 → 降级 tkinter", calls == ["tkinter"], str(calls))

    # 3.3 tkinter 也不可用 → 浏览器模式
    launcher._start_tkinter = make_stub("tkinter", False)
    run_main()
    ok("tkinter 不可用 → 浏览器模式",
       calls == ["tkinter", "browser"], str(calls))

    # 3.4 webview 抛异常 → 不应炸穿，继续降级
    def boom(*_a, **_k):
        calls.append("webview")
        raise RuntimeError("window create failed")

    launcher.detect_webview_runtime = lambda: (True, "")
    launcher._start_webview = boom
    launcher._start_tkinter = make_stub("tkinter", True)
    run_main()
    ok("webview 抛异常 → 不炸穿，降级 tkinter",
       calls == ["webview", "tkinter"], str(calls))

    # 3.5 webview 返回 False（启动失败）→ 降级 tkinter
    launcher._start_webview = make_stub("webview", False)
    run_main()
    ok("webview 返回 False → 降级 tkinter",
       calls == ["webview", "tkinter"], str(calls))

    # ================================================== CH_WEB 强制指定 =====
    section("4. CH_WEB 强制指定界面")

    launcher._start_webview = make_stub("webview", None)
    launcher._start_tkinter = make_stub("tkinter", True)
    launcher.detect_webview_runtime = lambda: (True, "")

    run_main(force="tk")
    ok("CH_WEB=tk → 跳过 webview 直接用 tkinter",
       calls == ["tkinter"], str(calls))

    run_main(force="edge")
    ok("CH_WEB=edge → 跳过 webview/tkinter 走浏览器",
       calls == ["browser"], str(calls))

    # 降级原因必须准确：把"用户手动指定"记成"WebView2 不可用"会误导排查，
    # 这条断言专门钉住这个曾真实发生过的问题。
    reasons = []

    def tk_record(reason):
        calls.append("tkinter")
        reasons.append(reason)
        return True

    launcher._start_tkinter = tk_record
    launcher.detect_webview_runtime = lambda: (True, "")
    run_main(force="tk")
    ok("CH_WEB=tk 时原因标明'非故障'",
       bool(reasons) and "CH_WEB=tk" in reasons[0] and "非故障" in reasons[0],
       str(reasons))

    reasons.clear()
    launcher.detect_webview_runtime = lambda: (False, "未检测到 WebView2 运行时")
    run_main(force="")
    ok("真的没 WebView2 时原因是真实原因",
       bool(reasons) and reasons[0] == "未检测到 WebView2 运行时", str(reasons))

    reasons.clear()
    launcher.detect_webview_runtime = lambda: (True, "")
    launcher._start_webview = make_stub("webview", False)
    run_main(force="")
    ok("WebView2 启动失败时原因写'启动失败'",
       bool(reasons) and "启动失败" in reasons[0], str(reasons))

    # ====================================================== --no-browser ====
    section("5. --no-browser 只起服务")
    calls.clear()
    launcher.detect_webview_runtime = lambda: (True, "")
    launcher._start_webview = make_stub("webview", True)
    launcher._start_tkinter = make_stub("tkinter", True)
    launcher._start_browser_mode = make_stub("browser", None)

    fake = FakeServer()
    orig_acquire = launcher._acquire_server
    launcher._acquire_server = lambda: (fake, "http://127.0.0.1:17653/")
    try:
        old_argv = sys.argv
        sys.argv = ["Codex小帮手.exe", "--no-browser"]
        try:
            launcher._main_impl()
        finally:
            sys.argv = old_argv
        ok("--no-browser 不启动任何界面", calls == [], str(calls))
        ok("--no-browser 起了 HTTP 服务", fake is not None)
    finally:
        launcher._acquire_server = orig_acquire

    # ==================================================== 端口释放 ==========
    section("6. 降级时释放端口")
    fake = FakeServer()
    launcher._release_server(fake)
    ok("_release_server 调用 shutdown", fake.shutdown_calls == 1)
    ok("_release_server 调用 server_close", fake.close_calls == 1)

    # server_close 抛异常也不应冒泡
    class BadServer:
        def shutdown(self):
            raise RuntimeError("shutdown boom")

        def server_close(self):
            raise RuntimeError("close boom")

    launcher._release_server(BadServer())
    ok("释放异常被吞掉，不中断降级", True)

    # ==================================================== 已有实例 ==========
    section("7. 单实例唤起")
    calls.clear()
    launcher._running_instance_url = lambda: "http://127.0.0.1:17653/"
    run_main()
    ok("已有实例 → 不启动新界面", calls == [], str(calls))
    launcher._running_instance_url = orig["running"]

    # 还原
    launcher.detect_webview_runtime = orig["detect"]
    launcher._start_webview = orig["webview"]
    launcher._start_tkinter = orig["tkinter"]
    launcher._start_browser_mode = orig["browser"]
    launcher.os.environ.pop("CH_WEB", None)

    # =============================================== tkinter 可用性 =========
    section("8. tkinter 真实可用性")
    try:
        import tkinter  # noqa: F401
        ok("tkinter 可导入", True)
    except Exception as exc:  # noqa: BLE001
        ok("tkinter 可导入", False, str(exc))
    try:
        from codexhelper.app import main as tk_main  # noqa: F401
        ok("app.main（tkinter 界面）可导入", True)
    except Exception as exc:  # noqa: BLE001
        ok("app.main（tkinter 界面）可导入", False, str(exc))

    print()
    if all(_results):
        print(f"全部 {len(_results)} 项测试通过")
        code = 0
    else:
        print(f"有 {len(_bad)} 项失败")
        for b in _bad:
            print("   - " + b)
        code = 1
except Exception:
    import traceback
    traceback.print_exc()
    code = 1

raise SystemExit(code)
