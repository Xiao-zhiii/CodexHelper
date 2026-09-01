# -*- coding: utf-8 -*-
"""UWP 回环豁免（Loopback Exemption）：让 UWP 应用能连本机代理。

## 为什么要有这个模块

Windows 的 UWP 应用跑在 AppContainer 沙箱里，**默认禁止连接 127.0.0.1**。
而系统代理恰恰把流量导向本机（如 `127.0.0.1:7888`），于是出现一个很迷惑的现象：
代理明明开着、浏览器正常，但 UWP 应用就是不走代理、一直转圈。

解除办法是把应用的 AppContainer SID 加入"回环豁免"列表。

**Codex 桌面端（`openai.codex`）本身就是 UWP 应用**——这不是顺手加的功能，
而是补一个真实缺口：用户想让 Codex 走本地代理（本地网关 / 镜像加速 / 抓包调试）时，
没有豁免就是连不上。微软商店同理，代理环境下下载更新基本不可用。

## 技术路径（已在本机实测通过）

1. **枚举 UWP 应用**：注册表 `AppContainer\\Mappings`，每项含 SID 与包名（Moniker）。
   比 PowerShell `Get-AppxPackage` 快得多——没有 PowerShell 冷启动那 1~2 秒开销。
2. **读取豁免列表**：`CheckNetIsolation.exe LoopbackExempt -s`
3. **增删豁免**：`CheckNetIsolation.exe LoopbackExempt -a|-d -n=<包名>`

## 编码坑（重点）

`CheckNetIsolation.exe` 的输出是**中文**（"列出环回免除的 AppContainer"），
且控制台编码随系统区域变化（GBK / UTF-8 都可能出现），直接 decode 很容易乱码。

但**包名与 SID 都是纯 ASCII**，所以这里一律用 **bytes 正则**提取，
不依赖任何解码结果——中文部分是否乱码完全不影响解析。
仅当需要把错误信息展示给用户时，才用 `_decode()` 尽力解码。
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any

# ------------------------------------------------------------ 目标应用 ----
# 只关心这两个（用户明确要求）：都是"不走代理就废掉一半功能"的典型。
# 以后要加，往这里补一条即可，scan() 与 set_exempt() 自动覆盖。
TARGETS: tuple[dict[str, str], ...] = (
    {
        "id": "codex",
        "name": "Codex 桌面端",
        "pattern": "openai.codex",
        "desc": "OpenAI Codex 桌面应用（UWP）。要让它走本机代理、本地网关或抓包调试，"
                "必须先开启回环豁免，否则完全连不上。",
    },
    {
        "id": "store",
        "name": "微软商店",
        "pattern": "microsoft.windowsstore",
        "desc": "Microsoft Store。代理环境下下载 / 更新需要豁免，否则会一直转圈或报网络错误。",
    },
)

# AppContainer 映射表：包名(Moniker) 与 SID 的对应关系
_MAPPINGS_KEY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows"
    r"\CurrentVersion\AppContainer\Mappings"
)

# 包名形如 openai.codex_2p2nqsd0c76g0 —— 发布者 ID 固定 13 位。
# 用字节正则：既避开中文编码问题，也能精确命中"包名"而不误伤路径等文本。
_PKG_BYTES_RE = re.compile(rb"[a-z0-9][a-z0-9.\-]*_[a-z0-9]{13}")
_SID_BYTES_RE = re.compile(rb"S-1-15-2-[0-9\-]+")


# -------------------------------------------------------------- 工具函数 --

def _decode(raw: bytes) -> str:
    """尽力解码子进程输出：UTF-8 → GBK → 系统 ANSI → 兜底替换。"""
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _run(args: list[str], timeout: int = 30) -> tuple[int, bytes, bytes]:
    """执行子进程，返回 (returncode, stdout_bytes, stderr_bytes)。

    刻意不做解码：调用方按需用 bytes 正则提取 ASCII 片段即可，
    中文部分乱码也不影响包名 / SID 的解析。
    """
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout or b"", p.stderr or b""
    except FileNotFoundError:
        return 127, b"", "CheckNetIsolation.exe 未找到".encode("utf-8")
    except subprocess.TimeoutExpired:
        return 124, b"", "执行超时".encode("utf-8")


# ------------------------------------------------------------ 状态读取 ----

def _exempted() -> set[tuple[str, str]]:
    """读取当前回环豁免列表，返回 {(包名, SID), ...}。

    输出形态（中文，编码随区域变化）：
        列出环回免除的 AppContainer
        [1] -----------------------------------------------------------------
            名称: microsoft.windowsstore_8wekyb3d8bbwe
            SID:  S-1-15-2-1609473798-...-1760938157
        完成。

    包名与 SID 分行出现，因此逐行扫描、配对：
    记住最近见到的包名，遇到 SID 就与之配对。
    """
    rc, out, _err = _run(["CheckNetIsolation.exe", "LoopbackExempt", "-s"])
    if rc != 0:
        return set()
    pairs: set[tuple[str, str]] = set()
    current = ""
    for line in out.splitlines():
        m = _PKG_BYTES_RE.search(line)
        if m:
            current = m.group(0).decode("ascii")
            continue
        m = _SID_BYTES_RE.search(line)
        if m and current:
            pairs.add((current, m.group(0).decode("ascii")))
            current = ""
    return pairs


def _appcontainers() -> list[dict[str, str]]:
    """枚举本机 AppContainer：返回 [{"sid","package","display"}, ...]。"""
    if os.name != "nt":
        return []
    import winreg
    out: list[dict[str, str]] = []
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MAPPINGS_KEY)
    except OSError:
        return out
    try:
        i = 0
        while True:
            try:
                sid = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            try:
                sk = winreg.OpenKey(k, sid)
            except OSError:
                continue
            moniker = ""
            display = ""
            try:
                moniker, _ = winreg.QueryValueEx(sk, "Moniker")
            except OSError:
                pass
            try:
                display, _ = winreg.QueryValueEx(sk, "DisplayName")
            except OSError:
                pass
            winreg.CloseKey(sk)
            if moniker:
                out.append({"sid": sid, "package": moniker, "display": display})
    finally:
        winreg.CloseKey(k)
    return out


def scan() -> dict[str, Any]:
    """检测目标 UWP 应用的安装与豁免状态。**只读，无副作用**。

    返回：
        ok/supported/admin/items/exempted_count/error
        items 每项：id/name/pattern/desc/installed/package/sid/exempt/status
    """
    if os.name != "nt":
        return {"ok": False, "supported": False, "admin": False, "items": [],
                "exempted_count": 0, "error": "仅 Windows 支持 UWP 回环豁免"}

    from .util import is_admin

    pairs = _exempted()
    exempt_pkgs = {p.lower() for p, _ in pairs}
    exempt_sids = {s for _, s in pairs}
    containers = _appcontainers()

    items: list[dict[str, Any]] = []
    for t in TARGETS:
        # 精确匹配 "<pattern>_" 前缀，避免 openai.codex 误命中 openai.codexfoo
        pat = t["pattern"].lower() + "_"
        matched = [c for c in containers if c["package"].lower().startswith(pat)]
        if not matched:
            items.append({
                **t,
                "installed": False, "package": "", "sid": "", "exempt": False,
                "status": "未安装",
            })
            continue
        # 同名可能有多个容器（多版本 / 系统组件）；
        # 取第一个展示，但只要有一个已豁免就认为整体已豁免。
        head = matched[0]
        is_ex = any(c["package"].lower() in exempt_pkgs or c["sid"] in exempt_sids
                    for c in matched)
        items.append({
            **t,
            "installed": True,
            "package": head["package"],
            "sid": head["sid"],
            "exempt": is_ex,
            "status": "已豁免" if is_ex else "未豁免",
            "count": len(matched),
        })

    return {
        "ok": True,
        "supported": True,
        "admin": is_admin(),
        "items": items,
        "exempted_count": len(pairs),
    }


# ------------------------------------------------------------ 写操作 ------

def set_exempt(app_id: str, enable: bool) -> dict[str, Any]:
    """开启 / 关闭某个目标应用的回环豁免。**需要管理员权限**。

    写完会重新 scan() 一次复核——退出码为 0 不代表真的生效
    （例如权限不足时部分 Windows 版本仍返回 0），以复核结果为准。
    """
    if os.name != "nt":
        return {"ok": False, "error": "仅 Windows 支持 UWP 回环豁免"}

    from .util import is_admin

    st = scan()
    item = next((i for i in st["items"] if i["id"] == app_id), None)
    if not item:
        return {"ok": False, "error": f"未知目标：{app_id}"}
    if not item.get("installed"):
        return {"ok": False, "error": f"{item['name']} 未安装，无需豁免"}

    pkg = item.get("package") or ""
    if not pkg:
        return {"ok": False, "error": "未取到包名（AppContainer 信息缺失）"}

    flag = "-a" if enable else "-d"
    rc, out, err = _run(
        ["CheckNetIsolation.exe", "LoopbackExempt", flag, f"-n={pkg}"])

    if rc != 0:
        detail = (_decode(err) or _decode(out) or f"退出码 {rc}").strip()
        if not is_admin():
            detail = "需要管理员权限。" + detail
        return {"ok": False, "error": detail, "id": app_id, "name": item["name"]}

    # 复核：以实际状态为准
    after = scan()
    now = next((i for i in after["items"] if i["id"] == app_id), {})
    effective = bool(now.get("exempt")) == bool(enable)
    action = "开启" if enable else "关闭"
    return {
        "ok": effective,
        "id": app_id,
        "name": item["name"],
        "package": pkg,
        "enabled": bool(enable),
        "exempt": bool(now.get("exempt")),
        "message": (f"{item['name']} 已{action}回环豁免"
                    if effective else
                    f"{item['name']} {action}未生效，请确认以管理员身份运行"),
        "scan": after,
    }
