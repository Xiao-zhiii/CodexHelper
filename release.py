# -*- coding: utf-8 -*-
"""一键发版：自检 → 打包 → 生成 release notes → 建 GitHub Release。

把 v1.7.0 之前"手工拼 notes + 手动 gh release create"的流程脚本化，
并在发版前强制跑 preflight_check.py 做门禁。

## 用法

    python release.py             # 完整发版
    python release.py --dry-run   # 只跑自检与打包，不建 Release
    python release.py --no-build  # 跳过打包，用已有 dist 产物

## 前置

- 已安装并登录 `gh`（`gh auth status`）
- 工作区干净（无未提交改动）——避免把本地临时改动打进发布包
- 版本号已在 `codexhelper/constants.py` 与 `version_info.txt` 改好

## 注意

本脚本**不负责** git commit/push：版本提交仍由人工决定时机。
它只检查工作区是否干净，脏就直接停下。
"""
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
EXE_NAME = "Codex小帮手.exe"
DIST_EXE = HERE / "dist" / EXE_NAME
# 发布资产名保持历史约定：CodexHelper.exe（README 里的下载链接依赖它）
ASSET_NAME = "CodexHelper.exe"

DRY_RUN = "--dry-run" in sys.argv
NO_BUILD = "--no-build" in sys.argv


def run(cmd, **kw):
    """跑命令并实时返回 CompletedProcess。"""
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(HERE),
                          **kw)


def step(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


def die(msg):
    print(f"\n中止：{msg}")
    raise SystemExit(1)


# ------------------------------------------------------------ 1. 版本 ----
step("1. 读取版本号")
sys.path.insert(0, str(HERE))
from codexhelper.constants import APP_VERSION  # noqa: E402

print(f"  APP_VERSION = {APP_VERSION}")
if not re.match(r"^\d+\.\d+\.\d+$", APP_VERSION):
    die(f"版本号格式应为 x.y.z，实际 {APP_VERSION}")
TAG = "v" + APP_VERSION

# -------------------------------------------------------- 2. 工作区 ----
step("2. 检查 git 工作区")
r = run(["git", "status", "--porcelain"])
if r.returncode != 0:
    die("当前目录不是 git 仓库")
dirty = [l for l in (r.stdout or "").splitlines() if l.strip()]
if dirty:
    print("  有未提交改动：")
    for l in dirty[:20]:
        print("    " + l)
    die("请先提交或清理改动，再发版（避免把临时改动打进发布包）")
print("  工作区干净")

r = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
branch = (r.stdout or "").strip()
print(f"  当前分支：{branch}")
if branch not in ("main", "master"):
    print(f"  ⚠ 不在 main/master 分支（当前 {branch}）")

# ------------------------------------------------- 3. 检查 tag 冲突 ----
step("3. 检查 tag 是否已存在")
r = run(["git", "tag", "--list", TAG])
if TAG in (r.stdout or "").split():
    die(f"tag {TAG} 已存在，请先改版本号")
print(f"  {TAG} 可用")

# ------------------------------------------------------- 4. 门禁 ----
step("4. 发布前自检（preflight_check.py）")
r = run([sys.executable, "preflight_check.py"])
print((r.stdout or "").strip()[-1500:])
if r.returncode != 0:
    die("发布前自检未通过")
print("\n  自检通过")

# ------------------------------------------------------- 5. 打包 ----
step("5. 打包 EXE")
if NO_BUILD:
    print("  --no-build：跳过打包")
else:
    t0 = time.time()
    r = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "CodexHelper.spec"])
    if r.returncode != 0:
        print((r.stdout or "")[-3000:])
        print((r.stderr or "")[-2000:])
        die("打包失败")
    print(f"  打包完成，耗时 {time.time() - t0:.1f}s")

if not DIST_EXE.is_file():
    die(f"产物不存在：{DIST_EXE}")
print(f"  产物：{DIST_EXE}（{DIST_EXE.stat().st_size:,} 字节）")

# -------------------------------------------------- 6. release notes ----
step("6. 生成 release notes")
# 动态取上一个 tag，别硬编码——否则每次发版 notes 区间都是错的
r = run(["git", "describe", "--tags", "--abbrev=0", "HEAD^"])
prev_tag = (r.stdout or "").strip()
if prev_tag:
    r = run(["git", "log", "--pretty=format:%s", f"{prev_tag}..HEAD"])
    new_commits = [l for l in (r.stdout or "").splitlines() if l.strip()]
    print(f"  对比基线：{prev_tag}")
else:
    # 没有上一个 tag（首次发版）时退化成最近 10 条
    r = run(["git", "log", "--pretty=format:%s", "-10"])
    new_commits = [l for l in (r.stdout or "").splitlines() if l.strip()]
    print("  未找到上一个 tag，取最近 10 条提交")

notes = [
    f"## Codex 小帮手 v{APP_VERSION}",
    "",
    "### 更新内容",
    "",
]
for c in new_commits:
    notes.append(f"- {c}")
notes += [
    "",
    "### 下载",
    "",
    f"下载 `CodexHelper.exe`，双击运行即可（无需安装 Node 或 Python）。",
    "",
    "> 若系统缺少 WebView2 运行时，程序会自动降级为 tkinter 界面；",
    "> 装上 WebView2 后自动恢复完整界面。",
    "",
    "### 校验",
    "",
    f"| 项目 | 值 |",
    f"|---|---|",
    f"| 文件大小 | {DIST_EXE.stat().st_size:,} 字节 |",
    f"| 打包时间 | {time.strftime('%Y-%m-%d %H:%M:%S')} |",
    f"| 自检 | preflight_check.py 20 项全绿 |",
]
notes_text = "\n".join(notes)
print(notes_text)

if DRY_RUN:
    step("预览模式：到此为止")
    print("  未创建 Release。去掉 --dry-run 可真正发版。")
    raise SystemExit(0)

# -------------------------------------------------- 7. 创建 Release ----
step("7. 创建 GitHub Release")
r = run(["gh", "--version"])
if r.returncode != 0:
    die("未找到 gh，请先安装 GitHub CLI 并登录（gh auth login）")

notes_file = HERE / "dist" / f"release-notes-v{APP_VERSION}.md"
notes_file.parent.mkdir(parents=True, exist_ok=True)
notes_file.write_text(notes_text, encoding="utf-8")

asset_tmp = HERE / "dist" / ASSET_NAME
import shutil
shutil.copy2(DIST_EXE, asset_tmp)

cmd = ["gh", "release", "create", TAG, str(asset_tmp),
       "--title", f"v{APP_VERSION}", "--notes-file", str(notes_file)]
print("  执行：", " ".join(f'"{c}"' if " " in c else c for c in cmd))
r = run(cmd)
print((r.stdout or "").strip())
if r.returncode != 0:
    print((r.stderr or "").strip()[:2000])
    die("创建 Release 失败")

print(f"\n发版完成：{TAG}")
print(f"  https://github.com/Xiao-zhiii/NodeCodexSetup/releases/tag/{TAG}")
