# -*- coding: utf-8 -*-
"""Codex 存储路径解析 —— 保证在任何 Windows 电脑上都能定位到 .codex。

## 为什么需要这个模块

Codex 把会话文件的**绝对路径**写进 `state_5.sqlite` 的 `threads.rollout_path`，
例如 `C:\\Users\\张三\\.codex\\sessions\\2026\\08\\29\\rollout-….jsonl`。
这带来三个跨机器问题：

1. **用户名不同**：换电脑（或换个 Windows 账户）后，路径里的 `张三` 对不上，
   文件明明在磁盘上却读不到。
2. **盘符不同**：用户把 `%USERPROFILE%` 重定向到 D 盘，路径里的 `C:` 失效。
3. **`\\\\?\\` 长路径前缀**：本机实测 `rollout_path` 有两种写法混用——
   `C:\\Users\\…` 和 `\\\\?\\C:\\Users\\…`（Win32 长路径前缀），直接字符串拼接会出错。

因此本模块做两件事：
- **定位**：按 Codex 官方与社区工具的优先级解析出当前机器的 CODEX_HOME。
- **重定位**：把 DB 里的历史绝对路径"截取相对部分 + 拼到当前 CODEX_HOME"，
  使其在新机器上重新可用（见 `relocate_rollout`）。

## 解析优先级

参考 codex-provider-sync（github.com/Dailin521/codex-provider-sync）的
SQLite Home 解析顺序，并结合 Codex 官方的 `CODEX_HOME` 约定：

1. `CODEX_HOME` 环境变量
2. `~/.codex/config.toml` 根级 `sqlite_home` 的父目录
3. `CODEX_SQLITE_HOME` 环境变量的父目录
4. `%USERPROFILE%\\.codex`（默认布局）
5. `%USERPROFILE%` 经注册表 ProfileList 查到的真实位置（应对重定向）
6. Codex 桌面端（MSIX）沙箱内的 LocalCache 副本（兜底探测）

所有候选都经 `_valid()` 校验：必须存在 `sessions` 或 `state_5.sqlite` 之一。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Win32 长路径前缀：\\?\C:\... 或 \\?\UNC\server\share\...
_UNC_PREFIX = "\\\\?\\UNC\\"
_WIN32_PREFIX = "\\\\?\\"

# 相对部分的识别标记：路径中这些目录名之后的内容才是"可移植"的
_PORTABLE_MARKERS = ("sessions", "archived_sessions")


def strip_win32_prefix(p: str) -> str:
    """去掉 \\\\?\\ 长路径前缀，返回普通路径形式。

    \\\\?\\C:\\a  -> C:\\a
    \\\\?\\UNC\\srv\\share -> \\\\srv\\share
    """
    if not p:
        return ""
    if p.startswith(_UNC_PREFIX):
        return "\\\\" + p[len(_UNC_PREFIX):]
    if p.startswith(_WIN32_PREFIX):
        return p[len(_WIN32_PREFIX):]
    return p


def _valid(p: Path | None) -> bool:
    """候选目录是否像真正的 CODEX_HOME。"""
    if not p:
        return False
    try:
        if not p.is_dir():
            return False
        # 只要具备会话目录或状态库之一就认为有效
        return (p / "sessions").exists() or (p / "state_5.sqlite").exists()
    except OSError:
        return False


def _profile_dir() -> Path | None:
    """取当前用户主目录。

    优先 USERPROFILE；缺失时经注册表 ProfileList 解析（应对用户把
    主目录重定向到其它盘符，此时 USERPROFILE 可能未被正确继承）。
    """
    up = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if up:
        try:
            return Path(up)
        except Exception:
            pass
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList",
        ) as key:
            i = 0
            while True:
                try:
                    sid = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(key, sid) as sk:
                        img, _ = winreg.QueryValueEx(sk, "ProfileImagePath")
                except OSError:
                    continue
                # 只认当前登录用户的 SID（与 USERPROFILE 同源时优先前者）
                try:
                    import ctypes
                    import ctypes.wintypes as wt

                    adv = ctypes.windll.advapi32
                    token = wt.HANDLE()
                    adv.OpenProcessToken(ctypes.windll.kernel32.GetCurrentProcess(),
                                         0x0008, ctypes.byref(token))
                    needed = wt.DWORD()
                    adv.GetTokenInformation(token, 1, None, 0,
                                            ctypes.byref(needed))
                    buf = ctypes.create_string_buffer(needed.value)
                    adv.GetTokenInformation(token, 1, buf, needed,
                                            ctypes.byref(needed))
                    cur_sid = ctypes.windll.advapi32.ConvertSidToStringSidA
                    ptr = ctypes.c_char_p()
                    cur_sid(buf, ctypes.byref(ptr))
                    if ptr.value and ptr.value.decode() == sid:
                        return Path(img)
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _toml_root_scalar(text: str, key: str) -> str | None:
    """从 TOML 文本里取**根级**标量（不进任何 [section]）。

    只需支持 Codex config.toml 里的简单 `key = "value"` 形式，
    避免引入第三方 TOML 依赖（PyInstaller 打包体积考量）。
    """
    in_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_section = True
            continue
        if in_section:
            continue
        m = re.match(rf'^{re.escape(key)}\s*=\s*["\'](.+?)["\']\s*(?:#.*)?$', line)
        if m:
            return m.group(1)
    return None


def _from_config_toml(profile: Path) -> Path | None:
    """config.toml 根级 sqlite_home 的父目录。"""
    cfg = profile / ".codex" / "config.toml"
    if not cfg.is_file():
        return None
    try:
        val = _toml_root_scalar(cfg.read_text(encoding="utf-8", errors="replace"),
                                "sqlite_home")
    except Exception:
        return None
    if not val:
        return None
    p = Path(strip_win32_prefix(val))
    # sqlite_home 指向目录或某个 .sqlite 文件，取其所在目录的上一级
    return p.parent if p.name.endswith((".sqlite", ".db")) else p.parent


def _msix_candidates() -> list[Path]:
    """Codex 桌面端（MSIX 包）沙箱内的 LocalCache 副本。

    MSIX 应用的数据可能在
    %LOCALAPPDATA%\\Packages\\OpenAI.Codex_<hash>\\LocalCache\\Roaming\\.codex
    正常安装时它会被重定向到 %USERPROFILE%\\.codex，但某些升级/迁移场景
    下两边会各留一份，这里作为兜底探测。
    """
    out: list[Path] = []
    if os.name != "nt":
        return out
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return out
    pkg_root = Path(base) / "Packages"
    if not pkg_root.is_dir():
        return out
    try:
        for d in pkg_root.iterdir():
            if not d.name.startswith("OpenAI.Codex"):
                continue
            for sub in (d / "LocalCache" / "Roaming" / ".codex",
                        d / "LocalCache" / ".codex"):
                if sub.is_dir():
                    out.append(sub)
    except OSError:
        pass
    return out


def resolve_codex_home(explicit: str | None = None) -> Path | None:
    """解析当前机器的 CODEX_HOME。找不到返回 None。

    参数 explicit：调用方强制指定的目录（如用户手动选择），优先级最高。
    """
    cands: list[Path | None] = []

    if explicit:
        cands.append(Path(strip_win32_prefix(explicit)))

    # 1) CODEX_HOME 环境变量
    env = os.environ.get("CODEX_HOME")
    if env:
        cands.append(Path(strip_win32_prefix(env)))

    profile = _profile_dir()
    if profile:
        # 2) config.toml 的 sqlite_home
        cands.append(_from_config_toml(profile))
        # 3) 默认布局
        cands.append(profile / ".codex")

    # 4) CODEX_SQLITE_HOME 的父目录
    senv = os.environ.get("CODEX_SQLITE_HOME")
    if senv:
        sp = Path(strip_win32_prefix(senv))
        cands.append(sp.parent if sp.name.endswith(".sqlite") else sp.parent)

    # 5) MSIX 沙箱兜底
    cands.extend(_msix_candidates())

    for c in cands:
        if _valid(c):
            return c.resolve()
    # 全都无效时，若默认布局的父目录存在，仍返回默认路径（便于前端提示"未初始化"）
    if profile:
        default = profile / ".codex"
        try:
            return default.resolve() if default.parent.is_dir() else None
        except OSError:
            return None
    return None


def relocate_rollout(rollout_path: str, codex_home: Path | None = None) -> Path | None:
    """把 DB 里的历史绝对路径重定位到当前机器。

    这是"换电脑也能读到"的关键：DB 里存的是绝对路径，其中用户名/盘符
    属于旧机器。这里只保留 `sessions/`（或 `archived_sessions/`）开始的
    相对部分，再拼到当前 CODEX_HOME 上。

    例：
      旧：`C:\\Users\\张三\\.codex\\sessions\\2026\\08\\29\\rollout-x.jsonl`
      新：`D:\\Users\\李四\\.codex\\sessions\\2026\\08\\29\\rollout-x.jsonl`
    """
    if not rollout_path:
        return None
    home = codex_home or resolve_codex_home()
    if home is None:
        return None

    raw = strip_win32_prefix(str(rollout_path))
    # 统一分隔符后找可移植标记
    norm = raw.replace("/", "\\")
    idx = -1
    for marker in _PORTABLE_MARKERS:
        i = norm.rfind("\\" + marker + "\\")
        if i >= 0:
            idx = i + 1
            break
    if idx < 0:
        return None

    rel = norm[idx:]
    target = home / Path(rel)
    try:
        return target if target.exists() else None
    except OSError:
        return None


def rollout_display(rollout_path: str) -> str:
    """把 rollout 绝对路径转成便于展示的 `sessions/2026/08/29/xxx.jsonl` 形式。"""
    if not rollout_path:
        return ""
    norm = strip_win32_prefix(str(rollout_path)).replace("/", "\\")
    for marker in _PORTABLE_MARKERS:
        i = norm.rfind("\\" + marker + "\\")
        if i >= 0:
            return norm[i + 1:]
    return norm


def sessions_dir(codex_home: Path | None = None) -> Path | None:
    home = codex_home or resolve_codex_home()
    return (home / "sessions") if home else None


def archived_dir(codex_home: Path | None = None) -> Path | None:
    home = codex_home or resolve_codex_home()
    return (home / "archived_sessions") if home else None


def state_db(codex_home: Path | None = None) -> Path | None:
    """threads 表所在库。

    实测（2026-08-30）：`threads` 表在根目录 `state_5.sqlite`；
    新版 `sqlite/codex-dev.db` 里只有 `local_thread_catalog` 等桌面端
    自有表，**没有** threads。因此优先级必须是 state_5.sqlite 在前，
    切勿按"新版目录优先"的想当然排序。
    """
    home = codex_home or resolve_codex_home()
    if not home:
        return None
    for cand in (home / "state_5.sqlite",
                 home / "sqlite" / "state_5.sqlite",
                 home / "sqlite" / "codex-dev.db"):
        if cand.is_file():
            return cand
    return home / "state_5.sqlite"


def logs_db(codex_home: Path | None = None) -> Path | None:
    """logs_2.sqlite（运行日志库）。"""
    home = codex_home or resolve_codex_home()
    if not home:
        return None
    for cand in (home / "logs_2.sqlite", home / "sqlite" / "logs_2.sqlite"):
        if cand.is_file():
            return cand
    return home / "logs_2.sqlite"


def history_db(codex_home: Path | None = None) -> Path | None:
    """thread_history_1.sqlite（会话条目投影库）。"""
    home = codex_home or resolve_codex_home()
    if not home:
        return None
    for cand in (home / "thread_history_1.sqlite",
                 home / "sqlite" / "thread_history_1.sqlite"):
        if cand.is_file():
            return cand
    return home / "thread_history_1.sqlite"


def describe() -> dict:
    """给前端展示的路径诊断信息。"""
    home = resolve_codex_home()
    info = {
        "home": str(home) if home else None,
        "env_codex_home": os.environ.get("CODEX_HOME") or "",
        "env_codex_sqlite_home": os.environ.get("CODEX_SQLITE_HOME") or "",
        "userprofile": os.environ.get("USERPROFILE") or "",
        "exists": bool(home and home.is_dir()),
        "state_db": None, "logs_db": None, "sessions": None,
        "archived": None, "sessions_count": 0, "archived_count": 0,
    }
    if not home:
        return info
    sd, ld = state_db(home), logs_db(home)
    sdir, adir = sessions_dir(home), archived_dir(home)
    info["state_db"] = str(sd) if sd and sd.exists() else None
    info["logs_db"] = str(ld) if ld and ld.exists() else None
    info["sessions"] = str(sdir) if sdir and sdir.exists() else None
    info["archived"] = str(adir) if adir and adir.exists() else None
    try:
        info["sessions_count"] = (len(list(sdir.rglob("*.jsonl")))
                                  if sdir and sdir.exists() else 0)
        info["archived_count"] = (len(list(adir.rglob("*.jsonl")))
                                  if adir and adir.exists() else 0)
    except OSError:
        pass
    return info
