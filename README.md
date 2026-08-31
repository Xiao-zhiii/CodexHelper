# Codex 小帮手（Node.js + Codex CLI 一键安装 · 插件修复）

> © 2026 小枳ai分享 · 作者主页：**https://github.com/Xiao-zhiii**

一个**完全独立**的 Windows 单文件工具：自带 Node.js 离线安装包，
无需 Python / Node.js / 任何运行环境，拷贝到任意 Win10 / Win11 电脑双击即用。
一键完成 **Node.js + OpenAI Codex CLI** 的安装，还能**一键修复**
Codex 桌面端的 Chrome 插件 / 浏览器插件 / Computer Use 插件失效问题。

## 功能特性

- **🖥 本地 Web 界面（v1.6.0 全新）**：双击 exe 自动打开浏览器界面
  （内置 HTTP 服务，数据不出本机；关闭浏览器后空闲自动退出），
  扁平化设计 + 骨架屏/按钮加载态/进度条等加载反馈
- **环境检测（Node.js / npm / Codex CLI 版本徽章）、一键安装、
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
- **🗂 配置中心（v1.6.0 新增）**：表格化查看 `.codex/config.toml`、`auth.json`
  （敏感值默认打码）、`.cc-switch`（供应商卡片/连通性测试/MCP/Skills）、
  Codex++ 注入状态与系统信息，支持自定义路径
- **📥 Codex 桌面端 降级 / 升级（v1.5.0 新增，独立分页）**：
  从 `Wangnov/codex-app-mirror` 镜像获取最近 50 个版本（标注可升级/可降级），
  下载自动选择通道（ghproxylist 加速优先 → 检测到系统代理则走代理 → 直连兜底），
  SHA256 校验后安装；降级自动先卸载当前版本（不影响 ~/.codex 用户数据），
  支持 `-ForceUpdateFromAnyVersion`
- **🔍 Codex 环境检测（v1.5.0 新增，独立分页）**：
  一键扫描 `~/.codex/.env` 与 系统/用户/进程三级环境变量中的
  代理（HTTP_PROXY 等）、API Key、Codex 相关条目并集中展示
  （密钥类值自动打码，防止截图泄露）
- **🗂 Codex 历史记录管理（v1.7.0 新增，独立分页）**：管理 Codex 内的对话记录
  - 列出全部会话（标题 / 时间 / 体积 / 供应商），支持按活跃·已归档筛选与关键词搜索
  - **归档 / 恢复**：归档 = 打标记 + 会话文件移入 `archived_sessions/`，可随时恢复
  - **删除**：清理库记录 + 投影表 + 会话文件 + 索引
  - **导入**：从 **Claude Code**（`~/.claude/projects`）或另一个 Codex 目录导入会话，
    Claude 格式自动转换为 Codex rollout 结构
  - 所有写操作前自动备份数据库到 `backups_state/codexhelper/`，备份失败即中止
- **📋 运行日志查看（v1.7.0 新增，独立分页）**：读取 `.codex/logs_2.sqlite`
  - 按级别（错误/警告/信息）筛选、关键词搜索、分页加载
  - 日志库常有上百 MB，因此服务端过滤后只回传一页，正文按需截断
  - 附带「本程序日志」（`Codex Helper.log`）便于自查
  - **跨机器可读**：会话与日志路径经用户名/盘符无关的相对化解析定位，
    换电脑、换 Windows 账户、主目录重定向到其它盘都能读到
- **✨ 设计系统（v1.7.0 焕新）**：按 Apple HIG 建立三层设计令牌
  （调色板 → 语义色 → 组件），组件规则零硬编码色值
  - 完整支持**暗色模式**（跟随系统）、键盘焦点环、标签页方向键导航、
    `prefers-reduced-motion` 减弱动效、表格粘性表头
- **界面加载反馈（v1.4.1 / v1.4.2）**：
  - 环境检测期间显示灰色骨架占位徽章（呼吸动效）与环形旋转指示器
  - 下载 Node.js 离线包时，底部进度条显示真实下载百分比（MB + %）
  - 点击安装/修复按钮后进入"正在安装…"加载态并锁定，防止重复点击
- **健壮的错误处理**：UAC 取消 / 安装超时 / 双源失败均有明确提示

## 使用方法

普通用户无需看代码——直接从 [Releases](../../releases) 下载，两个资产任选其一：

| 资产 | 大小 | 适合谁 | 说明 |
|---|---|---|---|
| **`CodexHelper-Setup-1.8.0.exe`**（推荐） | 约 309 MB | **大多数用户** | 安装向导，**安装时自动装好 VC++ 运行库**，装完自动创建开始菜单与桌面快捷方式，卸载走「应用和功能」 |
| `CodexHelper.exe` | 约 54 MB | 已装好运行环境的老用户 | 单文件绿色版，双击即用、不用安装；但**若系统缺 VC++ 运行库会打不开**，此时请改用上面的安装包 |

> 不知道选哪个就选**安装包**。单文件版体积小，但 v1.8.0 之前"用户下载后双击却跑不起来"
> 的反馈基本都是缺 VC++ 导致的，安装包就是为解决这个而做的。

装好后的使用与详细图文说明，见仓库内《使用说明》或 exe 同目录文档。

SmartScreen 提示时点【更多信息】→【仍要运行】（exe 未购买数字签名，属正常现象）。

## 目录结构

```
├── node_codex_installer.py   # PyInstaller 入口（兼容外观，转发到 codexhelper 包）
├── codexhelper/              # 主程序包
│   ├── constants.py          # 常量与下载源（APP_VERSION 在此）
│   ├── util.py winops.py     # 基础工具 / Windows 窗口与输入
│   ├── codex_fix.py          # 插件修复后端
│   ├── gpt_fix.py            # ChatGPT 启动修复后端
│   ├── installer.py          # 后台任务编排
│   ├── netenv.py             # 代理与环境变量扫描
│   ├── mirror.py             # 桌面端镜像：版本/下载/校验/安装
│   ├── codexpaths.py         # ★ v1.7.0 跨机器定位 CODEX_HOME
│   ├── codexhistory.py       # ★ v1.7.0 历史会话管理
│   ├── codexlogs.py          # ★ v1.7.0 运行日志读取
│   ├── launcher.py           # 程序入口：起服务 → 开浏览器 → 空闲退出
│   └── webui/                # 本地 Web 界面
│       ├── cfgcenter.py      # 配置中心后端
│       ├── server.py         # HTTP 路由与任务系统
│       └── page.py           # 前端注入层
├── codex_helper.ico          # 程序图标（exe 图标 + favicon 共用）
├── version_info.txt          # exe 版本资源（版权信息）
├── NodeCodexSetup.spec       # PyInstaller 打包配置
└── test_fix_headless.py      # 无头回归测试
```

## 从源码构建

需要：Windows 10/11 + Python 3.10+（开发环境为 3.13）

```bash
pip install pyinstaller pillow pywebview

# 打包（需提前把 node-v24.18.0-x64.msi 放在 src 目录；
#    可从 https://npmmirror.com/mirrors/node/v24.18.0/ 下载）
cd src
python -m PyInstaller NodeCodexSetup.spec --noconfirm --clean
```

产物：`src/dist/NodeCodexSetup.exe`（约 54 MB，单文件免安装），
部署时复制为 `Codex小帮手.exe`。

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
