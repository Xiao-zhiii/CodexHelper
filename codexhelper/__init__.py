# -*- coding: utf-8 -*-
"""Codex 小帮手实现包（v1.5.0 起由单文件拆分而来）。

模块地图：
    constants  常量与下载源
    util       基础工具（进程执行/路径/环境检测/环境变量）
    winops     Windows 窗口与输入操作
    codex_fix  Codex 插件修复后端
    gpt_fix    ChatGPT 启动修复后端
    installer  后台任务编排（队列消息协议见类文档）
    netenv     代理检测 + Codex 环境扫描（v1.5.0）
    mirror     桌面端镜像版本/下载/校验/安装（v1.5.0）
    theme      设计令牌与控件工厂（改观感只动这里）
    app        应用壳与忙碌状态机
    tabs/      各分页（install / gptfix / appx / env）

本包同时对外兼容旧单文件的常用符号（find_patch_skill、detect、App 等），
`node_codex_installer.py` 入口即转引这里，老脚本无需改动。
"""
from .constants import APP_TITLE, APP_VENDOR, APP_VERSION  # noqa: F401
from .codex_fix import (codex_home, ensure_full_access, ensure_goal_prompt,  # noqa: F401
                        find_patch_skill, install_patch_skill)
from .gpt_fix import (detect_gpt_env, find_codex_desktop,  # noqa: F401
                      locate_codex_cli, restart_chatgpt_app)
from .util import (OpCancelled, decode_bytes, detect, is_admin,  # noqa: F401
                   make_env, res_path, run_quiet, set_user_env)
from .winops import (find_new_console_window, find_window_by_title,  # noqa: F401
                     launch_codex_window, snapshot_windows,
                     type_text_into_window)


def App(root):
    """兼容旧用法 `App(root)`：返回初始化好的应用壳实例。"""
    from .app import App as _App
    return _App(root)


def main():
    from .app import main as _main
    _main()
