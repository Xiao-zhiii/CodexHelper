# -*- coding: utf-8 -*-
"""分页④：Codex 环境检测（v1.5.0 新增）。
扫描 ~/.codex 目录（.env 文件）与 系统/用户/进程 三级环境变量中
与 代理 / API Key / Codex 相关的条目并集中展示。"""
import tkinter as tk

from .. import theme
from ..theme import card, chip, hint
from .base import Tab


class TabEnv(Tab):
    def build(self):
        app = self.app
        card1 = card(self.parent, "① Codex 环境扫描")
        self.btn_scan = chip(card1, "↻ 开始检测", self.on_scan_click, pady=4)
        self.btn_scan.pack(side="right")
        hint(card1, "检查 ~/.codex 目录内的 .env 文件，以及 系统变量 / 用户变量 / 当前进程"
                    "中与 代理（HTTP_PROXY 等）、API Key、Codex 相关的环境变量。",
             pady=(4, 0))
        hint(card1, "安全提示：密钥类变量只显示首尾片段（打码），代理地址完整显示。")

        self.readout, self.append, self.clear = theme.mono_block(card1, height=13)
        self.readout.pack(fill="x", pady=(8, 0))

        app.action_buttons.append(self.btn_scan)
        self.register("env_report", self.render_report)

    def on_scan_click(self):
        self.clear()
        self.app.start_task(self.app.worker.run_env_scan,
                            btn=self.btn_scan, loading_text="正在扫描",
                            log_title="—— 扫描 Codex 环境配置 ——")

    def render_report(self, msg):
        r = msg[1]
        a = self.append
        # ① 代理
        p = r["proxy"]
        if p["enabled"]:
            a(f"【代理】已检测到{p['source']}：{p['server']}", "ok")
            a("  下载类操作将自动走此代理（ghproxylist 加速通道同样经代理转发）。", "dim")
        else:
            a("【代理】未检测到系统代理或代理环境变量（网络不畅时可开启后再试）。", "warn")

        # ② .codex / .env
        a(f"【.codex 目录】{r['home']}", "title")
        ef = r["env_file"]
        if ef["exists"]:
            a(f"  .env 文件：✓ 存在（{ef['count']} 项）→ {ef['path']}", "ok")
            for item in ef["entries"]:
                a(f"    {item['name']} = {item['masked']}",
                  "warn" if item["secret"] else "normal")
        else:
            a("  .env 文件：✗ 不存在（该文件是可选的本地环境配置，不影响使用）", "dim")

        # ③ 环境变量
        a(f"【相关环境变量】共 {len(r['vars'])} 条命中（代理 / API Key / Codex 相关）",
          "title")
        if not r["vars"]:
            a("  未发现相关变量。", "dim")
        for item in r["vars"]:
            flag = "🔑" if item["secret"] else ("🛜" if item["proxy"] else "•")
            a(f"  [{item['source']}] {flag} {item['name']} = {item['masked']}",
              "warn" if item["secret"] else "normal")
        cli = (r.get("cli_path") or "").strip()
        a(f"【CODEX_CLI_PATH】{cli if cli else '（未设置）'}",
          "ok" if cli else "dim")
        a("扫描完成。", "ok")
