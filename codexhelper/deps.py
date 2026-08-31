# -*- coding: utf-8 -*-
"""运行时依赖检测与安装：WebView2 / Python Manager / VC++ 运行库。

## 为什么要有这个模块

程序依赖三个运行时，缺任何一个都会出问题：
- **WebView2**：缺了界面会降级成 tkinter（功能不全）
- **Python Manager**：MSIX 包，部分一键操作依赖它
- **VC++ x64**：pywebview / pythonnet 的原生依赖，缺了直接起不来

以前只能靠用户自己去发现、自己去下载安装包。
现在把三个安装包内置，检测到缺失就提示一键安装。

## 设计要点

1. **检测与安装分离**：`scan()` 只负责查（快、无副作用），
   安装在独立任务里跑（`install_dep`），不阻塞界面。
2. **安装包来源**：优先用内置文件（打包时放进 `deps/` 目录），
   内置文件不存在时回退在线下载，保证开发环境和瘦身包也能用。
3. **每个依赖的判据都写清楚**：注册表/文件系统/包管理器各有不同，
   注释里记录了为什么用这个判据，方便以后排查"明明装了却检测不到"。
4. **安装命令要静默**：用 `/silent` `/quiet` 等参数，
   不弹 UAC 之外的新窗口打断用户。

## 扩展新依赖

在 `DEPS` 里加一条即可，`scan()` 与安装逻辑会自动覆盖。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ------------------------------------------------------------ 常量定义 --

# WebView2 Runtime 的 EdgeUpdate 产品 GUID（固定值，Microsoft 文档可查）
_WV2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# VC++ 运行库：VC++ 2015-2022 共用 14.0 这个版本号
_VC_KEY = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"

# Python Manager 的 MSIX 包名（用于 Get-AppxPackage 查询）
_PM_PACKAGE = "PythonManager"


def deps_dir() -> Path:
    """内置安装包目录。

    - 打包后：`exe 所在目录/deps/`（Inno Setup 会装到这里）
    - onefile 模式：`sys._MEIPASS/deps/`
    - 开发环境：`项目根/deps/`
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "deps"
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "deps"
    return Path(__file__).resolve().parents[2] / "deps"


def _reg_open(hive, path, view=0):
    """打开注册表键，成功返回句柄，失败返回 None。"""
    try:
        import winreg
        return winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
    except Exception:
        return None


def _webview2_installed() -> tuple[bool, str]:
    """检测 WebView2 运行时。

    三个来源任一命中即认为已装：
    1. 独立 WebView2 Runtime（注册表 EdgeUpdate\\Clients）
    2. Edge 自带的 msedgewebview2.exe
    3. 非 Windows 平台不检测（macOS/Linux 由 pywebview 自己处理）
    """
    if os.name != "nt":
        return True, "非 Windows 平台，跳过"

    try:
        import winreg
    except ImportError:
        return False, "无法导入 winreg"

    paths = tuple(
        base + "\\" + _WV2_GUID for base in (
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients",
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients",
        ))
    # 32/64 位视图都要看：运行时可能只装在其中一个
    for hive_name, hive in (("HKLM", winreg.HKEY_LOCAL_MACHINE),
                            ("HKCU", winreg.HKEY_CURRENT_USER)):
        for path in paths:
            for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                h = _reg_open(hive, path, view)
                if h is not None:
                    try:
                        h.Close()
                    except Exception:
                        pass
                    return True, f"{hive_name}\\{path}"

    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        d = os.environ.get(env)
        if d and (Path(d) / "Microsoft" / "Edge" / "Application"
                  / "msedgewebview2.exe").is_file():
            return True, f"{env}\\Microsoft\\Edge\\Application"

    return False, ""


def _vc_redist_installed() -> tuple[bool, str]:
    r"""检测 VC++ 2015-2022 x64 运行库。

    注册表 ``VisualStudio\14.0\VC\Runtimes\x64`` 下 Installed=1 即认为已装。
    VC++ 2015/2017/2019/2022 共用 14.x 这个主版本号，二进制兼容，
    所以只要 14.x 装了就够用，不必纠结具体是哪一年份的包。
    """
    if os.name != "nt":
        return True, "非 Windows 平台，跳过"
    try:
        import winreg
    except ImportError:
        return False, "无法导入 winreg"

    for hive_name, hive in (("HKLM", winreg.HKEY_LOCAL_MACHINE),
                            ("HKCU", winreg.HKEY_CURRENT_USER)):
        for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            h = _reg_open(hive, _VC_KEY, view)
            if h is None:
                continue
            try:
                installed = winreg.QueryValueEx(h, "Installed")[0]
                if installed == 1:
                    try:
                        ver = winreg.QueryValueEx(h, "Version")[0]
                    except Exception:
                        ver = "14.x"
                    h.Close()
                    return True, f"{hive_name} {ver}"
                h.Close()
            except Exception:
                try:
                    h.Close()
                except Exception:
                    pass
    # 兜底：直接看系统目录里有没有运行库 DLL
    sysdir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    for dll in ("vcruntime140.dll", "msvcp140.dll"):
        if (sysdir / dll).is_file():
            return True, f"System32\\{dll}"
    return False, ""


def _python_manager_installed() -> tuple[bool, str]:
    """检测 Python Manager（MSIX 包）。

    MSIX/APPX 应用不走注册表卸载项，必须用 Get-AppxPackage 查。
    PowerShell 冷启动约 1-2 秒，所以结果要缓存，不要每次界面刷新都查。
    """
    if os.name != "nt":
        return True, "非 Windows 平台，跳过"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-AppxPackage -Name '*{_PM_PACKAGE}*' | "
             f"Select-Object -First 1).Name"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        name = (r.stdout or "").strip()
        if name:
            return True, name
        return False, ""
    except Exception as exc:  # noqa: BLE001
        # PowerShell 不可用时不要误报"已安装"，但也不要判定为"必须装"
        return False, f"检测失败：{exc}"


# ------------------------------------------------------- 依赖定义表 ----

DEPS: tuple[dict[str, Any], ...] = (
    {
        "id": "webview2",
        "name": "WebView2 运行时",
        "desc": "程序界面依赖它。缺失时会自动降级为简化界面，功能不全。",
        "required": True,
        "file": "MicrosoftEdgeWebView2RuntimeInstallerX64.exe",
        "url": "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
        "detect": _webview2_installed,
        # /silent 静默安装，不弹进度窗
        "install_args": ["/silent", "/install"],
        "online_args": [],
    },
    {
        "id": "python_manager",
        "name": "Python Manager",
        "desc": "Codex 部分一键操作依赖此组件。",
        "required": False,
        "file": "python-manager-26.3.msix",
        "url": "",
        "detect": _python_manager_installed,
        # MSIX 走 Add-AppxPackage，不走命令行参数
        "install_args": [],
        "msix": True,
    },
    {
        "id": "vc_redist",
        "name": "VC++ 运行库 (x64)",
        "desc": "程序原生组件依赖它，缺失会导致无法启动。",
        "required": True,
        "file": "VC_redist.x64.exe",
        "url": "https://aka.ms/vs/17/release/vc_redist.x64.exe",
        "detect": _vc_redist_installed,
        "install_args": ["/quiet", "/norestart"],
        "online_args": ["/quiet", "/norestart"],
    },
)


def _dep_by_id(dep_id: str) -> dict[str, Any] | None:
    for d in DEPS:
        if d["id"] == dep_id:
            return d
    return None


# ------------------------------------------------------------ 扫描 ----

_SCAN_CACHE: dict[str, Any] | None = None


def scan(force: bool = False) -> dict[str, Any]:
    """扫描全部依赖。结果会缓存（PowerShell 检测较慢）。

    返回：
        {
          "ok": True,
          "items": [ {id, name, desc, required, installed, where,
                      has_local, local_path, size, url}, ... ],
          "missing": [ ... 未安装的 id ... ],
          "all_ok": True/False,
        }
    """
    global _SCAN_CACHE
    if _SCAN_CACHE is not None and not force:
        return _SCAN_CACHE

    ddir = deps_dir()
    items = []
    for d in DEPS:
        try:
            installed, where = d["detect"]()
        except Exception as exc:  # noqa: BLE001
            installed, where = False, f"检测异常：{exc}"

        local = ddir / d["file"]
        items.append({
            "id": d["id"],
            "name": d["name"],
            "desc": d["desc"],
            "required": bool(d["required"]),
            "installed": bool(installed),
            "where": where or "",
            "has_local": local.is_file(),
            "local_path": str(local) if local.is_file() else "",
            "size": local.stat().st_size if local.is_file() else 0,
            "url": d.get("url", ""),
        })

    missing = [i["id"] for i in items if not i["installed"]]
    result = {
        "ok": True,
        "items": items,
        "missing": missing,
        # all_ok 只看必需项：可选项缺了不阻塞
        "all_ok": all(i["installed"] for i in items if i["required"]),
        "deps_dir": str(ddir),
    }
    _SCAN_CACHE = result
    return result


def invalidate_cache() -> None:
    """安装后调用，清掉缓存，下次 scan 会重新检测。"""
    global _SCAN_CACHE
    _SCAN_CACHE = None


# ------------------------------------------------------------ 安装 ----

def build_install_cmd(dep_id: str) -> dict[str, Any]:
    """构造安装命令。优先内置文件，没有就回退在线安装。

    返回 {ok, kind, argv, path, error}
      kind: "local" | "online" | "msix" | "powershell"
    """
    d = _dep_by_id(dep_id)
    if d is None:
        return {"ok": False, "error": f"未知依赖：{dep_id}"}

    # 1) 内置安装包
    local = deps_dir() / d["file"]
    if local.is_file():
        if d.get("msix"):
            return {
                "ok": True,
                "kind": "powershell",
                "argv": [
                    "powershell", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-Command",
                    f"Add-AppxPackage -Path '{local}'",
                ],
                "path": str(local),
            }
        return {
            "ok": True,
            "kind": "local",
            "argv": [str(local)] + list(d.get("install_args") or []),
            "path": str(local),
        }

    # 2) 在线兜底
    if d.get("url"):
        return {
            "ok": True,
            "kind": "online",
            "argv": [d["url"]],
            "path": d["url"],
            "note": "内置安装包缺失，将打开下载页",
        }
    if d.get("msix"):
        return {"ok": False,
                "error": f"未找到内置安装包 {d['file']}，且该组件无在线下载地址"}

    return {"ok": False,
            "error": f"未找到内置安装包：{d['file']}"}


def install_dep(dep_id: str, timeout: int = 900) -> dict[str, Any]:
    """安装单个依赖（阻塞）。返回 {ok, dep, message, returncode}。

    超时默认 15 分钟——WebView2 在线安装可能很慢。
    """
    d = _dep_by_id(dep_id)
    if d is None:
        return {"ok": False, "dep": dep_id, "message": f"未知依赖：{dep_id}"}

    cmd = build_install_cmd(dep_id)
    if not cmd.get("ok"):
        return {"ok": False, "dep": dep_id,
                "message": cmd.get("error", "无法构造安装命令")}

    argv = cmd["argv"]
    try:
        if cmd["kind"] == "online":
            # 在线兜底：只能打开浏览器让用户自己下
            os.startfile(cmd["path"])  # noqa: S606
            return {
                "ok": True, "dep": dep_id, "manual": True,
                "message": f"已打开 {d['name']} 下载页，请手动下载安装",
            }

        proc = subprocess.run(
            argv, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rc = proc.returncode
        ok = rc == 0
        invalidate_cache()
        return {
            "ok": ok,
            "dep": dep_id,
            "returncode": rc,
            "message": (f"{d['name']} 安装完成" if ok
                        else f"{d['name']} 安装失败（退出码 {rc}）"),
            "stderr": (proc.stderr or "")[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "dep": dep_id, "message": "安装超时"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "dep": dep_id, "message": f"安装异常：{exc}"}


def missing_required() -> list[str]:
    """返回缺失的必需依赖 id 列表（供启动时提示用）。"""
    try:
        r = scan()
    except Exception:
        return []
    return [i["id"] for i in r["items"]
            if i["required"] and not i["installed"]]
