# -*- coding: utf-8 -*-
"""发布前一键自检（preflight）——把 v1.7.0 踩过的坑固化成可执行的检查。

## 检查项

1. **版本一致性**：`constants.APP_VERSION` ↔ `version_info.txt` 的四段版本号。
   打 Release 时最容易漏改后者，导致 exe 属性里显示旧版本。
2. **页面 JS 语法**：用 `node --check` 逐个校验 `page.get_page()` 产出的内联
   `<script>`。v1.7.0 的"空白卡片"事故就是 JS 里混入真实换行导致的
   SyntaxError——页面不报错、只是静默全白，靠肉眼看不出来。
3. **关键 DOM 结构**：历史 / 日志两个 tab 的容器还在（防止改版时误删）。
4. **三个新模块的沙箱自测**：跑 `test_codex_modules_headless.py`。
5. **打包资源**：`installer.ico` 存在且是多帧 ICO（少帧会导致任务栏图标糊）。
6. **资产名版本号一致性**：README 里的 `CodexHelper-Setup-x.y.z.exe`、
   写死的 Release tag、`CodexHelper.iss` 的 `MyAppVersion` 三处手写的版本号
   都必须等于 `APP_VERSION`。v1.8.2 发版时 README 漏改（仍是 1.8.1），
   靠人眼没发现——这里把它钉成门禁。

## 用法

    cd F:\\vibe code\\src
    python preflight_check.py

退出码 0 = 全部通过，1 = 有失败项（可直接用于 CI 或发布脚本的门禁）。
"""
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

REPORT = []


def check(name, cond, extra=""):
    cond = bool(cond)
    REPORT.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    return cond


def section(t):
    print(f"== {t} ==")


# ------------------------------------------------------------- 1. 版本 ----
section("1. 版本一致性")
try:
    from codexhelper.constants import APP_VERSION
except Exception as exc:  # noqa: BLE001
    check("导入 constants.APP_VERSION", False, str(exc))
    APP_VERSION = None

if APP_VERSION:
    print(f"  APP_VERSION = {APP_VERSION}")
    vi = (SRC / "version_info.txt").read_text(encoding="utf-8", errors="replace")
    m_file = re.search(r"filevers=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", vi)
    m_str = re.search(r"StringStruct\('FileVersion',\s*'([^']+)'\)", vi)
    check("version_info.txt 解析出 filevers", m_file is not None)
    check("version_info.txt 解析出 FileVersion 字符串", m_str is not None)
    if m_file:
        got = ".".join(m_file.groups())
        want = APP_VERSION + ".0"
        check(f"filevers 与 APP_VERSION 一致（{got}）", got == want,
              "" if got == want else f"期望 {want}")
    if m_str:
        check(f"FileVersion 字符串与 APP_VERSION 一致（{m_str.group(1)}）",
              m_str.group(1) == APP_VERSION + ".0")
    check("版本号为三段式 x.y.z",
          re.match(r"^\d+\.\d+\.\d+$", APP_VERSION) is not None)

# ------------------------------------------------------- 2. 页面与 JS ----
section("2. 页面渲染与 JS 语法")
html = ""
try:
    from codexhelper.webui import page
    html = page.get_page(APP_VERSION or "0.0.0", "小枳ai分享",
                         "https://example.com", False)
    check("page.get_page() 正常返回", bool(html), f"{len(html)} 字符")
except Exception as exc:  # noqa: BLE001
    check("page.get_page() 正常返回", False, repr(exc))

if html:
    # 客户端错误上报是 v1.7.0 排查"空白卡片"时补的：页面 JS 抛错会静默
    # 全白，只有这三个监听能把异常送回后端日志。少任何一个排查都会瞎。
    for name, pat in [("历史 tab 容器", r'id="tab-history"'),
                      ("日志 tab 容器", r'id="tab-logs"'),
                      ("运行时错误监听", r'addEventListener\("error"'),
                      ("Promise 拒绝监听", r'addEventListener\("unhandledrejection"'),
                      ("资源加载失败分支", r"资源加载失败"),
                      ("上报端点 /api/client-error", r"/api/client-error")]:
        n = len(re.findall(pat, html))
        check(name, n > 0, f"{n} 处")

    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    check("提取到内联 script 块", len(scripts) > 0, f"{len(scripts)} 个")

    node = shutil.which("node")
    for cand in (Path(r"C:\Program Files\nodejs\node.exe"),
                 Path.home() / "AppData" / "Roaming" / "nvm" / "node.exe"):
        if not node and cand.exists():
            node = str(cand)
    if node and scripts:
        # 临时文件统一落在 _tmp/ 下，不往项目根目录堆（用完即删）
        (SRC.parent / "_tmp").mkdir(exist_ok=True)
        tmp = SRC.parent / "_tmp" / "_preflight.js"
        for i, s in enumerate(scripts):
            tmp.write_text(s, encoding="utf-8")
            p = subprocess.run([node, "--check", str(tmp)],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if p.returncode != 0:
                line = ""
                m = re.search(r"\.js:(\d+)", p.stderr or "")
                if m:
                    n = int(m.group(1))
                    sl = s.splitlines()
                    lo, hi = max(0, n - 3), min(len(sl), n + 2)
                    line = " | " + " / ".join(
                        f"{k + 1}:{sl[k][:60]}" for k in range(lo, hi))
                check(f"script#{i + 1} 语法", False, line)
                print((p.stderr or "")[:800])
            else:
                check(f"script#{i + 1} 语法", True, f"{len(s)} 字符")
        tmp.unlink(missing_ok=True)
    elif not node:
        print("  [SKIP] 未找到 node，跳过 JS 语法校验（强烈建议安装 Node 后再发布）")

# --------------------------------------------------------- 3. 模块自测 ----
section("3. 后端模块自测")
for name, script in (
    ("codexpaths / codexhistory / codexlogs 沙箱", "test_codex_modules_headless.py"),
    ("helper 诊断接口与持久化日志", "test_helper_api_headless.py"),
    ("启动自检与界面降级链", "test_launcher_fallback_headless.py"),
    ("运行时依赖与前端导航", "test_deps_headless.py"),
):
    t = SRC / script
    if t.is_file():
        p = subprocess.run([sys.executable, str(t)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", cwd=str(SRC))
        tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()][-3:]
        for ln in tail:
            print("    " + ln)
        if p.returncode != 0:
            print("    ---- 失败用例 ----")
            for ln in (p.stdout or "").splitlines():
                if "FAIL" in ln or "Error" in ln:
                    print("    " + ln)
        check(f"{name} 通过", p.returncode == 0, f"exit={p.returncode}")
    else:
        check(f"存在 {script}", False)

# --------------------------------------------------------- 4. 打包资源 ----
section("4. 打包资源")
ico = SRC / "installer.ico"
check("installer.ico 存在", ico.is_file())
if ico.is_file():
    data = ico.read_bytes()
    frames = int.from_bytes(data[4:6], "little") if len(data) >= 6 else 0
    check(f"ICO 为多帧（{frames} 帧，覆盖 16→256）", frames >= 5)
    check(f"ICO 体积合理（{len(data)} 字节）", len(data) > 1024)

# ------------------------------------------------------- 5. 发布链路 ----
# 打包再正确，发版链路坏了照样发不出去。这里静态校验 CI 配置，
# 避免把坏 workflow 推上去才发现。
section("5. 发布链路")
wf = SRC / ".github" / "workflows" / "release.yml"
rel_py = SRC / "release.py"
# src 不是 git 仓库，workflow 只存在于 NodeCodexSetup/；两边都照顾到
if not wf.is_file():
    wf = SRC.parent / "NodeCodexSetup" / ".github" / "workflows" / "release.yml"

check("存在 release workflow", wf.is_file(), str(wf.name))
if wf.is_file():
    wf_text = wf.read_text(encoding="utf-8", errors="replace")
    check("workflow 使用 windows runner（路径断言依赖）",
          "windows-latest" in wf_text)
    check("workflow 有 contents: write 权限（否则建不了 Release）",
          "contents: write" in wf_text)
    check("workflow 资产名为 CodexHelper.exe",
          "CodexHelper.exe" in wf_text)
    check("workflow 含发布前自检步骤",
          "preflight_check.py" in wf_text)
    try:
        import yaml
        yaml.safe_load(wf_text)
        check("workflow YAML 可解析", True)
    except ImportError:
        print("  [SKIP] 未安装 pyyaml，跳过 YAML 解析校验")
    except Exception as exc:  # noqa: BLE001
        check("workflow YAML 可解析", False, str(exc))

check("存在 release.py", rel_py.is_file())
if rel_py.is_file():
    try:
        ast.parse(rel_py.read_text(encoding="utf-8"))
        check("release.py 语法正确", True)
    except SyntaxError as exc:
        check("release.py 语法正确", False, f"第 {exc.lineno} 行")

# ------------------------------------------------- 6. 资产名版本号一致性 ----
# v1.8.2 事故：release notes 里的资产名由 release.py 带版本号自动生成，
# 但 README 里的安装包文件名是**手写的**，发 1.8.2 时 README 仍写着
# Setup-1.8.1.exe，从发版到补传都没人发现。
#
# 根因是"版本号散落在多处，改的时候靠人记得全改"。这里把所有手写的
# 版本号钉死：漏改任何一处，preflight 直接 FAIL。
section("6. 资产名版本号一致性")
REPO_DIR = SRC.parent / "NodeCodexSetup"

readme = REPO_DIR / "README.md"
if not readme.is_file():
    readme = SRC / "README.md"

if not readme.is_file():
    print("  [SKIP] 未找到 README.md，跳过资产名校验")
elif not APP_VERSION:
    print("  [SKIP] APP_VERSION 不可用，跳过资产名校验")
else:
    rd = readme.read_text(encoding="utf-8", errors="replace")
    # 安装包资产名：README 里必须出现，且版本号只能是当前的
    vers = re.findall(r"CodexHelper-Setup-(\d+\.\d+\.\d+)\.exe", rd)
    check("README 引用了安装包资产名", len(vers) > 0, f"{len(vers)} 处")
    stale = sorted({v for v in vers if v != APP_VERSION})
    check(f"README 安装包版本号与 APP_VERSION 一致（{APP_VERSION}）",
          not stale, "" if not stale else f"残留旧版本号 {stale}")
    # 下载链接若写死 tag，也必须跟上（相对链接 ../../releases 不受影响）
    tags = re.findall(r"releases/tag/v(\d+\.\d+\.\d+)", rd)
    stale_tag = sorted({t for t in tags if t != APP_VERSION})
    check(f"README 写死的 Release tag 与 APP_VERSION 一致（{APP_VERSION}）",
          not stale_tag,
          "" if not stale_tag else f"残留旧 tag {stale_tag}")

iss = SRC / "CodexHelper.iss"
if not iss.is_file():
    iss = REPO_DIR / "CodexHelper.iss"
check("存在 CodexHelper.iss", iss.is_file())
if iss.is_file():
    iss_text = iss.read_text(encoding="utf-8", errors="replace")
    m_iss = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', iss_text)
    check("CodexHelper.iss 解析出 MyAppVersion", m_iss is not None)
    if m_iss:
        check(f"iss MyAppVersion 与 APP_VERSION 一致（{m_iss.group(1)}）",
              m_iss.group(1) == APP_VERSION)
    # 安装包输出名走 {#MyAppVersion}，不用手写版本号
    check("iss 输出文件名使用 {#MyAppVersion} 变量",
          "CodexHelper-Setup-{#MyAppVersion}" in iss_text)

# --------------------------------------------- 7. README 功能声明 vs 代码 ----
# v1.7.0 / v1.8.2 两次事故：README 声称的功能，代码里压根没有（或反过来，
# 代码删了 README 还写着）。preflight 只校验版本号，这个盲区一直没人管。
#
# 更要注意**搜索范围**：审查框架当年只 grep 了 page.py，就断定"暗色模式 0 处、
# 焦点环 0 处、sticky 0 处"——而全部 CSS 与令牌都在 cfgcenter.py 里，
# 结论整体翻转。所以每条声明的搜索范围都**显式列出**，不默认只搜一个文件。
#
# 规则：README 里写了这个锚点 ⇒ 代码里必须找到证据。没写就跳过（不强迫写文档）。
section("7. README 功能声明核验")
WEBUI_DIR = SRC / "codexhelper" / "webui"

# (说明, README 锚点正则, 代码证据正则, 要搜的文件)
#
# 注意搜索范围要跟着代码搬家同步：v1.8.2 拆 cfgcenter.py 时把 HTML_PAGE
# （含全部 CSS 与设计令牌）抽到了 webui/cfgtpl.py，若这里不加上它，
# 5 条 CSS 声明会集体 FAIL——门禁会拦，但那是"提醒你漏同步"，不是真缺功能。
_CSS_FILES = ["webui/page.py", "webui/cfgcenter.py", "webui/cfgtpl.py"]

CLAIMS = [
    ("暗色模式（跟随系统）", r"暗色模式", r"prefers-color-scheme", _CSS_FILES),
    ("键盘焦点环", r"键盘焦点环", r":focus-visible|:focus\s*\{", _CSS_FILES),
    ("标签页方向键导航", r"方向键导航", r"Arrow(Left|Right)", _CSS_FILES),
    ("prefers-reduced-motion 减弱动效", r"prefers-reduced-motion",
     r"prefers-reduced-motion", _CSS_FILES),
    ("表格粘性表头", r"粘性表头", r"position:\s*sticky", _CSS_FILES),
    ("骨架屏 / 加载态", r"骨架", r"skeleton|骨架", _CSS_FILES),
    ("敏感值打码", r"打码", r"mask_value|def redact|\b打码\b",
     ["webui/page.py", "webui/cfgcenter.py", "netenv.py"]),
    ("跨机器路径解析", r"跨机器", r"def relocate_rollout", ["codexpaths.py"]),
    ("写操作前自动备份", r"自动备份", r"def backup_databases|备份失败",
     ["codexhistory.py"]),
    # 真实写法是 upper(level) in (?,?)，不是 level in (...)——正则必须贴着
    # 代码现状写，否则门禁会误报"功能不存在"（本次就是这么踩的）。
    ("日志按级别筛选（SQL 下推）", r"按级别",
     r"upper\(\s*level\s*\)\s+in\s*\(|level\s+in\s*\(", ["codexlogs.py"]),
]

# 设计令牌单独验：README 说"三层设计令牌"，光有 1 个 CSS 变量不算数
TOKEN_CLAIM = ("三层设计令牌（CSS 变量 ≥ 20 个）", r"设计令牌")


def _read_mod(rel):
    """按相对路径读模块源码，找不到返回空串。"""
    for base in (SRC / "codexhelper", SRC):
        p = base / rel
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return ""


if not (readme.is_file() and rd):
    print("  [SKIP] README 不可用，跳过功能声明核验")
else:
    for label, anchor, evidence, files in CLAIMS:
        if not re.search(anchor, rd):
            print(f"  [SKIP] README 未声明「{label}」")
            continue
        hits = 0
        where = []
        for rel in files:
            n = len(re.findall(evidence, _read_mod(rel), flags=re.IGNORECASE))
            if n:
                hits += n
                where.append(f"{Path(rel).name}={n}")
        check(f"「{label}」代码里有实现", hits > 0,
              "、".join(where) if where else f"锚点命中但代码无证据（搜过 {'/'.join(files)}）")

    if re.search(TOKEN_CLAIM[1], rd):
        css_vars = 0
        where = []
        for rel in _CSS_FILES:
            n = len(re.findall(r"--[a-z][a-z0-9-]+\s*:", _read_mod(rel)))
            if n:
                css_vars += n
                where.append(f"{Path(rel).name}={n}")
        check(f"「{TOKEN_CLAIM[0]}」", css_vars >= 20,
              f"共 {css_vars} 个（{'、'.join(where) or '无'}）")

print()
failed = [n for n, c in REPORT if not c]
if failed:
    print(f"发布前自检：{len(failed)} 项未通过")
    for n in failed:
        print("   - " + n)
    raise SystemExit(1)
print(f"发布前自检：全部 {len(REPORT)} 项通过")
