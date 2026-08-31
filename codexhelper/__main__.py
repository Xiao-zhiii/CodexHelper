# -*- coding: utf-8 -*-
"""程序入口。

⚠ 必须是 launcher（WebView2 原生窗口），**不要改回 app（tkinter）**。

历史坑：v1.6.0 起 launcher 已替代 tkinter 界面成为主界面，
但本文件曾被误改回 `from .app import main`，导致打包产物变成
旧的 tkinter 界面（而日志里 launcher 的输出又让人误以为跑的是新版），
排查"界面一直加载"时被误导了很久。

判据很简单：运行新版后日志里应出现
"pywebview 导入成功 / 正在创建 WebView2 原生窗口"，
若出现 Tk 窗口则说明本入口又指错了。

launcher 同时支持命令行参数：
    --self-test    跑一遍核心接口自检，退出码 0/1
    --no-browser   只起服务不开窗口（供 AI 用 helper 接口排查）

兼容 PyInstaller：打包时 PyInstaller 可能把本文件作为顶层脚本运行，
相对导入会爆炸，因此同时提供绝对导入 fallback。
"""
import os
import sys
from pathlib import Path

# PyInstaller 环境下，把包根目录补到 sys.path，确保绝对导入能找到 codexhelper
if __package__ is None or __package__ == "":
    here = Path(__file__).resolve().parent
    root = here.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from codexhelper.launcher import main
else:
    from .launcher import main

if __name__ == "__main__":
    main()
