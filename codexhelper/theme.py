# -*- coding: utf-8 -*-
"""设计令牌与控件工厂（v1.4.2 设计走查确立）。
改界面观感只动这个文件：色板、字体、按钮/卡片/徽章工厂都在这里。"""
import tkinter as tk
from tkinter import ttk

# ------------------------------------------------------------ 设计令牌 ----
FONT = "Microsoft YaHei UI"
MONO = "Consolas"

BG = "#F1F5F9"            # 窗口背景
CARD = "#FFFFFF"          # 卡片
BORDER = "#E2E8F0"        # 卡片描边
TXT = "#0F172A"           # 正文
SUB = "#64748B"           # 次级文字（白底）
SUB_DARK = "#475569"      # 次级文字（浅灰底，保证对比度）
PRIMARY = "#2563EB"       # 主色（可交互）
PRIMARY_D = "#1D4ED8"
GREEN_BG, GREEN_FG = "#DCFCE7", "#166534"
RED_BG, RED_FG = "#FEE2E2", "#991B1B"
AMBER_FG = "#B45309"
CHIP, CHIP_HOVER = "#F1F5F9", "#E2E8F0"          # 次级扁平按钮
CHIP_BLUE, CHIP_BLUE_HOVER = "#EFF6FF", "#DBEAFE"  # 蓝色调 chip
CHIP_RED, CHIP_RED_HOVER = "#FEF2F2", "#FEE2E2"    # 危险色 chip
SKELETON_1, SKELETON_2 = "#E2E8F0", "#F8FAFC"     # 骨架屏呼吸两端色
DISABLED_FG = "#94A3B8"

PROGRESS_STYLE = "CH.Horizontal.TProgressbar"


def f(size, bold=False, mono=False):
    """字体快捷构造：(family, size[, bold])。"""
    fam = MONO if mono else FONT
    return (fam, size, "bold") if bold else (fam, size)


def setup_styles():
    """ttk 全局样式（clam）：扁平标签页 + 进度条。"""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(PROGRESS_STYLE, thickness=8, background=PRIMARY,
                    troughcolor=BORDER, borderwidth=0)
    style.configure("TNotebook", background=BG, borderwidth=0,
                    tabmargins=(14, 6, 14, 0))
    style.configure("TNotebook.Tab", font=f(10, bold=True), padding=(18, 6),
                    background=CHIP, foreground=SUB,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.map("TNotebook.Tab",
              background=[("selected", CARD)],
              foreground=[("selected", PRIMARY_D)],
              expand=[("selected", (1, 1, 1, 0))])


# ------------------------------------------------------------ 控件工厂 ----

def card(parent, title=None, padx=14, pady=10):
    """白底描边卡片；title 给定时在左上角加粗标题。"""
    c = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                 highlightthickness=1, padx=padx, pady=pady)
    c.pack(fill="x", padx=14, pady=(10, 0))
    if title:
        tk.Label(c, text=title, bg=CARD, fg=TXT,
                 font=f(10, bold=True)).pack(anchor="w")
    return c


def chip(parent, text, command, size=9, bold=False, padx=12, pady=6,
         fg=TXT, bg=CHIP, hover=CHIP_HOVER, wrap=False):
    """次级扁平按钮（悬停有反馈）。"""
    b = tk.Button(parent, text=text, command=command, font=f(size, bold=bold),
                  bg=bg, fg=fg, relief="flat", bd=0,
                  activebackground=hover, activeforeground=fg,
                  disabledforeground=DISABLED_FG, cursor="hand2",
                  padx=padx, pady=pady)
    return b


def primary(parent, text, command, size=11, pady=7):
    """主操作按钮（蓝底白字）。"""
    return tk.Button(parent, text=text, command=command, font=f(size, bold=True),
                     bg=PRIMARY, fg="white", activebackground=PRIMARY_D,
                     activeforeground="white", relief="flat", cursor="hand2",
                     disabledforeground="#93C5FD", padx=16, pady=pady)


def badge(parent, text="检测中…"):
    """检测状态徽章（灰色骨架占位，后续按结果上色）。"""
    return tk.Label(parent, text=text, bg=SKELETON_1, fg=SUB,
                    font=f(9, bold=True), padx=10, pady=2)


def badge_colors(kind):
    """ok/bad/na → (bg, fg)。"""
    return {"ok": (GREEN_BG, GREEN_FG), "bad": (RED_BG, RED_FG),
            "na": (BORDER, SUB)}[kind]


def badge_row(parent, names):
    """创建多行『名称 + 徽章 + 详情』网格。返回 {key: (badge, detail)}。"""
    grid = tk.Frame(parent, bg=CARD)
    grid.pack(fill="x", side="top", anchor="w", pady=(4, 2))
    rows = {}
    for i, (key, name) in enumerate(names):
        tk.Label(grid, text=name, bg=CARD, fg=TXT, font=f(10)).grid(
            row=i, column=0, sticky="w", padx=(2, 10), pady=2)
        b = badge(grid)
        b.grid(row=i, column=1, sticky="w")
        d = tk.Label(grid, text="", bg=CARD, fg=SUB, font=f(9))
        d.grid(row=i, column=2, sticky="w", padx=12)
        grid.columnconfigure(2, weight=1)
        rows[key] = (b, d)
    return grid, rows


def set_badge(b, text, kind):
    """按 ok/bad/na 给徽章上色。"""
    bg, fg = badge_colors(kind)
    b.configure(text=text, bg=bg, fg=fg)


def hint(parent, text, pady=(4, 0)):
    """卡内说明文字（9pt 次级色，自动换行）。"""
    tk.Label(parent, text=text, bg=CARD, fg=SUB, font=f(9),
             wraplength=600, justify="left").pack(anchor="w", pady=pady)


def mono_block(parent, height=8):
    """只读等宽文本块（日志/检测结果），自带滚动条与彩色 tag。返回 (text, append, clear)。"""
    wrap = tk.Frame(parent, bg=CARD)
    txt = tk.Text(wrap, height=height, bg=CARD, fg=TXT, font=f(9, mono=True),
                  wrap="word", relief="flat", state=tk.DISABLED, takefocus=0)
    tag_colors = {"ok": GREEN_FG, "warn": AMBER_FG, "err": "#DC2626",
                  "dim": SUB, "normal": TXT, "title": PRIMARY_D}
    for tag, color in tag_colors.items():
        txt.tag_configure(tag, foreground=color)
    sb = tk.Scrollbar(wrap, command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    txt.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    def append(text, tag="normal"):
        txt.configure(state="normal")
        was_end = txt.yview()[1] > 0.98
        txt.insert("end", text + "\n", tag)
        if was_end:
            txt.see("end")
        txt.configure(state="disable")

    def clear():
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.configure(state="disable")

    return wrap, append, clear


def log_widget(parent, height=3):
    """底部共用日志区：标题行 + 清空按钮 + 等宽文本。返回 (frame, append, clear)。"""
    frame = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                     highlightthickness=1, padx=10, pady=6)
    head = tk.Frame(frame, bg=CARD)
    head.pack(fill="x")
    tk.Label(head, text="③ 详细日志", bg=CARD, fg=TXT,
             font=f(10, bold=True)).pack(side="left")
    txt, append, clear = mono_block(frame, height=height)
    clear_btn = chip(head, "清空日志", clear, padx=10, pady=2)
    clear_btn.pack(side="right")
    txt.pack(fill="both", expand=True, side="left")
    return frame, append, clear


class Spinner(tk.Canvas):
    """环形加载指示器（纯 tkinter canvas，无需图片资源）。
    - start()/stop()：indeterminate 模式，弧段匀速旋转，用于时长未知的等待；
    - set_progress(frac)：determinate 模式，按 0~1 直接填充，适合小空间展示
      明确进度（当前界面未用到 determinate，备用，见交接文档“加载动效清单”）。"""

    def __init__(self, master, size=16, ring=3, color=PRIMARY, bg=CARD):
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        pad = ring // 2 + 1
        bbox = (pad, pad, size - pad, size - pad)
        self._trough = self.create_arc(bbox, start=0, extent=359.9, style="arc",
                                       outline=BORDER, width=ring)
        self._arc = self.create_arc(bbox, start=90, extent=90, style="arc",
                                    outline=color, width=ring)
        self._angle = 90
        self._after_id = None
        self._set_visible(False)   # 空闲时整个隐藏，避免误读为“卡住的加载”

    def _set_visible(self, on):
        st = "normal" if on else "hidden"
        for item in (self._trough, self._arc):
            self.itemconfigure(item, state=st)

    def start(self):
        self._set_visible(True)
        if self._after_id is None:
            self._spin()

    def stop(self):
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._set_visible(False)

    def set_progress(self, frac):
        """determinate：frac∈[0,1]，同时停止旋转。"""
        self.stop()
        frac = max(0.0, min(1.0, float(frac)))
        self.itemconfigure(self._arc, start=90, extent=359.9 * frac)

    def _spin(self):
        try:
            self._angle = (self._angle - 15) % 360
            self.itemconfigure(self._arc, start=self._angle)
            self._after_id = self.after(40, self._spin)
        except tk.TclError:
            self._after_id = None   # 窗口已销毁，结束动画循环
