# -*- coding: utf-8 -*-
"""Codex 插件修复后端：fast-patch 技能安装、Full Access、/goal 指令。"""
import io
import os
import re
import shutil
import urllib.request
import zipfile

from .constants import (FIX_PROMPT, GOAL_MD_BODY, SKILL_DIR_NAME, SKILL_REPO,
                        SKILL_ZIP_URLS)


def codex_home(home=None) -> str:
    """Codex CLI 数据目录（~/.codex）。home 参数用于测试时重定向。"""
    return os.path.join(home or os.path.expanduser("~"), ".codex")


def find_patch_skill(home=None):
    """检测本机是否已安装 fast-patch 修复技能，返回技能目录；未安装返回 None。"""
    skills = os.path.join(codex_home(home), "skills")
    for n in (SKILL_DIR_NAME, "codex-windows-fast-patch"):
        p = os.path.join(skills, n, "SKILL.md")
        if os.path.isfile(p):
            return os.path.dirname(p)
    if os.path.isdir(skills):
        for d in os.listdir(skills):
            if "fast-patch" in d.lower():
                p = os.path.join(skills, d, "SKILL.md")
                if os.path.isfile(p):
                    return os.path.dirname(p)
    return None


def install_patch_skill(log=print, home=None) -> str:
    """从 GitHub 下载技能仓库 zip，解压安装到 ~/.codex/skills/<技能名>/。"""
    dest = os.path.join(codex_home(home), "skills", SKILL_DIR_NAME)
    data = None
    for url in SKILL_ZIP_URLS:
        try:
            log("下载修复技能：" + url)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            if len(data) < 1024:
                raise IOError("下载内容异常（过小）")
            break
        except Exception as e:
            log(f"该下载源失败：{e}", "warn")
            data = None
    if data is None:
        raise RuntimeError(
            "所有下载源均失败，无法下载修复技能。请检查网络，或手动从 "
            f"https://github.com/{SKILL_REPO} 下载 zip 解压到：{dest}")

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.rmtree(dest, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.strip("/")]
        tops = {n.split("/")[0] for n in names}
        root = ""
        if len(tops) == 1:
            cand = next(iter(tops))
            if all(n == cand or n.startswith(cand + "/") for n in names):
                root = cand + "/"
        for n in names:
            rel = n[len(root):] if root else n
            if not rel or rel.endswith("/"):
                continue
            rel = rel.replace("/", os.sep)
            if rel.startswith("..") or os.path.isabs(rel):
                continue  # 防路径穿越
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(n) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    if not os.path.isfile(os.path.join(dest, "SKILL.md")):
        raise RuntimeError("技能包解压后未找到 SKILL.md，安装失败。")
    log(f"修复技能安装完成：{dest}", "ok")
    return dest


def ensure_full_access(log=print, home=None) -> str:
    """把 Codex 权限设为 Full Access：在 ~/.codex/config.toml 顶部写入
    approval_policy = "never" 与 sandbox_mode = "danger-full-access"。
    已有同名键会被移除后统一写回顶部；文件其余内容（含各 [table] 段）原样保留，
    原文件备份为 config.toml.nodecodexsetup.bak。"""
    cfg = os.path.join(codex_home(home), "config.toml")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    had = os.path.isfile(cfg)
    old = ""
    if had:
        with open(cfg, "r", encoding="utf-8", errors="replace") as f:
            old = f.read()
        try:
            shutil.copy2(cfg, cfg + ".nodecodexsetup.bak")
        except Exception:
            pass
    kept = [ln for ln in old.splitlines()
            if not re.match(r"^(approval_policy|sandbox_mode)\s*=", ln)]
    header = [
        "# ---- 由 NodeCodexSetup（小枳ai分享）设置：Codex Full Access 权限 ----",
        'approval_policy = "never"',
        'sandbox_mode = "danger-full-access"',
        "",
    ]
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("\n".join(header + kept).rstrip("\n") + "\n")
    log("Codex 权限已设置为 Full Access（approval_policy=never、"
        "sandbox_mode=danger-full-access）", "ok")
    if had:
        log("原配置已备份为 config.toml.nodecodexsetup.bak")
    return cfg


def ensure_goal_prompt(log=print, home=None) -> str:
    """写入 ~/.codex/prompts/goal.md，使 codex TUI 中输入 /goal 即自动调取
    fast-patch 技能执行插件修复（codex 会把 prompts 目录下的 .md 注册为斜杠命令）。"""
    pdir = os.path.join(codex_home(home), "prompts")
    os.makedirs(pdir, exist_ok=True)
    p = os.path.join(pdir, "goal.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(GOAL_MD_BODY.format(prompt=FIX_PROMPT))
    log("已写入 /goal 自定义指令：" + p, "ok")
    return p
