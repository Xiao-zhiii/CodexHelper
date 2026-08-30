# Codex 小帮手（Node.js + Codex CLI 一键安装 · 插件修复）

> © 2026 小枳ai分享 · 作者主页：**https://github.com/Xiao-zhiii**

一个**完全独立**的 Windows 单文件工具：自带 Node.js 离线安装包，
无需 Python / Node.js / 任何运行环境，拷贝到任意 Win10 / Win11 电脑双击即用。
一键完成 **Node.js + OpenAI Codex CLI** 的安装，还能**一键修复**
Codex 桌面端的 Chrome 插件 / 浏览器插件 / Computer Use 插件失效问题。

## 功能特性

- **GUI 图形界面**：环境检测（Node.js / npm / Codex CLI 版本徽章）、一键安装、
  分项安装、任务取消、实时日志
- **Node.js 离线安装**：内置 `node-v24.18.0-x64.msi`（随 exe 打包，无需联网），
  msiexec 静默安装 + UAC 提权处理
- **Codex CLI 在线安装**：`npm i -g @openai/codex`
  - 自动执行 `Set-ExecutionPolicy RemoteSigned` 解除 PowerShell“禁止运行脚本”限制
  - 优先走 **npmmirror 国内镜像**，超过 5 分钟自动切换 npm 官方源重试
  - 安装后自动校验版本、定位 `codex` 命令入口
- **🛠 Codex 插件一键修复（v1.2 新增）**：修复 Codex 桌面端
  Chrome 插件 / 浏览器插件 / Computer Use 插件失效问题
  - 自动检测本机是否已安装 `codex-windows-fast-patch-skill` 修复技能，
    没有则从 GitHub 自动下载安装（多源容错）
  - 自动把 Codex 权限设置为 **Full Access**（`config.toml` 写入
    `approval_policy = "never"` + `sandbox_mode = "danger-full-access"`，原配置自动备份）
  - 自动写入 `/goal` 自定义指令（`~/.codex/prompts/goal.md`），
    在 codex 中输入 `/goal` 即可随时调取修复技能
  - 自动打开 **PowerShell 版 Codex CLI**（Full Access 模式），自动确认目录信任提示，
    并自动**逐字符键入** `/goal 修复指令`（等效人工打字），回车即开始排查修复。
    注意：不使用 Ctrl+V——新版 codex 把 Ctrl+V 绑定为“粘贴剪贴板图片”，
    传统控制台下文字无法输入（报 no image on clipboard）
  - 自动输入未成功时（个别环境安全策略拦截），自动弹窗提示：
    修复提示词已在剪贴板，点击 Codex 窗口【鼠标右键】即可粘贴，回车开始修复
- **🗨 ChatGPT 启动修复（v1.4.0 新增，独立分页）**：修复 ChatGPT 桌面应用
  启动报错 "ChatGPT failed to start. Unable to locate the Codex CLI binary"
  - 自动检测 OpenAI.Codex 桌面应用（ChatGPT）安装状态与包内 codex.exe 位置
  - 一键写入用户环境变量 `CODEX_CLI_PATH` 并自动重启 ChatGPT 应用
    （包内找不到 CLI 时自动回退到 npm 版 Codex 的原生二进制）
- **管理员模式引导**：启动时检测权限，支持一键 UAC 提权重启
- **✨ 界面加载反馈与设计焕新（v1.4.1 / v1.4.2）**：
  - 环境检测期间显示灰色骨架占位徽章（呼吸动效）与环形旋转指示器
  - 下载 Node.js 离线包时，底部进度条显示真实下载百分比（MB + %）
  - 点击安装/修复按钮后进入"正在安装…"加载态并锁定，防止重复点击
  - 按钮与标签页扁平化设计、字号与对比度优化（依据 Apple HIG 走查）
- **健壮的错误处理**：UAC 取消 / 安装超时 / 双源失败均有明确提示

## 使用方法

普通用户无需看代码——直接从 [Releases](../../releases) 下载
`CodexHelper.exe`（约 41 MB，单文件，即「Codex 小帮手」），双击运行即可。
详细图文说明见仓库内《使用说明》或 exe 同目录文档。

SmartScreen 提示时点【更多信息】→【仍要运行】（exe 未购买数字签名，属正常现象）。

## 目录结构

```
├── node_codex_installer.py   # 主程序（tkinter GUI + 安装/修复逻辑，约 1100 行）
├── make_icon.py              # 图标生成脚本（Pillow）
├── installer.ico             # 程序图标
├── version_info.txt          # exe 版本资源（版权信息）
└── NodeCodexSetup.spec       # PyInstaller 打包配置
```

## 从源码构建

需要：Windows 10/11 + Python 3.10+（开发环境为 3.13）

```bash
pip install pyinstaller pillow

# 1. 生成图标
python make_icon.py

# 2. 打包（需提前把 node-v24.18.0-x64.msi 放在当前目录；
#    可从 https://npmmirror.com/mirrors/node/v24.18.0/ 下载）
python -m PyInstaller --onefile --windowed --clean --noconfirm \
    --name NodeCodexSetup \
    --icon installer.ico \
    --version-file version_info.txt \
    --add-data "node-v24.18.0-x64.msi;assets" \
    --add-data "installer.ico;assets" \
    node_codex_installer.py
```

产物：`dist/NodeCodexSetup.exe`（约 41 MB，单文件免安装）

## 技术要点

- Node.js 检测兼容自定义安装路径（`where node` + 常见目录兜底）
- npm 调用采用 `node.exe + npm-cli.js` 直连方式，绕开 `.cmd`/`.ps1`
  执行策略与引号转义问题
- msiexec 静默安装经 PowerShell `-EncodedCommand` + `Start-Process -Verb RunAs`
  实现，精确解析 msiexec 退出码（0 / 3010 / 1223 / 1602 / 1603 …）
- 插件修复的窗口自动化：`CREATE_NEW_CONSOLE` 直开控制台（绕开
  `cmd /c start` 的引号二次解析坑），启动前后窗口快照差分 + 控制台宿主进程
  过滤定位窗口（codex TUI 会改写窗口标题，不能靠标题找），剪贴板 +
  `keybd_event` 模拟粘贴回车，仅在前台校验通过后才输入，失败自动回退为
  “指令已在剪贴板，手动粘贴”
- 子进程输出经 UTF-8 → GBK 双重解码，兼容中文 Windows

## 版权声明

**© 2026 小枳ai分享 · 版权所有** — 本程序仅供个人学习使用，
转载 / 二次分发请保留本声明及代码内的作者标识水印。

作者主页：https://github.com/Xiao-zhiii
