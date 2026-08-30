# -*- coding: utf-8 -*-
"""
Codex 小帮手（独立 exe 版）—— Node.js + Codex CLI 一键安装 · Codex 插件一键修复

版权所有 (C) 2026 小枳ai分享
本程序由 小枳ai分享 制作并分享，转载/二次分发请保留本版权声明。

【v1.5.0 起本文件为兼容外观】真正的实现拆分到 codexhelper/ 包：
    - PyInstaller 打包入口仍引用本文件（NodeCodexSetup.spec 无需改动）；
    - 旧脚本/测试的 `nci.xxx` 导入路径继续可用（test_fix_headless.py、
      debug_capture.py 等）。
新增代码请进 codexhelper/ 对应模块，不要往回堆。
"""
from codexhelper import (  # noqa: F401
    APP_TITLE,
    APP_VENDOR,
    APP_VERSION,
    OpCancelled,
    App,
    codex_home,
    decode_bytes,
    detect,
    detect_gpt_env,
    ensure_full_access,
    ensure_goal_prompt,
    find_codex_desktop,
    find_new_console_window,
    find_patch_skill,
    find_window_by_title,
    install_patch_skill,
    is_admin,
    launch_codex_window,
    locate_codex_cli,
    make_env,
    res_path,
    restart_chatgpt_app,
    run_quiet,
    set_user_env,
    snapshot_windows,
    type_text_into_window,
)
from codexhelper.launcher import main
from codexhelper.webui.cfgcenter import (  # noqa: F401
    build_snapshot,
    read_auth,
    read_cc_switch,
    read_codex_plus,
    read_config,
)

if __name__ == "__main__":
    main()
