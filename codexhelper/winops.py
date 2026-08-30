# -*- coding: utf-8 -*-
"""Windows 窗口/输入操作：窗口查找定位、前台切换、剪贴板、SendInput 键入。"""
import ctypes
import subprocess
import time

from .constants import CREATE_NEW_CONSOLE

u = ctypes.windll.user32
k = ctypes.windll.kernel32

_KEYBOARD = 1                # INPUT_KEYBOARD
_KEYEVENTF_UNICODE = 0x0004
_KEYEVENTF_KEYUP = 0x0002


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


def find_window_by_title(substr, timeout=20, poll=0.3, cancel_event=None):
    """轮询查找标题包含 substr 的可见顶层窗口，返回 hwnd(int)；超时或取消返回 None。"""
    Proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    hits = []

    def on_window(hwnd, _lparam):
        if u.IsWindowVisible(hwnd):
            n = u.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                if substr in buf.value:
                    hits.append(int(hwnd or 0))
        return 1

    t0 = time.time()
    while True:
        del hits[:]
        u.EnumWindows(Proc(on_window), None)
        if hits:
            return hits[0]
        if cancel_event is not None and cancel_event.is_set():
            return None
        if time.time() - t0 >= timeout:
            return None
        time.sleep(poll)


def _set_clipboard_text(text) -> bool:
    """ctypes 写剪贴板（CF_UNICODETEXT），可在后台线程调用，不依赖 tkinter。
    注意：GlobalAlloc/GlobalLock/SetClipboardData 的句柄是 64 位，
    必须显式声明 restype/argtypes，否则会被按 32 位截断导致锁定失败。"""
    CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.restype = ctypes.c_void_p
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    opened = False
    for _ in range(10):          # 剪贴板可能被其它程序短暂占用，重试
        if u.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.1)
    if not opened:
        return False
    try:
        u.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)
        h = k.GlobalAlloc(GMEM_MOVEABLE, ctypes.sizeof(buf))
        if not h:
            return False
        p = k.GlobalLock(h)
        if not p:
            return False
        ctypes.memmove(p, buf, ctypes.sizeof(buf))
        k.GlobalUnlock(h)
        if not u.SetClipboardData(CF_UNICODETEXT, h):
            return False
        return True
    finally:
        u.CloseClipboard()


def _keybd(vk, up=False):
    ctypes.windll.user32.keybd_event(vk, 0, 2 if up else 0, 0)


def focus_window(hwnd) -> bool:
    """把窗口带到前台；成功返回 True。
    先用 ALT 敲击解除前台锁；不行再 AttachThreadInput 挂到前台线程的
    输入队列后强制切换（Win10 上对 SetForegroundWindow 的限制更严）。"""
    u.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = int(hwnd)

    def is_fg():
        return int(u.GetForegroundWindow() or 0) == hwnd

    for _ in range(2):
        u.ShowWindow(hwnd, 9)              # SW_RESTORE
        _keybd(0x12)
        _keybd(0x12, True)                 # 轻敲 ALT 解除前台切换限制
        u.SetForegroundWindow(hwnd)
        time.sleep(0.45)
        if is_fg():
            return True

    fg = int(u.GetForegroundWindow() or 0)
    if fg:
        fg_thread = u.GetWindowThreadProcessId(fg, None)
        cur = k.GetCurrentThreadId()
        u.AttachThreadInput(cur, fg_thread, True)
        try:
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
        finally:
            u.AttachThreadInput(cur, fg_thread, False)
        time.sleep(0.45)
        if is_fg():
            return True

    u.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    return is_fg()


def focus_and_paste(hwnd, text) -> bool:
    """把目标窗口带到前台，用剪贴板 + Ctrl+V 粘贴 text 后回车。
    仅在确认目标窗口已在前台时才粘贴，避免误输入到其它窗口。"""
    if not focus_window(hwnd):
        return False
    if not _set_clipboard_text(text):
        return False
    time.sleep(0.2)
    _keybd(0x11)
    _keybd(0x56)                           # Ctrl+V
    _keybd(0x56, True)
    _keybd(0x11, True)
    time.sleep(0.4)
    _keybd(0x0D)
    _keybd(0x0D, True)                     # 回车发送
    return True


def send_enter_to_window(hwnd) -> bool:
    """把窗口带到前台后发送一次回车（用于确认 codex 的目录信任提示；
    若 codex 已直接进入主界面，空的回车不会产生任何输入）。"""
    if not focus_window(hwnd):
        return False
    _keybd(0x0D)
    _keybd(0x0D, True)
    return True


def _send_unicode_char(ch) -> bool:
    """发送一个 Unicode 字符的按下+抬起事件（中文等 BMP 字符均支持）。"""
    code = ord(ch)
    if code > 0xFFFF:
        return False
    down = _INPUT()
    down.type = _KEYBOARD
    down.union.ki = _KEYBDINPUT(0, code, _KEYEVENTF_UNICODE, 0, None)
    up = _INPUT()
    up.type = _KEYBOARD
    up.union.ki = _KEYBDINPUT(0, code,
                              _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0, None)
    sent = u.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
    sent += u.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))
    return sent == 2


def type_text_into_window(hwnd, text, char_delay=0.012) -> bool:
    """把窗口带到前台后逐字符键入 text 并回车。
    仅在确认目标窗口已在前台时才输入，避免打字打到别的窗口。"""
    if not focus_window(hwnd):
        return False
    time.sleep(0.3)
    for ch in text:
        if not _send_unicode_char(ch):
            return False
        time.sleep(char_delay)
    time.sleep(0.3)
    _keybd(0x0D)
    _keybd(0x0D, True)                     # 回车提交
    return True


def launch_codex_window(marker, env=None, cwd=None):
    """新开一个 PowerShell 窗口运行 codex（Full Access 模式）。
    先用 $host.UI.RawUI.WindowTitle 把窗口标题设为 marker，便于按标题定位。
    注意：必须直接用 CREATE_NEW_CONSOLE 开窗口，不能经过
    `cmd /c start "标题" …`——列表参数被 list2cmdline 加引号后再经 cmd
    二次解析，start 会把带引号的标题误当成文件名。
    -NoExit：codex 退出后窗口保留，便于查看报错；
    -NoProfile -ExecutionPolicy Bypass：不受用户配置与执行策略影响。"""
    ps_cmd = ("$host.UI.RawUI.WindowTitle='" + marker + "'; "
              "codex --dangerously-bypass-approvals-and-sandbox")
    subprocess.Popen(
        ["powershell", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", ps_cmd],
        env=env, cwd=cwd, creationflags=CREATE_NEW_CONSOLE,
    )


CONSOLE_HOST_EXES = ("windowsterminal.exe", "openconsole.exe", "conhost.exe")


def _window_exe_name(hwnd) -> str:
    """返回窗口所属进程的 exe 小写文件名；取不到返回空串。"""
    import ctypes.wintypes as wt
    pid = wt.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    kh = k.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not kh:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wt.DWORD(260)
        if k.QueryFullProcessImageNameW(kh, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        k.CloseHandle(kh)


def snapshot_windows() -> set:
    """当前所有可见顶层窗口句柄集合（用于启动后差分出新窗口）。"""
    Proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    seen = set()

    def cb(hwnd, _lparam):
        if u.IsWindowVisible(hwnd):
            seen.add(int(hwnd or 0))
        return 1

    u.EnumWindows(Proc(cb), None)
    return seen


def find_new_console_window(before, marker, timeout=25, poll=0.25, cancel_event=None):
    """定位刚打开的 codex 控制台窗口。
    优先：在 before 快照之后新出现、且属于控制台宿主进程（Windows Terminal /
    conhost）的顶层窗口——codex TUI 会改写窗口标题，不能依赖标题；
    其次：标题含 marker 的可见窗口（新标签合并进已有 Windows Terminal 窗口时，
    窗口标题即焦点标签标题，marker 可见说明我们的标签正处于前台）。
    超时或取消返回 None。"""
    Proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    def scan():
        fresh, marked = [], None

        def cb(hwnd, _lparam):
            nonlocal marked   # 回调内重新绑定外层变量，必须声明，否则 EnumWindows 会被异常中断
            h = int(hwnd or 0)
            if not u.IsWindowVisible(h):
                return 1
            if h not in before:
                fresh.append(h)
            n = u.GetWindowTextLengthW(h)
            if n > 0 and marked is None:
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, buf, n + 1)
                if marker in buf.value:
                    marked = h
            return 1

        u.EnumWindows(Proc(cb), None)
        return fresh, marked

    t0 = time.time()
    while True:
        fresh, marked = scan()
        for h in fresh:
            if _window_exe_name(h) in CONSOLE_HOST_EXES:
                return h
        if marked is not None:
            return marked
        if cancel_event is not None and cancel_event.is_set():
            return None
        if time.time() - t0 >= timeout:
            return None
        time.sleep(poll)
