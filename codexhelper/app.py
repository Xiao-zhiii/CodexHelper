# -*- coding: utf-8 -*-
"""应用壳：窗口骨架（标题/分页/状态条/日志/页脚）、忙碌状态机、队列轮询。
分页只负责自己的界面与动作，跨分页的状态（忙碌/按钮加载/日志/进度）都在这里。"""
import queue
import threading
import time
import traceback

import tkinter as tk
from tkinter import messagebox, ttk

from . import theme
from .constants import APP_TITLE, APP_VENDOR, APP_VERSION
from .installer import Installer
from .theme import Spinner, f
from .util import is_admin, relaunch_as_admin, res_path


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE + " · " + APP_VENDOR)
        # 窗口高度自适应屏幕：小屏幕（如 1366x768 的 Win10 笔记本）不超屏，
        # 保证底部日志区完整可见
        scr_h = root.winfo_screenheight()
        win_h = max(520, min(680, scr_h - 120))
        root.geometry(f"700x{win_h}")
        root.minsize(640, 520)
        root.configure(bg=theme.BG)
        try:
            ico = res_path("installer.ico")
            if ico:
                root.iconbitmap(ico)
        except Exception:
            pass

        self.q = queue.Queue()
        self.worker = Installer(self.q)
        self.busy = False
        self._detecting = False
        self.base_status = ""
        self._final_shown = False
        # 加载动效内部状态
        self._skeleton_after = None      # 骨架屏脉冲循环
        self._skeleton_phase = 0
        self._btn_loading = None         # (btn, 原文本) Button Loading 目标
        self._btn_loading_text = ""
        self._btn_dots = 0
        self._btn_after = None           # 按钮省略号动画循环
        # 分页注册表
        self.route = {}                  # 消息名 → 分页处理函数
        self.action_buttons = []         # 忙碌时统一禁用的按钮
        self.cancel_button = None
        self.skeleton_rows = []          # 参与骨架呼吸的徽章表 {key: (badge, detail)}
        self.on_done = None              # 任务结束后的钩子（由分页①注册）
        # 日志控件创建前的缓冲（分页构建时可能已写欢迎日志）
        self._log_buffer = []

        def _buffered(text, tag="normal"):
            self._log_buffer.append((text, tag))

        self._log_append = _buffered
        self._clear_log = lambda: None

        self._build_ui()
        self._startup_notice()
        self.root.after(150, lambda: threading.Thread(target=self._initial_detect,
                                                      daemon=True).start())
        self._poll_queue()

    def _initial_detect(self):
        """启动时让分页①执行首次检测（detect_job 会发 detect_begin/info/gpt_info）。"""
        try:
            tab = getattr(self, "_tab_install", None)
            if tab:
                tab.detect_job()
        except Exception:
            pass

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

    # ---------- UI ----------
    def _build_ui(self):
        # pack 顺序 = 空间分配顺序：页脚、标题、分页容器先拿到各自请求高度，
        # 日志卡与状态卡随后从底边堆叠；窗口高度不足时由最后 pack 的状态卡
        # 吸收压缩，保证分页内的操作按钮、说明文字永远完整可见。
        foot = tk.Label(self.root, text=f"© 2026 {APP_VENDOR} · 点击查看关于",
                        bg=theme.BG, fg=theme.SUB_DARK, font=f(9),
                        cursor="hand2")
        foot.pack(side="bottom", pady=(2, 4))
        foot.bind("<Button-1>", self._about)

        head = tk.Frame(self.root, bg=theme.BG)
        head.pack(fill="x", pady=(8, 0), padx=4)
        tk.Label(head, text=APP_TITLE, bg=theme.BG, fg=theme.TXT,
                 font=f(15, bold=True)).pack(side="left", padx=10)
        admin = is_admin()
        tk.Label(head, text=("✓ 当前已以管理员模式运行" if admin else
                             "⚠ 未以管理员运行：建议右键 → 以管理员身份运行本程序"),
                 bg="#ECFDF5" if admin else "#FFF7ED",
                 fg=theme.GREEN_FG if admin else theme.AMBER_FG,
                 font=f(9, bold=not admin), padx=10, pady=4
                 ).pack(side="right", padx=10)

        # 分页容器
        theme.setup_styles()
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 0))
        pages = [(" 安装 · 插件修复 ", "tab_install"),
                 (" ChatGPT 启动修复 ", "tab_gptfix"),
                 (" 桌面端 降级 / 升级 ", "tab_appx"),
                 (" Codex 环境检测 ", "tab_env")]
        for text, mod in pages:
            frame = tk.Frame(self.nb, bg=theme.BG)
            self.nb.add(frame, text=text)
            if mod == "tab_install":
                from .tabs.tab_install import TabInstall
                self._tab_install = TabInstall(self, frame)
            elif mod == "tab_gptfix":
                from .tabs.tab_gptfix import TabGptFix
                self._tab_gptfix = TabGptFix(self, frame)
            elif mod == "tab_appx":
                from .tabs.tab_appx import TabAppx
                self._tab_appx = TabAppx(self, frame)
            elif mod == "tab_env":
                from .tabs.tab_env import TabEnv
                self._tab_env = TabEnv(self, frame)

        # 底部容器：状态卡（进度条）与日志卡。放进同一容器是为了控制压缩顺序——
        # 窗口高度不足时（如“桌面端 降级 / 升级”分页内容较高），容器内先 pack 的
        # 状态卡优先保住（下载进度必须可见），日志卡吸收剩余空间并自带滚动。
        bottom = tk.Frame(self.root, bg=theme.BG)
        bottom.pack(side="bottom", fill="both", expand=True)

        # ③ 日志卡（容器内后 pack、expand：剩余空间全给日志）
        # 日志控件创建前，分页构建可能已经写欢迎日志——先缓冲，创建后回放。
        log_card, log_append, log_clear = theme.log_widget(bottom, height=3)
        log_card.pack(side="top", fill="both", expand=True, padx=14, pady=(0, 4))
        pending, self._log_buffer = self._log_buffer, None
        for text, tag in (pending or []):
            log_append(text, tag)
        self._log_append = log_append
        self._clear_log = log_clear

        # 状态/进度条（所有分页共用；容器内先 pack = 优先拿到高度，
        # 视觉上位于日志卡上方）
        card3 = tk.Frame(bottom, bg=theme.CARD, highlightbackground=theme.BORDER,
                         highlightthickness=1, padx=14, pady=8)
        card3.pack(side="top", fill="x", padx=14, pady=(6, 0))
        # 进度条只用于“可计算进度”（如离线包下载，determinate 真实百分比）；
        # 时长未知的等待一律由左侧环形 Spinner 表达，避免同一任务双指示器。
        self.bar = ttk.Progressbar(card3, mode="determinate", maximum=100,
                                   style=theme.PROGRESS_STYLE)
        self.bar.pack(fill="x", pady=(2, 2))
        row3 = tk.Frame(card3, bg=theme.CARD)
        row3.pack(fill="x")
        self.spinner = Spinner(row3, size=16, ring=3)
        self.spinner.pack(side="left", padx=(0, 8))
        self.lbl_status = tk.Label(row3, text="就绪。正在检测本机环境…", bg=theme.CARD,
                                   fg=theme.TXT, font=f(10), anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)

    def _about(self, event=None):
        from .constants import _wm
        messagebox.showinfo(
            "关于本程序",
            f"Codex 小帮手  v{APP_VERSION}\n"
            f"—— Node.js + Codex CLI 一键安装 · Codex 插件一键修复\n\n"
            f"© 2026 {APP_VENDOR} · 版权所有\n"
            f"作者主页：{_wm()}\n\n"
            f"本程序由 {APP_VENDOR} 制作并分享，仅供个人学习使用，\n"
            f"转载/二次分发请保留版权声明。",
            parent=self.root)

    # ---------- 日志 ----------
    def _append_log(self, text, tag="normal"):
        stamp = time.strftime("%H:%M:%S ")
        self._log_append(stamp + text.replace("\n", "\n          ") + "\n", tag)

    # ---------- 忙碌状态机 ----------
    def start_task(self, fn, btn=None, loading_text="正在处理", log_title=None):
        """统一的任务入口：忙碌检查 → 全局禁用 → 被点按钮进入加载态 → 后台线程。
        fn 在后台线程执行，结束时必须 put ("done", ok, summary)。"""
        if self.busy:
            return
        self._final_shown = False
        self._set_busy(True)
        if btn is not None:
            self._set_button_loading(btn, loading_text)
        if log_title:
            self._append_log(log_title, "ok")
        self.worker.cancel.clear()
        self.worker._cancel_noted = False
        threading.Thread(target=fn, daemon=True).start()

    def _set_busy(self, busy: bool):
        """统一切换所有操作按钮的可用/禁用状态与加载指示。"""
        self.busy = busy
        st = tk.DISABLED if busy else "normal"
        for b in self.action_buttons:
            try:
                b.configure(state=st)
            except tk.TclError:
                pass
        if self.cancel_button is not None:
            self.cancel_button.configure(state="normal" if busy else tk.DISABLED)
        if busy:
            self.spinner.start()      # Spinner：时长未知，仅提示系统正在处理
        else:
            self.spinner.stop()
            self.bar.configure(value=0)
            self._restore_buttons()

    # ---------- Button Loading ----------
    def _set_button_loading(self, btn, text):
        """按钮文字变为“text+动态省略号”，配合禁用态防止重复点击。"""
        self._restore_buttons()
        if btn is None:
            return
        self._btn_loading = (btn, str(btn.cget("text")))
        self._btn_loading_text = text
        self._btn_dots = 0
        self._animate_button()

    def _animate_button(self):
        if not self._btn_loading:
            return
        btn, _orig = self._btn_loading
        try:
            btn.configure(text=self._btn_loading_text + "." * self._btn_dots)
            self._btn_dots = (self._btn_dots + 1) % 4
            self._btn_after = self.root.after(400, self._animate_button)
        except tk.TclError:
            self._btn_loading = None
            self._btn_after = None

    def _restore_buttons(self):
        """结束加载态：还原被点击按钮的原始文字。"""
        if self._btn_after is not None:
            try:
                self.root.after_cancel(self._btn_after)
            except Exception:
                pass
            self._btn_after = None
        if self._btn_loading:
            btn, orig = self._btn_loading
            try:
                btn.configure(text=orig)
            except tk.TclError:
                pass
            self._btn_loading = None

    # ---------- Skeleton ----------
    def _start_skeleton(self):
        if self._skeleton_after is None:
            self._pulse_skeleton()

    def _pulse_skeleton(self):
        self._skeleton_phase ^= 1
        bg = theme.SKELETON_1 if self._skeleton_phase else theme.SKELETON_2
        for rows in self.skeleton_rows:
            for badge, _d in rows.values():
                try:
                    badge.configure(bg=bg)
                except tk.TclError:
                    pass
        self._skeleton_after = self.root.after(420, self._pulse_skeleton)

    def _stop_skeleton(self):
        if self._skeleton_after is not None:
            try:
                self.root.after_cancel(self._skeleton_after)
            except Exception:
                pass
            self._skeleton_after = None

    def _on_detect_done(self):
        """检测结束钩子（分页①回调里也会触发）。"""
        self._detecting = False
        self._stop_skeleton()

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
                elif kind == "progress":
                    # Progress Bar：仅用于可计算进度的阶段（离线包/镜像下载），
                    # None 表示该阶段结束、清零复位
                    frac = msg[1]
                    if frac is None:
                        self.bar.configure(value=0)
                    else:
                        self.bar.configure(mode="determinate",
                                           value=max(0.0, min(1.0, frac)) * 100)
                elif kind == "done":
                    _, ok, summary = msg
                    self._set_busy(False)
                    final = ("✔ 已完成：" if ok else "⚠ 已结束：") + summary
                    self.base_status = final
                    self._final_shown = True
                    self.lbl_status.configure(text=final)
                    if self.on_done:
                        try:
                            self.on_done()
                        except Exception:
                            pass
                else:
                    handler = self.route.get(kind)
                    if handler:
                        try:
                            handler(msg)
                        except Exception:
                            pass  # 单条消息处理异常不能拖垮 after 循环
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
            import os
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
            # 同 launcher.py：GUI 程序没有可见的 stderr，print 等于丢掉。
            # 崩溃兜底必须落到统一日志，否则排查时找不到任何线索。
            try:
                from .logs import write as _log_write
                _log_write("ERROR", "tkinter 界面启动失败：错误框也弹不出来",
                           traceback=err[-3000:])
            except Exception:
                pass
