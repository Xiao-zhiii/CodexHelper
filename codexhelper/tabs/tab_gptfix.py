# -*- coding: utf-8 -*-
"""分页②：ChatGPT（OpenAI.Codex 桌面应用）启动报错修复。"""
import os

import tkinter as tk

from .. import theme
from ..gpt_fix import GPT_ERROR_TEXT
from ..theme import card, hint, primary, badge_row, set_badge
from .base import Tab


class TabGptFix(Tab):
    def build(self):
        app = self.app
        cardg = card(self.parent, "① 问题检测与一键修复")
        tk.Label(cardg, text=GPT_ERROR_TEXT, bg="#FEF2F2", fg=theme.RED_FG,
                 font=(theme.MONO, 9), wraplength=610, justify="left",
                 padx=10, pady=8).pack(fill="x", pady=(4, 8))
        _grid, self.rows_g = badge_row(cardg, [("pkg", "ChatGPT 桌面应用"),
                                               ("cli", "codex.exe CLI"),
                                               ("env", "CODEX_CLI_PATH")])
        app.skeleton_rows.append(self.rows_g)

        self.btn_fix_gpt = primary(cardg, "🔧 一键修复 ChatGPT 启动报错",
                                   self.on_fix_click)
        self.btn_fix_gpt.pack(fill="x", pady=(8, 6))
        hint(cardg, "自动定位 ChatGPT 内置的 codex.exe → "
                    "写入环境变量 CODEX_CLI_PATH → 重启 ChatGPT", pady=(2, 0))
        hint(cardg, "仅对当前用户生效，无需重启电脑；"
                    "若仍报错，请完全退出 ChatGPT 后重新打开。")

        app.action_buttons.append(self.btn_fix_gpt)
        self.register("gpt_info", self.render_gpt_info)

    def render_gpt_info(self, msg):
        info = msg[1]
        self.app._on_detect_done()

        def badge(key, text, kind):
            set_badge(self.rows_g[key][0], text, kind)

        pkg = info.get("pkg")
        if pkg:
            badge("pkg", f"✓ v{pkg.get('version')}", "ok")
            self.rows_g["pkg"][1].configure(text=pkg.get("location") or "")
        else:
            badge("pkg", "✗ 未安装", "bad")
            self.rows_g["pkg"][1].configure(text="未检测到 OpenAI.Codex 桌面应用（ChatGPT）")

        cli = info.get("cli")
        if cli:
            badge("cli", "✓ 已找到", "ok")
            self.rows_g["cli"][1].configure(text=cli)
        else:
            badge("cli", "✗ 未找到", "bad")
            self.rows_g["cli"][1].configure(text="请先到【安装 · 插件修复】页安装 Codex CLI")

        env = (info.get("env") or "").strip()
        if env:
            valid = os.path.isfile(env)
            badge("env", "✓ 已设置" if valid else "⚠ 指向的文件不存在",
                  "ok" if valid else "bad")
            self.rows_g["env"][1].configure(text=env)
        else:
            badge("env", "✗ 未设置", "bad")
            self.rows_g["env"][1].configure(text="这正是 ChatGPT 启动报错的常见原因")

    def on_fix_click(self):
        self.app.start_task(lambda: self.app.worker.run_fix_gpt(restart=True),
                            btn=self.btn_fix_gpt, loading_text="正在修复",
                            log_title="—— 开始：ChatGPT 启动修复 ——")
