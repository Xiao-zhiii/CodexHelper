# -*- coding: utf-8 -*-
"""分页①：环境检测 + Node.js / Codex CLI 安装 + Codex 插件修复。"""
import threading

import tkinter as tk

from .. import theme
from ..theme import card, chip, hint, primary, badge_row, set_badge
from .base import Tab


class TabInstall(Tab):
    def build(self):
        app = self.app
        # ① 检测状态卡——“重新检测”与标题同行，节省纵向空间：
        # 分页内容总高超过窗口可用高度时 pack 会压缩卡片，底部内容（按钮行、
        # 说明文字）会被裁掉，因此尽量压缩各卡片的固定占用。
        card1 = card(self.parent, "① 环境检测")
        self.btn_recheck = chip(card1, "↻ 重新检测", self.on_detect_click, pady=4)
        self.btn_recheck.pack(side="right")
        _grid, self.rows = badge_row(card1, [("node", "Node.js"), ("npm", "npm"),
                                             ("codex", "Codex CLI")])
        app.skeleton_rows.append(self.rows)

        # ② 安装 / 修复卡
        card2 = card(self.parent, "② 安装 / 修复")
        self.big_btn = primary(card2, "一键安装 Node.js 和 Codex CLI",
                               lambda: self.start_install(True, True, self.big_btn))
        self.big_btn.pack(fill="x", pady=(4, 6))

        row = tk.Frame(card2, bg=theme.CARD)
        row.pack(fill="x")
        self.btn_node_only = chip(row, "仅安装 Node.js", pady=6,
                                  command=lambda: self.start_install(True, False,
                                                                     self.btn_node_only))
        self.btn_codex_only = chip(row, "仅安装 Codex CLI", pady=6,
                                   command=lambda: self.start_install(False, True,
                                                                      self.btn_codex_only))
        self.btn_cancel = chip(row, "取消", padx=14, size=9, bold=True,
                               fg=theme.RED_FG, bg=theme.CHIP_RED,
                               hover=theme.CHIP_RED_HOVER,
                               command=self.on_cancel)
        self.btn_cancel.configure(state=tk.DISABLED, disabledforeground="#DC2626")
        self.btn_node_only.pack(side="left")
        self.btn_codex_only.pack(side="left", padx=8)
        self.btn_cancel.pack(side="right")

        self.btn_fix = chip(card2, "🛠 一键修复 Codex 插件"
                            "（桌面端 Chrome / 浏览器 / Computer Use 插件失效）",
                            size=9, bold=True, pady=4,
                            fg=theme.PRIMARY_D, bg=theme.CHIP_BLUE,
                            hover=theme.CHIP_BLUE_HOVER,
                            command=self.on_fix_click)
        self.btn_fix.pack(fill="x", pady=(8, 0))
        hint(card2, "自动安装修复技能 → 设为 Full Access → 打开 Codex 输入 /goal")

        # 注册到全局忙碌状态机与消息路由
        app.action_buttons += [self.big_btn, self.btn_node_only,
                               self.btn_codex_only, self.btn_fix, self.btn_recheck]
        app.cancel_button = self.btn_cancel
        app.on_done = self.on_task_done
        self.register("detect_begin", self.on_detect_begin)
        self.register("info", self.render_info)
        self.register("fix_manual", self.on_fix_manual)

        self.log_welcome()

    def log_welcome(self):
        from ..constants import APP_VENDOR
        self.log("欢迎使用 Codex 小帮手！", "ok")
        self.log("一键安装 Node.js（内置离线包，无需联网）与 Codex CLI"
                 "（npm 联网安装，优先 npmmirror 镜像，"
                 "超 5 分钟自动切官方源）。", "normal")
        self.log("如 Codex 桌面端插件（Chrome / 浏览器 / Computer Use）失效，"
                 "点击【② 安装 / 修复】中的【一键修复 Codex 插件】一键处理。", "normal")
        self.log("ChatGPT 打不开或报 \"Unable to locate the Codex CLI binary\"？"
                 "切到【ChatGPT 启动修复】分页一键处理。", "normal")
        self.log("Codex 桌面端想降级/升级？切到【桌面端 降级 / 升级】分页。", "normal")
        self.log(f"© 2026 {APP_VENDOR} · 本程序仅供个人学习与分享使用", "dim")

    # ---------- 检测 ----------
    def on_detect_click(self):
        if self.app._detecting:
            return
        threading.Thread(target=self.detect_job, daemon=True).start()

    def detect_job(self):
        app = self.app
        idle = (not app.busy) and (not app._final_shown)
        app.q.put(("detect_begin",))
        if idle:
            app.q.put(("status", "正在检测本机环境…"))
        try:
            from ..util import detect
            info = detect()
            gpt = self.detect_gpt()
        except Exception as e:
            app.q.put(("log", "err", "环境检测失败：" + str(e)))
            info, gpt = {}, {}
        # 两页结果集齐后一起发，保证骨架脉冲在两页结果渲染前不中断
        app.q.put(("info", info))
        app.q.put(("gpt_info", gpt))
        if idle:
            app.q.put(("status", "检测完成。点击上方按钮即可开始安装。"))

    def detect_gpt(self):
        from ..gpt_fix import detect_gpt_env
        return detect_gpt_env()

    def on_detect_begin(self, _msg):
        app = self.app
        app._detecting = True
        if not app.busy:
            app.spinner.start()
        app._start_skeleton()
        self.btn_recheck.configure(state=tk.DISABLED)
        app._set_button_loading(self.btn_recheck, "检测中")

    def _on_detect_done(self):
        app = self.app
        app._detecting = False
        app._stop_skeleton()
        if app._btn_loading and app._btn_loading[0] is self.btn_recheck:
            app._restore_buttons()
        if not app.busy:
            app.spinner.stop()
            self.btn_recheck.configure(state="normal")

    def render_info(self, msg):
        info = msg[1]
        self._on_detect_done()

        def badge(key, text, kind):
            set_badge(self.rows[key][0], text, kind)

        has_node = bool(info.get("node_dir") and info.get("node_ver"))
        badge("node", f"✓ v{info['node_ver']}" if has_node else "✗ 未安装",
              "ok" if has_node else "bad")
        self.rows["node"][1].configure(text=info.get("node_dir") or "")

        has_npm = bool(info.get("npm_ver"))
        badge("npm", f"✓ v{info['npm_ver']}" if has_npm else "✗ 不可用",
              "ok" if has_npm else "bad")
        self.rows["npm"][1].configure(text=info.get("npm_prefix") or "")

        cod_v = info.get("codex_ver")
        badge("codex", f"✓ v{cod_v}" if cod_v else "✗ 未安装",
              "ok" if cod_v else "bad")
        self.rows["codex"][1].configure(text=info.get("codex_shim") or "")

    def on_fix_manual(self, _msg):
        from tkinter import messagebox
        try:
            messagebox.showinfo(
                "已复制修复提示词到剪贴板",
                "未能自动键入修复指令（可能被系统安全策略拦截）。\n\n"
                "修复提示词已复制到剪贴板：\n"
                "① 点击刚打开的 Codex（PowerShell）窗口；\n"
                "② 在窗口内【鼠标右键】即可粘贴\n"
                "（注意：不要按 Ctrl+V，codex 会把它当作粘贴图片）；\n"
                "③ 按回车开始修复。",
                parent=self.app.root)
        except Exception:
            pass

    # ---------- 动作 ----------
    def start_install(self, want_node: bool, want_codex: bool, btn):
        app = self.app
        parts = []
        if want_node:
            parts.append("Node.js")
        if want_codex:
            parts.append("Codex CLI")
        app.start_task(lambda: app.worker.run(want_node, want_codex),
                       btn=btn, loading_text="正在安装",
                       log_title="—— 开始安装：" + "+".join(parts) + " ——")

    def on_fix_click(self):
        app = self.app
        app.start_task(app.worker.run_fix, btn=self.btn_fix,
                       loading_text="正在修复",
                       log_title="—— 开始：Codex 插件一键修复 ——")

    def on_cancel(self):
        self.app.worker.cancel.set()
        self.log("收到取消请求…", "warn")

    def on_task_done(self):
        """任务结束 → 自动刷新一次检测结果。"""
        self.on_detect_click()
