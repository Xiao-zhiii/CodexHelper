# -*- coding: utf-8 -*-
"""分页③：Codex 桌面端 降级 / 升级（v1.5.0 新增）。
从 Wangnov/codex-app-mirror 镜像获取版本列表：
下载先走 ghproxylist.com 加速（国内友好），检测到系统代理则全程走代理，
SHA256 校验通过后 Add-AppxPackage 安装（支持 -ForceUpdateFromAnyVersion 降级）。"""
import threading

import tkinter as tk
from tkinter import ttk

from .. import mirror, theme
from ..constants import APPX_ARCH, APPX_MIRROR_REPO
from ..theme import card, chip, hint, set_badge
from .base import Tab


class TabAppx(Tab):
    def build(self):
        app = self.app
        self.releases = []
        self.installed = None

        # ① 当前安装——标题行：标题居左，“检测当前版本”居右（显式行，保证同行显示）
        card1 = card(self.parent)
        head1 = tk.Frame(card1, bg=theme.CARD)
        head1.pack(fill="x")
        tk.Label(head1, text="① 当前安装", bg=theme.CARD, fg=theme.TXT,
                 font=theme.f(10, bold=True)).pack(side="left")
        self.btn_detect = chip(head1, "↻ 检测当前版本", self.on_detect_click, pady=4)
        self.btn_detect.pack(side="right")
        grid = tk.Frame(card1, bg=theme.CARD)
        grid.pack(fill="x", side="top", anchor="w", pady=(4, 2))
        self.b_ver = theme.badge(grid, "检测中…")
        self.b_ver.grid(row=0, column=0, sticky="w")
        self.d_ver = tk.Label(grid, text="OpenAI.Codex 桌面应用（即 ChatGPT / Codex Desktop）",
                              bg=theme.CARD, fg=theme.SUB, font=theme.f(9))
        self.d_ver.grid(row=0, column=1, sticky="w", padx=12)
        grid.columnconfigure(1, weight=1)

        # ② 镜像版本列表——标题行：标题居左，“获取列表”与状态文字居右
        card2 = card(self.parent)
        head2 = tk.Frame(card2, bg=theme.CARD)
        head2.pack(fill="x")
        tk.Label(head2, text=f"② 镜像版本（{APPX_MIRROR_REPO}）", bg=theme.CARD,
                 fg=theme.TXT, font=theme.f(10, bold=True)).pack(side="left")
        self.btn_fetch = chip(head2, "↻ 获取镜像版本列表", self.on_fetch_click, pady=4)
        self.btn_fetch.pack(side="right")
        self.lbl_sel = tk.Label(head2, text="尚未获取列表", bg=theme.CARD, fg=theme.SUB,
                                font=theme.f(9))
        self.lbl_sel.pack(side="right", padx=10)

        cols = ("version", "size", "date", "rel")
        listwrap = tk.Frame(card2, bg=theme.CARD)
        listwrap.pack(fill="x", pady=(8, 0))
        self.tree = ttk.Treeview(listwrap, columns=cols, show="headings", height=5,
                                 selectmode="browse")
        for cid, text, w, anchor in (
                ("version", "版本 (MSIX)", 150, "w"),
                ("size", "大小", 90, "e"),
                ("date", "发布日期", 100, "center"),
                ("rel", "与当前版本相比", 120, "center")):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=w, anchor=anchor)
        vsb = ttk.Scrollbar(listwrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="left", fill="y", padx=(6, 0))
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        self.btn_install = chip(card2, "⬇ 下载并安装所选版本（支持降级）",
                                self.on_install_click, size=10, bold=True, pady=8,
                                fg=theme.PRIMARY_D, bg=theme.CHIP_BLUE,
                                hover=theme.CHIP_BLUE_HOVER)
        self.btn_install.pack(fill="x", pady=(10, 0))
        self.btn_install.configure(state=tk.DISABLED, disabledforeground="#93C5FD")
        hint(card2, "通道：ghproxylist 加速优先 → 有系统代理则走代理 → 直连兜底，"
                    "下载后自动校验 SHA256；单版本约 800 MB。降级会先卸载当前版本"
                    "再安装（只移除应用本体，不影响 ~/.codex 用户数据），"
                    "安装会先关闭 ChatGPT。")

        app.action_buttons += [self.btn_fetch, self.btn_install]
        self.register("mirror_list", self.render_list)
        self.register("appx_info", self.render_info)

        # 启动时自动检测一次当前版本
        self.app.root.after(400, lambda: threading.Thread(
            target=self.on_detect_click, daemon=True).start())

    # ---------- 动作 ----------
    def on_detect_click(self):
        threading.Thread(target=self.app.worker.detect_appx,
                         daemon=True).start()

    def on_fetch_click(self):
        self.app.start_task(self.app.worker.run_fetch_mirror,
                            btn=self.btn_fetch, loading_text="正在获取",
                            log_title="—— 获取 Codex 桌面端镜像版本 ——")

    def on_install_click(self):
        sel = self.tree.selection()
        if not sel:
            self.log("请先在列表中选择一个版本。", "warn")
            return
        release = self.releases[int(sel[0])]
        self.app.start_task(lambda: self.app.worker.run_appx_install(release),
                            btn=self.btn_install, loading_text="正在下载安装",
                            log_title=f"—— 安装镜像版本 {release['tag']} ——")

    def on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        release = self.releases[int(sel[0])]
        msix = release.get("msix")
        ver = msix["version"] if msix else "安装时解析"
        self.lbl_sel.configure(text=f"已选：{ver}（{release['tag']}）")

    # ---------- 渲染 ----------
    def render_info(self, msg):
        pkg = msg[1]
        if pkg:
            set_badge(self.b_ver, f"✓ v{pkg['version']} · {APPX_ARCH}", "ok")
            self.d_ver.configure(text=pkg.get("location") or "")
            self.installed = pkg["version"]
        else:
            set_badge(self.b_ver, "✗ 未安装", "bad")
            self.d_ver.configure(text="未检测到 OpenAI.Codex 桌面应用")
            self.installed = None
        self.refresh_rel_column()

    def render_list(self, msg):
        self.releases = msg[1]
        self.tree.delete(*self.tree.get_children())
        for i, rel in enumerate(self.releases):
            msix = rel.get("msix")
            ver = msix["version"] if msix else "安装时解析"
            size = f"{msix['size'] / 1048576:.0f} MB" if msix else "—"
            self.tree.insert("", "end", str(i),
                             values=(ver, size, rel.get("published") or "—",
                                     self.relative_label(ver)))
        self.lbl_sel.configure(text=f"共 {len(self.releases)} 个版本，选择后点击下方按钮")

    def relative_label(self, ver):
        installed = getattr(self, "installed", None)
        if ver == "安装时解析" or not installed:
            return "—"
        cur, new = mirror.version_tuple(installed), mirror.version_tuple(ver)
        if new > cur:
            return "▲ 可升级"
        if new < cur:
            return "▼ 可降级"
        return "● 当前版本"

    def refresh_rel_column(self):
        for item in self.tree.get_children():
            vals = list(self.tree.item(item, "values"))
            vals[3] = self.relative_label(vals[0])
            self.tree.item(item, values=vals)

