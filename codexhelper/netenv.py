# -*- coding: utf-8 -*-
"""Codex 环境检测后端（v1.5.0）：
① 代理检测（Windows 系统代理 + 环境变量）
② ~/.codex 目录 .env 文件检查
③ 系统/用户/进程三级环境变量中与 代理 / API Key / Codex 相关条目的收集。

安全约定：密钥类值只显示首尾片段（打码），代理地址不涉密、完整显示——
本工具面向公开分发，界面截图不应泄露完整密钥。
"""
import os
import re

from .codex_fix import codex_home

UA = {"User-Agent": "Mozilla/5.0"}

# 变量名/值中视为“代理类”的关键字
_PROXY_NAME_HINTS = ("proxy",)
# 变量名/值中视为“敏感/账号类”的关键字（命中即打码显示）
_SECRET_NAME_HINTS = ("api_key", "apikey", "api-key", "api key", "token",
                      "secret", "password", "credential")
_SECRET_VALUE_HINTS = ("sk-", "api key", "apikey", "api_key")
# 用户点名要找的“codex 数据”类字样
_CODEX_HINTS = ("codex", "openai", "anthropic")

_ENV_SCOPES = [
    ("用户变量", "HKCU"),
    ("系统变量", "HKLM"),
]


# ------------------------------------------------------------ 代理检测 ----

def _registry_system_proxy():
    """读 Windows 系统代理（WinINET，注册表）。返回 'host:port' 或 None。"""
    if os.name != "nt":
        return None
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
            if not enable:
                return None
            try:
                server, _ = winreg.QueryValueEx(k, "ProxyServer")
            except OSError:
                return None
        finally:
            winreg.CloseKey(k)
    except Exception:
        return None
    if not server:
        return None
    if "=" in server:          # 形如 "http=127.0.0.1:7890;https=127.0.0.1:7890"
        parts = {}
        for item in server.split(";"):
            if "=" in item:
                sch, addr = item.split("=", 1)
                parts[sch.strip().lower()] = addr.strip()
        server = parts.get("https") or parts.get("http") or next(iter(parts.values()), "")
    server = server.strip()
    return server or None


def _env_proxy_from(mapping) -> str | None:
    """从一组环境变量里取代理地址（HTTPS_PROXY 优先于 HTTP_PROXY 优先于 ALL_PROXY）。"""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                "ALL_PROXY", "all_proxy"):
        v = (mapping.get(key) or "").strip()
        if v:
            return v
    return None


def detect_proxy():
    """检测本机代理。返回 dict：
    enabled / server('host:port') / url('http://host:port' 或原样) / source('系统代理'|'环境变量')"""
    server = _registry_system_proxy()
    if server:
        url = server if "://" in server else "http://" + server
        return {"enabled": True, "server": server, "url": url, "source": "系统代理"}
    url = _env_proxy_from(os.environ)
    if url:
        return {"enabled": True, "server": url.split("://", 1)[-1], "url": url,
                "source": "环境变量"}
    return {"enabled": False, "server": None, "url": None, "source": None}


def build_opener(proxy_url=None):
    """按代理地址构造 urllib opener；proxy_url 为空返回 None（用默认直连）。"""
    import urllib.request
    if not proxy_url:
        return None
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    return urllib.request.build_opener(handler)


# --------------------------------------------------------- .env / 变量 ----

def _mask(name: str, value: str) -> str:
    """密钥类值打码（保留首 6 尾 4）；代理地址与普通路径明文显示，
    超长非敏感值仅截断不遮蔽。"""
    low = name.lower()
    if "proxy" in low or value.lower().startswith(("http://", "https://", "socks")):
        return value
    if not _is_secret(name, value):
        return value if len(value) <= 120 else value[:117] + "…"
    if len(value) > 14:
        return value[:6] + "…" + value[-4:] + f"（共{len(value)}字符）"
    return "••••••"


def _is_secret(name: str, value: str) -> bool:
    low = (name + " " + value).lower()
    return any(h in low for h in _SECRET_NAME_HINTS) or any(h in value for h in _SECRET_VALUE_HINTS)


def parse_dotenv(path):
    """解析 .env 文本：返回 [(key, raw_value)]，忽略注释与空行。"""
    entries = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key:
                    entries.append((key, val))
    except OSError:
        pass
    return entries


def _reg_env_scope(hive, path, source_label, out):
    """枚举注册表某个环境变量作用域，命中关键字的追加到 out。"""
    if os.name != "nt":
        return
    import winreg
    try:
        k = winreg.OpenKey(hive, path)
    except OSError:
        return
    try:
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            i += 1
            _maybe_record(source_label, name, str(value), out)
    finally:
        winreg.CloseKey(k)


def _maybe_record(source, name, value, out, force=False):
    """命中 代理 / 密钥 / Codex 关键字才记录，避免罗列整个 PATH 之类噪声。"""
    low_name, low_val = name.lower(), (value or "").lower()
    hit = (any(h in low_name for h in _PROXY_NAME_HINTS)
           or any(h in low_name for h in _CODEX_HINTS)
           or any(h in low_name or h in low_val for h in _SECRET_NAME_HINTS)
           or any(h in value for h in _SECRET_VALUE_HINTS)
           or force)
    if not hit:
        return
    out.append({"source": source, "name": name, "value": value,
                "masked": _mask(name, value),
                "secret": _is_secret(name, value),
                "proxy": "proxy" in low_name or low_val.startswith(("http://127.0.0.1", "socks"))})


def scan_codex_env(home=None) -> dict:
    """【Codex 环境检测】分页的后端入口。"""
    from .util import get_user_env  # 复用注册表读取
    base = codex_home(home)
    env_path = os.path.join(base, ".env")
    exists = os.path.isfile(env_path)
    entries = parse_dotenv(env_path) if exists else []

    vars_out = []
    # ① 进程环境（本工具实际看到的）
    for name, value in os.environ.items():
        _maybe_record("当前进程", name, value, vars_out)
    # ② 用户变量 / ③ 系统变量（注册表全量枚举）
    import winreg
    _reg_env_scope(winreg.HKEY_CURRENT_USER, "Environment", "用户变量", vars_out)
    _reg_env_scope(winreg.HKEY_LOCAL_MACHINE,
                   r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                   "系统变量", vars_out)
    # .env 里的条目也算“环境”发现
    dotenv_items = [{"name": k, "value": v, "masked": _mask(k, v),
                     "secret": _is_secret(k, v),
                     "proxy": "proxy" in k.lower()} for k, v in entries]

    # 去重（同名同源保第一条），按 来源→名称 排序
    seen = set()
    uniq = []
    for item in vars_out:
        key = (item["source"], item["name"].lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    uniq.sort(key=lambda x: (x["source"], x["name"].lower()))

    return {
        "home": base,
        "env_file": {"path": env_path, "exists": exists,
                     "count": len(entries), "entries": dotenv_items},
        "proxy": detect_proxy(),
        "cli_path": get_user_env("CODEX_CLI_PATH"),
        "vars": uniq,
    }
