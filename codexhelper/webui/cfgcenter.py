# -*- coding: utf-8 -*-
"""Codex 配置中心后端（v1.6.0 自用户项目 F:/codex helper 整体收编）。

来源：本地工具 "Codex Helper"（ThreadingHTTPServer + 浏览器界面，
读取 .codex / .cc-switch / Codex++ 配置并做供应商连通性测试）。
本模块保留其后端能力：文件夹发现、系统信息、config.toml / auth.json /
.cc-switch(SQLite) / Codex++ 解析、供应商测活、配置修复（回收站备份）。
前端（page.py）与 HTTP 路由（server.py）已按 Codex 小帮手品牌重写并扩展。

除文件头与 LOG 位置外，函数逻辑与原实现保持一致——它是经过实战验证的代码。
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import unquote, urlparse

from .. import logs

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None


APP_TITLE = "Codex Helper"
SENSITIVE_WORDS = (
    "access",
    "apikey",
    "api_key",
    "auth",
    "cookie",
    "credential",
    "key",
    "password",
    "refresh",
    "secret",
    "session",
    "token",
)

APP_LABELS = {
    "claude": "Claude Code",
    "claude-desktop": "Claude Desktop",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "opencode": "OpenCode",
    "openclaw": "OpenClaw",
    "hermes": "Hermes",
}

CURRENT_PROVIDER_SETTING_KEYS = {
    "claude": "currentProviderClaude",
    "claude-desktop": "currentProviderClaudeDesktop",
    "codex": "currentProviderCodex",
    "gemini": "currentProviderGemini",
    "opencode": "currentProviderOpencode",
    "openclaw": "currentProviderOpenclaw",
    "hermes": "currentProviderHermes",
}

CATEGORY_LABELS = {
    "official": "官方",
    "cn_official": "开源官方",
    "cloud_provider": "云服务商",
    "aggregator": "聚合平台",
    "third_party": "第三方",
    "custom": "自定义",
    "omo": "Oh My OpenCode",
    "omo-slim": "Oh My OpenCode Slim",
}


# 日志统一迁移到 logs.py（持久化到 %LOCALAPPDATA%\CodexHelper\，
# 带 10MB×5 轮转、模块名、行号、异常 traceback）。
# 为向后兼容，cfgcenter 仍暴露同名函数，内部转发给 logs 模块。

def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def redact_log_value(value: Any, key_path: str = "") -> Any:
    return logs.redact(value, key_path)


def write_log(level: str, message: str, **details: Any) -> None:
    logs.write(level, message, **details)


def write_exception_log(message: str, exc: BaseException, **details: Any) -> None:
    logs.exception(message, exc, **details)


@dataclass
class FolderDiscovery:
    codex_folder: Path | None
    cc_switch_folder: Path | None
    codex_plus_folder: Path | None
    codex_candidates: list[Path]
    cc_switch_candidates: list[Path]
    codex_plus_candidates: list[Path]


def system_drive() -> Path:
    drive = os.environ.get("SystemDrive")
    if drive:
        return Path(drive + "\\")
    return Path(Path.home().anchor or "C:\\")


def candidate_folders(folder_name: str) -> list[Path]:
    home = Path.home()
    drive = system_drive()
    cwd = Path.cwd()
    candidates = [
        home / folder_name,
        drive / folder_name,
        cwd / folder_name,
    ]

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        normalized = str(candidate).casefold()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(candidate)
    return unique


def valid_folder(path_text: str | None) -> Path | None:
    if not path_text:
        return None
    path = Path(unquote(path_text)).expanduser()
    if path.exists() and path.is_dir():
        return path
    return None


def first_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def discover_folders(
    codex_override: str | None = None,
    cc_override: str | None = None,
    codex_plus_override: str | None = None,
) -> FolderDiscovery:
    codex_candidates = candidate_folders(".codex")
    cc_switch_candidates = candidate_folders(".cc-switch")
    codex_plus_candidates = candidate_folders(".codex-session-delete")
    return FolderDiscovery(
        codex_folder=valid_folder(codex_override) or first_existing(codex_candidates),
        cc_switch_folder=valid_folder(cc_override) or first_existing(cc_switch_candidates),
        codex_plus_folder=valid_folder(codex_plus_override) or first_existing(codex_plus_candidates),
        codex_candidates=codex_candidates,
        cc_switch_candidates=cc_switch_candidates,
        codex_plus_candidates=codex_plus_candidates,
    )


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "未知"
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "未知"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return "未知"


class MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def total_physical_memory() -> int | None:
    if platform.system() != "Windows":
        return None
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return int(status.ullTotalPhys)
    return None


def run_powershell(script: str) -> str:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]
    creationflags = 0
    if platform.system() == "Windows":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def windows_registry_value(path: str, name: str) -> str:
    if platform.system() != "Windows":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return ""


def get_cpu_name() -> str:
    cpu = run_powershell(
        "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)"
    )
    return cpu or platform.processor() or "未知"


def get_gpu_names() -> str:
    gpu = run_powershell(
        "(Get-CimInstance Win32_VideoController | "
        "Where-Object {$_.Name} | Select-Object -ExpandProperty Name) -join '; '"
    )
    return gpu or "未知"


def collect_system_info() -> list[dict[str, str]]:
    drive = system_drive()
    disk_total = disk_used = disk_free = None
    try:
        usage = shutil.disk_usage(str(drive))
        disk_total = usage.total
        disk_used = usage.used
        disk_free = usage.free
    except OSError:
        pass

    product_name = windows_registry_value(
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductName"
    )
    display_version = windows_registry_value(
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "DisplayVersion"
    )
    current_build = windows_registry_value(
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuildNumber"
    )

    if product_name.startswith("Windows 10"):
        try:
            if int(current_build) >= 22000:
                product_name = product_name.replace("Windows 10", "Windows 11", 1)
        except ValueError:
            pass

    os_name = product_name or platform.system()
    if display_version:
        os_name = f"{os_name} {display_version}"
    if current_build:
        os_name = f"{os_name} (Build {current_build})"

    rows = [
        ("电脑名称", "信息", platform.node() or os.environ.get("COMPUTERNAME", "未知")),
        ("系统名称", "信息", os_name),
        ("系统版本", "信息", platform.platform()),
        ("系统架构", "信息", platform.machine() or "未知"),
        ("CPU", "硬件", get_cpu_name()),
        ("CPU 核心数", "硬件", str(os.cpu_count() or "未知")),
        ("GPU", "硬件", get_gpu_names()),
        ("运行内存", "硬件", format_bytes(total_physical_memory())),
        ("系统盘", "存储", str(drive)),
        ("系统盘总容量", "存储", format_bytes(disk_total)),
        ("系统盘已用容量", "存储", format_bytes(disk_used)),
        ("系统盘可用容量", "存储", format_bytes(disk_free)),
        ("当前用户目录", "路径", str(Path.home())),
    ]
    return [{"name": name, "type": item_type, "value": value} for name, item_type, value in rows]


def collect_user_environment(show_sensitive: bool) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    text = value_to_text(value)
                    rows.append(
                        {
                            "name": str(name),
                            "type": "用户变量",
                            "value": mask_value(str(name), text, show_sensitive),
                        }
                    )
                    index += 1
        except OSError as exc:
            rows.append(make_row("读取用户变量失败", "注册表", str(exc)))

    if not rows:
        for name, value in os.environ.items():
            rows.append(
                {
                    "name": str(name),
                    "type": "当前进程变量",
                    "value": mask_value(str(name), str(value), show_sensitive),
                }
            )

    return sorted(rows, key=lambda row: row["name"].casefold())


def parse_toml(path: Path) -> Any:
    if tomllib is None:
        raise RuntimeError("当前 Python 版本不支持 TOML 解析，请使用 Python 3.11 或更新版本。")
    with path.open("rb") as file:
        return tomllib.load(file)


def parse_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def value_to_text(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, indent=2)


def flatten_data(value: Any, prefix: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, (dict, list)):
                rows.extend(flatten_data(item, path))
            else:
                rows.append({"name": path, "type": type(item).__name__, "value": value_to_text(item)})
    elif isinstance(value, list):
        if not value:
            rows.append({"name": prefix or "列表", "type": "list", "value": "[]"})
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            if isinstance(item, (dict, list)):
                rows.extend(flatten_data(item, path))
            else:
                rows.append({"name": path, "type": type(item).__name__, "value": value_to_text(item)})
    else:
        rows.append({"name": prefix or "值", "type": type(value).__name__, "value": value_to_text(value)})
    return rows


def is_sensitive_key(path: str) -> bool:
    lowered = path.casefold()
    return any(word in lowered for word in SENSITIVE_WORDS)


def mask_text(value: str) -> str:
    if not value:
        return ""
    return "********（已隐藏，开启显示敏感值后可查看）"


def mask_value(path: str, value: str, show_sensitive: bool) -> str:
    if show_sensitive or not is_sensitive_key(path):
        return value
    return mask_text(value)


def sanitize_external_text(value: str) -> str:
    text = value or ""
    text = re.sub(
        r"(?i)\b(api[_\s-]?key|token|authorization|bearer)(\s*[:=]\s*)([^\s,;\"'}]+)",
        r"\1\2***",
        text,
    )
    text = re.sub(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})", "sk-***", text)
    return text


def mask_rows(rows: list[dict[str, str]], show_sensitive: bool) -> list[dict[str, str]]:
    if show_sensitive:
        return rows
    masked: list[dict[str, str]] = []
    for row in rows:
        copied = dict(row)
        if is_sensitive_key(copied.get("name", "")):
            copied["value"] = mask_text(copied.get("value", ""))
        masked.append(copied)
    return masked


def redact_data(value: Any, prefix: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result[key] = mask_text(value_to_text(item)) if is_sensitive_key(path) else redact_data(item, path)
        return result
    if isinstance(value, list):
        return [redact_data(item, f"{prefix}[{index}]") for index, item in enumerate(value)]
    return value


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def read_config(codex_folder: Path | None) -> dict[str, Any]:
    path = codex_folder / "config.toml" if codex_folder else None
    if path is None or not path.exists():
        return {"path": str(path) if path else "", "found": False, "rows": [], "raw": "", "error": "未找到 config.toml"}
    try:
        data = parse_toml(path)
        rows = flatten_data(data)
        return {
            "path": str(path),
            "found": True,
            "rows": rows,
            "raw": safe_read_text(path),
            "error": "" if rows else "文件为空",
        }
    except Exception as exc:  # noqa: BLE001 - errors are shown in the GUI
        return {"path": str(path), "found": True, "rows": [], "raw": safe_read_text(path), "error": str(exc)}


def read_auth(codex_folder: Path | None, show_sensitive: bool) -> dict[str, Any]:
    path = codex_folder / "auth.json" if codex_folder else None
    if path is None or not path.exists():
        return {"path": str(path) if path else "", "found": False, "rows": [], "raw": "", "error": "未找到 auth.json"}
    try:
        data = parse_json(path)
        rows = flatten_data(data)
        visible_data = data if show_sensitive else redact_data(data)
        return {
            "path": str(path),
            "found": True,
            "rows": mask_rows(rows, show_sensitive),
            "raw": json.dumps(visible_data, ensure_ascii=False, indent=2),
            "error": "" if rows else "文件为空",
        }
    except Exception as exc:  # noqa: BLE001 - errors are shown in the GUI
        raw = safe_read_text(path) if show_sensitive else "auth.json 含有敏感信息。开启“显示敏感值”后可查看原始内容。"
        return {"path": str(path), "found": True, "rows": [], "raw": raw, "error": str(exc)}


def directory_summary(folder: Path | None) -> list[dict[str, str]]:
    if folder is None:
        return [{"name": "未找到", "type": "文件夹", "value": "请确认 .cc-switch 文件夹位置，或输入自定义路径。"}]
    if not folder.exists():
        return [{"name": str(folder), "type": "文件夹", "value": "路径不存在"}]

    rows: list[dict[str, str]] = []
    try:
        children = sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    except OSError as exc:
        return [{"name": str(folder), "type": "读取失败", "value": str(exc)}]

    if not children:
        return [{"name": str(folder), "type": "文件夹", "value": "文件夹为空"}]

    for child in children:
        try:
            stat = child.stat()
            size = "" if child.is_dir() else format_bytes(stat.st_size)
        except OSError:
            size = "未知"
        item_type = "文件夹" if child.is_dir() else "文件"
        rows.append({"name": child.name, "type": item_type, "value": size})
    return rows


def make_row(name: str, item_type: str, value: Any) -> dict[str, str]:
    return {"name": name, "type": item_type, "value": value_to_text(value)}


def bool_text(value: Any) -> str:
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "1", "yes", "on"}:
            return "开启"
        if lowered in {"false", "0", "no", "off", ""}:
            return "关闭"
    return "开启" if bool(value) else "关闭"


def short_text(value: Any, max_length: int = 260) -> str:
    text = value_to_text(value)
    text = " ".join(text.splitlines()) if "\n" in text else text
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def read_json_or_empty(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, "文件不存在"
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data, ""
        return {}, "JSON 顶层不是对象"
    except Exception as exc:  # noqa: BLE001 - shown in UI
        return {}, str(exc)


def sqlite_connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    return conn


def sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not sqlite_table_exists(conn, table):
        return set()
    return {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def sqlite_count(conn: sqlite3.Connection, table: str) -> int:
    if not sqlite_table_exists(conn, table):
        return 0
    row = conn.execute(f'SELECT COUNT(*) AS count FROM "{table}"').fetchone()
    return int(row["count"] if row else 0)


def parse_json_object(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_toml_text(text: str | None) -> dict[str, Any]:
    if not text or tomllib is None:
        return {}
    try:
        data = tomllib.loads(text)
    except Exception:  # noqa: BLE001 - malformed provider config should not break the page
        return {}
    return data if isinstance(data, dict) else {}


def nested_value(data: Any, *keys: str) -> Any:
    item = data
    for key in keys:
        if not isinstance(item, dict):
            return None
        item = item.get(key)
    return item


def first_text_value(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list, tuple)):
            text = str(value).strip()
            if text:
                return text
    return ""


def secret_state(value: str, show_sensitive: bool) -> str:
    if not value:
        return "未配置"
    return value if show_sensitive else "已配置"


def format_millis(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    seconds = number / 1000 if number > 10_000_000_000 else number
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(seconds))


def enabled_app_names(flags: dict[str, Any]) -> str:
    apps = [APP_LABELS.get(app, app) for app, enabled in flags.items() if bool(enabled)]
    return "、".join(apps) if apps else "未启用"


def label_app(app_type: str) -> str:
    return APP_LABELS.get(app_type, app_type)


def label_category(category: Any) -> str:
    if not category:
        return "未分类"
    return CATEGORY_LABELS.get(str(category), str(category))


def meta_value(meta: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in meta:
            return meta.get(key)
    return None


def extract_provider_settings(
    app_type: str,
    settings_config: dict[str, Any],
    meta: dict[str, Any],
    show_sensitive: bool,
) -> dict[str, str]:
    api_format = first_text_value(meta_value(meta, "apiFormat", "api_format"))
    provider_type = first_text_value(meta_value(meta, "providerType", "provider_type"))

    base_url = ""
    model = ""
    auth_value = ""
    extra: list[str] = []

    if app_type in {"claude", "claude-desktop"}:
        env = settings_config.get("env") if isinstance(settings_config.get("env"), dict) else {}
        base_url = first_text_value(env.get("ANTHROPIC_BASE_URL"))
        auth_value = first_text_value(
            env.get("ANTHROPIC_AUTH_TOKEN"),
            env.get("ANTHROPIC_API_KEY"),
            env.get("OPENROUTER_API_KEY"),
            env.get("GOOGLE_API_KEY"),
        )
        model = first_text_value(
            env.get("ANTHROPIC_MODEL"),
            env.get("ANTHROPIC_DEFAULT_SONNET_MODEL"),
            env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"),
            env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"),
        )
        if env.get("ANTHROPIC_DEFAULT_SONNET_MODEL"):
            extra.append(f"Sonnet: {env.get('ANTHROPIC_DEFAULT_SONNET_MODEL')}")
        if env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"):
            extra.append(f"Opus: {env.get('ANTHROPIC_DEFAULT_OPUS_MODEL')}")
    elif app_type == "codex":
        auth = settings_config.get("auth") if isinstance(settings_config.get("auth"), dict) else {}
        config_text = settings_config.get("config") if isinstance(settings_config.get("config"), str) else ""
        toml_data = parse_toml_text(config_text)
        model_provider = first_text_value(toml_data.get("model_provider"))
        provider_block = {}
        providers_block = toml_data.get("model_providers")
        if model_provider and isinstance(providers_block, dict):
            provider_block = providers_block.get(model_provider) or {}
        if not isinstance(provider_block, dict):
            provider_block = {}
        base_url = first_text_value(provider_block.get("base_url"), toml_data.get("base_url"))
        model = first_text_value(toml_data.get("model"), provider_block.get("model"))
        auth_value = first_text_value(auth.get("OPENAI_API_KEY"), toml_data.get("openai_api_key"))
        api_format = api_format or first_text_value(provider_block.get("wire_api"))
        if model_provider:
            extra.append(f"model_provider: {model_provider}")
        if toml_data.get("model_reasoning_effort"):
            extra.append(f"reasoning: {toml_data.get('model_reasoning_effort')}")
    elif app_type == "gemini":
        env = settings_config.get("env") if isinstance(settings_config.get("env"), dict) else {}
        base_url = first_text_value(env.get("GOOGLE_GEMINI_BASE_URL"))
        model = first_text_value(env.get("GEMINI_MODEL"))
        auth_value = first_text_value(env.get("GEMINI_API_KEY"), env.get("GOOGLE_API_KEY"))
    elif app_type == "opencode":
        options = settings_config.get("options") if isinstance(settings_config.get("options"), dict) else {}
        base_url = first_text_value(options.get("baseURL"), options.get("baseUrl"))
        auth_value = first_text_value(options.get("apiKey"), options.get("api_key"))
        models = settings_config.get("models")
        if isinstance(models, dict):
            model = "、".join(list(models.keys())[:3])
            if len(models) > 3:
                model += f" 等 {len(models)} 个"
        extra.append(first_text_value(settings_config.get("npm")))
    elif app_type == "openclaw":
        base_url = first_text_value(settings_config.get("baseUrl"), settings_config.get("base_url"))
        auth_value = first_text_value(settings_config.get("apiKey"), settings_config.get("api_key"))
        models = settings_config.get("models")
        if isinstance(models, list):
            names = [first_text_value(item.get("name"), item.get("id")) for item in models if isinstance(item, dict)]
            model = "、".join([name for name in names if name][:3])
            if len(names) > 3:
                model += f" 等 {len(names)} 个"
        extra.append(first_text_value(settings_config.get("api")))
    elif app_type == "hermes":
        base_url = first_text_value(settings_config.get("base_url"), settings_config.get("baseUrl"))
        auth_value = first_text_value(settings_config.get("api_key"), settings_config.get("apiKey"))
        model = first_text_value(settings_config.get("model"), settings_config.get("default"))

    auth_binding = meta_value(meta, "authBinding", "auth_binding")
    if isinstance(auth_binding, dict):
        source = first_text_value(auth_binding.get("source"))
        auth_provider = first_text_value(auth_binding.get("authProvider"), auth_binding.get("auth_provider"))
        if source:
            extra.append(f"认证来源: {source}")
        if auth_provider:
            extra.append(f"托管认证: {auth_provider}")

    if meta_value(meta, "costMultiplier", "cost_multiplier"):
        extra.append(f"成本倍率: {meta_value(meta, 'costMultiplier', 'cost_multiplier')}")
    if meta_value(meta, "pricingModelSource", "pricing_model_source"):
        extra.append(f"计费来源: {meta_value(meta, 'pricingModelSource', 'pricing_model_source')}")
    if meta_value(meta, "commonConfigEnabled", "common_config_enabled") is not None:
        extra.append(f"通用配置: {bool_text(meta_value(meta, 'commonConfigEnabled', 'common_config_enabled'))}")
    if meta_value(meta, "endpointAutoSelect", "endpoint_auto_select") is not None:
        extra.append(f"端点自动选择: {bool_text(meta_value(meta, 'endpointAutoSelect', 'endpoint_auto_select'))}")
    if meta_value(meta, "usage_script", "usageScript"):
        script = meta_value(meta, "usage_script", "usageScript")
        if isinstance(script, dict):
            extra.append(f"用量查询: {bool_text(script.get('enabled'))}")
    if provider_type:
        extra.append(f"类型: {provider_type}")

    return {
        "base_url": base_url or "未配置",
        "model": model or "未配置",
        "api_key": secret_state(auth_value, show_sensitive),
        "api_format": api_format or "未指定",
        "extra": "；".join([item for item in extra if item]) or "无",
    }


def read_cc_switch_settings(folder: Path | None, show_sensitive: bool) -> dict[str, Any]:
    path = folder / "settings.json" if folder else None
    if path is None:
        return {"path": "", "found": False, "data": {}, "rows": [], "error": "未找到 .cc-switch 文件夹"}
    data, error = read_json_or_empty(path)
    rows: list[dict[str, str]] = []
    if data:
        simple_fields = [
            ("language", "界面语言"),
            ("showInTray", "显示托盘图标"),
            ("minimizeToTrayOnClose", "关闭时最小化到托盘"),
            ("useAppWindowControls", "应用窗口控制按钮"),
            ("enableClaudePluginIntegration", "Claude 插件联动"),
            ("skipClaudeOnboarding", "跳过 Claude 初次确认"),
            ("launchOnStartup", "开机自启"),
            ("silentStartup", "静默启动"),
            ("enableLocalProxy", "主页面本地代理功能"),
            ("enableFailoverToggle", "独立显示故障转移开关"),
            ("preserveCodexOfficialAuthOnSwitch", "切换时保留 Codex 官方登录"),
            ("unifyCodexSessionHistory", "统一 Codex 会话历史"),
            ("skillSyncMethod", "Skill 同步方式"),
            ("skillStorageLocation", "Skill 存储位置"),
            ("backupIntervalHours", "自动备份间隔小时"),
            ("backupRetainCount", "备份保留数量"),
            ("preferredTerminal", "首选终端"),
        ]
        for key, label in simple_fields:
            if key in data:
                value = bool_text(data[key]) if isinstance(data[key], bool) else value_to_text(data[key])
                rows.append(make_row(label, "设备设置", value))

        visible_apps = data.get("visibleApps")
        if isinstance(visible_apps, dict):
            rows.append(make_row("主页面可见应用", "设备设置", enabled_app_names(visible_apps)))

        for app_type, label in APP_LABELS.items():
            override_key = {
                "claude": "claudeConfigDir",
                "codex": "codexConfigDir",
                "gemini": "geminiConfigDir",
                "opencode": "opencodeConfigDir",
                "openclaw": "openclawConfigDir",
                "hermes": "hermesConfigDir",
            }.get(app_type)
            if override_key and data.get(override_key):
                rows.append(make_row(f"{label} 配置目录覆盖", "路径", data[override_key]))

        for app_type, key in CURRENT_PROVIDER_SETTING_KEYS.items():
            if data.get(key):
                rows.append(make_row(f"{label_app(app_type)} 当前供应商 ID", "本机优先", data[key]))

        for sync_key, label in (("webdavSync", "WebDAV 同步"), ("s3Sync", "S3 同步")):
            sync = data.get(sync_key)
            if isinstance(sync, dict):
                rows.append(make_row(f"{label}启用", "同步", bool_text(sync.get("enabled"))))
                rows.append(make_row(f"{label}自动同步", "同步", bool_text(sync.get("autoSync"))))
                for key, field_label in (
                    ("baseUrl", "地址"),
                    ("remoteRoot", "远端根目录"),
                    ("profile", "配置档"),
                    ("region", "区域"),
                    ("bucket", "桶"),
                    ("endpoint", "端点"),
                    ("username", "用户名"),
                    ("accessKeyId", "Access Key ID"),
                ):
                    if sync.get(key):
                        value = mask_value(f"{sync_key}.{key}", value_to_text(sync[key]), show_sensitive)
                        rows.append(make_row(f"{label}{field_label}", "同步", value))
    elif path.exists() and error:
        rows.append(make_row("settings.json", "读取失败", error))
    else:
        rows.append(make_row("settings.json", "状态", "未找到"))

    return {
        "path": str(path),
        "found": path.exists(),
        "data": data,
        "rows": rows,
        "error": "" if data or not path.exists() else error,
    }


def read_cc_switch_database(
    folder: Path | None,
    settings_data: dict[str, Any],
    show_sensitive: bool,
) -> dict[str, Any]:
    empty = {
        "found": False,
        "path": str(folder / "cc-switch.db") if folder else "",
        "overview": [],
        "settingsTable": [],
        "currentProviders": [],
        "providers": [],
        "providerCards": [],
        "proxy": [],
        "mcp": [],
        "skills": [],
        "skillRepos": [],
        "errors": [],
    }
    if folder is None:
        empty["errors"].append("未找到 .cc-switch 文件夹")
        return empty
    db_path = folder / "cc-switch.db"
    if not db_path.exists():
        empty["errors"].append("未找到 cc-switch.db")
        return empty

    errors: list[str] = []
    overview: list[dict[str, str]] = []
    settings_rows: list[dict[str, str]] = []
    current_rows: list[dict[str, str]] = []
    provider_rows: list[dict[str, str]] = []
    provider_cards: list[dict[str, Any]] = []
    proxy_rows: list[dict[str, str]] = []
    mcp_rows: list[dict[str, str]] = []
    skill_rows: list[dict[str, str]] = []
    skill_repo_rows: list[dict[str, str]] = []

    try:
        stat = db_path.stat()
        with sqlite_connect_readonly(db_path) as conn:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            provider_count = sqlite_count(conn, "providers")
            mcp_count = sqlite_count(conn, "mcp_servers")
            skill_count = sqlite_count(conn, "skills")
            repo_count = sqlite_count(conn, "skill_repos")
            request_log_count = sqlite_count(conn, "proxy_request_logs")
            backup_count = len(list((folder / "backups").glob("*"))) if (folder / "backups").exists() else 0

            overview.extend(
                [
                    make_row("数据库版本", "SQLite user_version", user_version),
                    make_row("数据库大小", "文件", format_bytes(stat.st_size)),
                    make_row("数据库修改时间", "文件", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))),
                    make_row("供应商数量", "providers", provider_count),
                    make_row("MCP 数量", "mcp_servers", mcp_count),
                    make_row("Skills 数量", "skills", skill_count),
                    make_row("Skill 仓库数量", "skill_repos", repo_count),
                    make_row("请求日志数量", "proxy_request_logs", request_log_count),
                    make_row("备份文件数量", "backups", backup_count),
                    make_row("表数量", "SQLite", len(tables)),
                ]
            )

            providers_by_app: dict[str, list[dict[str, Any]]] = {}
            if sqlite_table_exists(conn, "providers"):
                query = (
                    "SELECT id, app_type, name, settings_config, website_url, category, created_at, "
                    "sort_index, notes, icon, icon_color, meta, is_current, in_failover_queue "
                    "FROM providers ORDER BY app_type, COALESCE(sort_index, 999999), created_at ASC, id ASC"
                )
                for row in conn.execute(query):
                    item = dict(row)
                    item["settings_config_data"] = parse_json_object(item.get("settings_config"))
                    item["meta_data"] = parse_json_object(item.get("meta"))
                    providers_by_app.setdefault(item["app_type"], []).append(item)

                endpoint_counts: dict[tuple[str, str], int] = {}
                if sqlite_table_exists(conn, "provider_endpoints"):
                    for row in conn.execute(
                        "SELECT provider_id, app_type, COUNT(*) AS count FROM provider_endpoints GROUP BY provider_id, app_type"
                    ):
                        endpoint_counts[(row["app_type"], row["provider_id"])] = int(row["count"])

                health: dict[tuple[str, str], dict[str, Any]] = {}
                if sqlite_table_exists(conn, "provider_health"):
                    for row in conn.execute(
                        "SELECT provider_id, app_type, is_healthy, consecutive_failures, last_success_at, last_failure_at, last_error FROM provider_health"
                    ):
                        health[(row["app_type"], row["provider_id"])] = dict(row)

                for app_type, providers in providers_by_app.items():
                    ids = {provider["id"] for provider in providers}
                    setting_key = CURRENT_PROVIDER_SETTING_KEYS.get(app_type, "")
                    setting_current = first_text_value(settings_data.get(setting_key))
                    db_current = first_text_value(
                        next((provider["id"] for provider in providers if provider.get("is_current")), "")
                    )
                    if setting_current and setting_current in ids:
                        current_id = setting_current
                        source = "settings.json"
                    elif db_current:
                        current_id = db_current
                        source = "数据库 is_current"
                    elif setting_current:
                        current_id = setting_current
                        source = "settings.json（数据库中未找到）"
                    else:
                        current_id = ""
                        source = "未设置"

                    current_provider = next((provider for provider in providers if provider["id"] == current_id), None)
                    current_name = current_provider["name"] if current_provider else (current_id or "未设置")
                    current_rows.append(
                        make_row(
                            label_app(app_type),
                            f"{len(providers)} 个供应商",
                            f"{current_name}；来源：{source}；ID：{current_id or '无'}",
                        )
                    )

                    for provider in providers:
                        details = extract_provider_settings(
                            app_type,
                            provider["settings_config_data"],
                            provider["meta_data"],
                            show_sensitive,
                        )
                        is_current = provider["id"] == current_id
                        health_item = health.get((app_type, provider["id"]))
                        if health_item:
                            health_text = "健康" if health_item.get("is_healthy") else "异常"
                            if health_item.get("consecutive_failures"):
                                health_text += f"，连续失败 {health_item['consecutive_failures']}"
                            if health_item.get("last_error"):
                                health_text += f"，最近错误：{short_text(health_item['last_error'], 80)}"
                        else:
                            health_text = "默认健康（无记录）"
                        endpoint_count = endpoint_counts.get((app_type, provider["id"]), 0)
                        created_at = format_millis(provider.get("created_at"))
                        website_url = first_text_value(provider.get("website_url")) or "未配置"
                        category_label = label_category(provider.get("category"))
                        test_base_url = cc_switch_base_url(
                            app_type,
                            provider["settings_config_data"],
                            provider["meta_data"],
                        )
                        test_unavailable_reason = ""
                        if not test_base_url:
                            test_unavailable_reason = "未配置 Base URL"
                        elif not valid_http_url(test_base_url):
                            test_unavailable_reason = "Base URL 不是 http/https 地址"
                        icon = first_text_value(provider.get("icon"))
                        if provider.get("icon_color"):
                            icon = f"{icon or '未设置'}（{provider.get('icon_color')}）"
                        detail_lines = [
                            f"供应商 ID：{provider['id']}",
                            f"分类：{category_label}",
                            f"Base URL：{details['base_url']}",
                            f"API Key/Token：{details['api_key']}",
                            f"官网链接：{website_url}",
                            f"模型：{details['model']}",
                            f"API 格式：{details['api_format']}",
                            f"自定义端点数量：{endpoint_count}",
                            f"健康状态：{health_text}",
                            f"排序：{provider.get('sort_index') if provider.get('sort_index') is not None else '未设置'}",
                            f"图标：{icon or '未设置'}",
                            f"其他：{details['extra']}",
                        ]
                        if created_at:
                            detail_lines.append(f"添加时间：{created_at}")
                        if provider.get("notes"):
                            detail_lines.append(f"备注：{short_text(provider['notes'], 120)}")
                        if provider.get("in_failover_queue"):
                            detail_lines.append("故障转移：已加入队列")
                        provider_rows.append(
                            make_row(
                                f"{label_app(app_type)} / {provider['name']}",
                                "当前" if is_current else "备用",
                                "\n".join(detail_lines),
                            )
                        )
                        provider_cards.append(
                            {
                                "source": "ccSwitch",
                                "id": str(provider["id"]),
                                "appType": app_type,
                                "appLabel": label_app(app_type),
                                "name": str(provider.get("name") or provider["id"]),
                                "status": "当前" if is_current else "备用",
                                "isCurrent": is_current,
                                "category": category_label,
                                "baseUrl": details["base_url"],
                                "apiKey": details["api_key"],
                                "websiteUrl": "" if website_url == "未配置" else website_url,
                                "model": details["model"],
                                "apiFormat": details["api_format"],
                                "endpointCount": endpoint_count,
                                "health": health_text,
                                "healthState": (
                                    "healthy"
                                    if health_item and health_item.get("is_healthy")
                                    else "error"
                                    if health_item and not health_item.get("is_healthy")
                                    else "neutral"
                                ),
                                "sortIndex": (
                                    str(provider.get("sort_index"))
                                    if provider.get("sort_index") is not None
                                    else "未设置"
                                ),
                                "icon": icon or "未设置",
                                "iconColor": first_text_value(provider.get("icon_color")),
                                "extra": details["extra"],
                                "createdAt": created_at,
                                "notes": short_text(provider["notes"], 120) if provider.get("notes") else "",
                                "inFailoverQueue": bool(provider.get("in_failover_queue")),
                                "testable": not test_unavailable_reason,
                                "testUnavailableReason": test_unavailable_reason,
                            }
                        )

            if sqlite_table_exists(conn, "proxy_config"):
                proxy_cols = sqlite_columns(conn, "proxy_config")
                select_cols = [col for col in (
                    "app_type",
                    "proxy_enabled",
                    "listen_address",
                    "listen_port",
                    "enable_logging",
                    "enabled",
                    "auto_failover_enabled",
                    "max_retries",
                    "streaming_first_byte_timeout",
                    "streaming_idle_timeout",
                    "non_streaming_timeout",
                    "circuit_failure_threshold",
                    "circuit_success_threshold",
                    "circuit_timeout_seconds",
                    "circuit_error_rate_threshold",
                    "circuit_min_requests",
                    "default_cost_multiplier",
                    "pricing_model_source",
                ) if col in proxy_cols]
                for row in conn.execute(f"SELECT {', '.join(select_cols)} FROM proxy_config ORDER BY app_type"):
                    item = dict(row)
                    parts = [
                        f"入口服务：{bool_text(item.get('proxy_enabled'))}",
                        f"监听：{item.get('listen_address', '127.0.0.1')}:{item.get('listen_port', 15721)}",
                        f"请求日志：{bool_text(item.get('enable_logging', 1))}",
                        f"接管：{bool_text(item.get('enabled'))}",
                        f"自动故障转移：{bool_text(item.get('auto_failover_enabled'))}",
                    ]
                    if item.get("max_retries") is not None:
                        parts.append(f"重试：{item.get('max_retries')}")
                    if item.get("streaming_first_byte_timeout") is not None:
                        parts.append(f"首字节超时：{item.get('streaming_first_byte_timeout')}s")
                    if item.get("streaming_idle_timeout") is not None:
                        parts.append(f"流式空闲超时：{item.get('streaming_idle_timeout')}s")
                    if item.get("non_streaming_timeout") is not None:
                        parts.append(f"非流式超时：{item.get('non_streaming_timeout')}s")
                    if item.get("circuit_failure_threshold") is not None:
                        parts.append(f"熔断失败阈值：{item.get('circuit_failure_threshold')}")
                    if item.get("default_cost_multiplier") is not None:
                        parts.append(f"默认成本倍率：{item.get('default_cost_multiplier')}")
                    if item.get("pricing_model_source") is not None:
                        parts.append(f"计费模型来源：{item.get('pricing_model_source')}")
                    proxy_rows.append(make_row(label_app(item.get("app_type", "")), "代理配置", "；".join(parts)))

            if sqlite_table_exists(conn, "mcp_servers"):
                for row in conn.execute(
                    "SELECT id, name, server_config, description, homepage, tags, enabled_claude, enabled_codex, "
                    "enabled_gemini, enabled_opencode, enabled_hermes FROM mcp_servers ORDER BY name ASC, id ASC"
                ):
                    item = dict(row)
                    server = parse_json_object(item.get("server_config"))
                    apps = {
                        "claude": item.get("enabled_claude"),
                        "codex": item.get("enabled_codex"),
                        "gemini": item.get("enabled_gemini"),
                        "opencode": item.get("enabled_opencode"),
                        "hermes": item.get("enabled_hermes"),
                    }
                    server_type = first_text_value(server.get("type")) or ("http" if server.get("url") else "stdio")
                    command = first_text_value(server.get("command"))
                    if isinstance(server.get("command"), list):
                        command = " ".join(value_to_text(v) for v in server.get("command"))
                    detail = first_text_value(server.get("url"), command, item.get("description"), item.get("homepage"), item.get("id"))
                    mcp_rows.append(make_row(item.get("name") or item.get("id"), server_type, f"启用：{enabled_app_names(apps)}；{detail}"))

            if sqlite_table_exists(conn, "skills"):
                for row in conn.execute(
                    "SELECT id, name, description, directory, repo_owner, repo_name, repo_branch, enabled_claude, "
                    "enabled_codex, enabled_gemini, enabled_opencode, enabled_hermes, installed_at, updated_at FROM skills ORDER BY name ASC"
                ):
                    item = dict(row)
                    apps = {
                        "claude": item.get("enabled_claude"),
                        "codex": item.get("enabled_codex"),
                        "gemini": item.get("enabled_gemini"),
                        "opencode": item.get("enabled_opencode"),
                        "hermes": item.get("enabled_hermes"),
                    }
                    repo = ""
                    if item.get("repo_owner") and item.get("repo_name"):
                        repo = f"；仓库：{item['repo_owner']}/{item['repo_name']}#{item.get('repo_branch') or 'main'}"
                    times = []
                    if item.get("installed_at"):
                        times.append(f"安装：{format_millis(item.get('installed_at'))}")
                    if item.get("updated_at"):
                        times.append(f"更新：{format_millis(item.get('updated_at'))}")
                    skill_rows.append(
                        make_row(
                            item.get("name") or item.get("id"),
                            "Skill",
                            f"启用：{enabled_app_names(apps)}；目录：{item.get('directory') or '未知'}{repo}"
                            + (f"；{'；'.join(times)}" if times else ""),
                        )
                    )

            if sqlite_table_exists(conn, "skill_repos"):
                for row in conn.execute("SELECT owner, name, branch, enabled FROM skill_repos ORDER BY owner ASC, name ASC"):
                    skill_repo_rows.append(
                        make_row(f"{row['owner']}/{row['name']}", "Skill 仓库", f"分支：{row['branch']}；状态：{bool_text(row['enabled'])}")
                    )

            if sqlite_table_exists(conn, "settings"):
                for row in conn.execute("SELECT key, value FROM settings ORDER BY key ASC"):
                    key = row["key"]
                    value = mask_value(key, short_text(row["value"], 360), show_sensitive)
                    settings_rows.append(make_row(key, "数据库设置", value))
    except Exception as exc:  # noqa: BLE001 - shown in UI
        errors.append(str(exc))

    return {
        "found": True,
        "path": str(db_path),
        "overview": overview,
        "settingsTable": settings_rows,
        "currentProviders": current_rows,
        "providers": provider_rows,
        "providerCards": provider_cards,
        "proxy": proxy_rows,
        "mcp": mcp_rows,
        "skills": skill_rows,
        "skillRepos": skill_repo_rows,
        "errors": errors,
    }


def read_cc_switch(folder: Path | None, show_sensitive: bool) -> dict[str, Any]:
    settings = read_cc_switch_settings(folder, show_sensitive)
    database = read_cc_switch_database(folder, settings.get("data", {}), show_sensitive)
    rows = directory_summary(folder)
    return {
        "path": str(folder) if folder else "",
        "found": bool(folder and folder.exists()),
        "rows": rows,
        "settings": settings,
        "database": database,
    }


def api_key_from_json_text(text: str | None) -> str:
    data = parse_json_object(text)
    return first_text_value(data.get("OPENAI_API_KEY"), data.get("apiKey"), data.get("api_key"))


def codex_provider_block(config_text: str, provider_id: str) -> dict[str, Any]:
    data = parse_toml_text(config_text)
    providers = data.get("model_providers")
    if not isinstance(providers, dict):
        return {}
    provider = providers.get(provider_id)
    return provider if isinstance(provider, dict) else {}


def normalized_url(value: str) -> str:
    text = value.strip().rstrip("/").casefold()
    if text.endswith("/v1"):
        text = text[:-3].rstrip("/")
    return text


def codex_plus_profile_base_urls(settings_data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    if first_text_value(settings_data.get("relayBaseUrl")):
        urls.append(first_text_value(settings_data.get("relayBaseUrl")))
    profiles = settings_data.get("relayProfiles")
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            urls.append(first_text_value(profile.get("upstreamBaseUrl"), profile.get("baseUrl")))
            config_text = first_text_value(profile.get("configContents"))
            config_data = parse_toml_text(config_text)
            provider_id = first_text_value(config_data.get("model_provider"))
            provider = codex_provider_block(config_text, provider_id)
            urls.append(first_text_value(provider.get("base_url")))
    return [url for url in urls if url]


def codex_plus_config_status(
    codex_folder: Path | None,
    show_sensitive: bool,
    settings_data: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    if codex_folder is None:
        return [make_row("Codex 配置", "未找到", "未找到 .codex 文件夹")]
    settings_data = settings_data or {}
    config_path = codex_folder / "config.toml"
    auth_path = codex_folder / "auth.json"
    config_text = safe_read_text(config_path) if config_path.exists() else ""
    auth_text = safe_read_text(auth_path) if auth_path.exists() else ""
    config_data = parse_toml_text(config_text)
    provider_id = first_text_value(config_data.get("model_provider"))
    provider = codex_provider_block(config_text, provider_id)
    provider_name = first_text_value(provider.get("name"))
    base_url = first_text_value(provider.get("base_url"))
    requires_auth = provider.get("requires_openai_auth")
    bearer_token = first_text_value(provider.get("experimental_bearer_token"))
    auth_api_key = api_key_from_json_text(auth_text)
    has_api_key = bool(bearer_token or auth_api_key)
    model_catalog = first_text_value(config_data.get("model_catalog_json"))
    profile_urls = {normalized_url(url) for url in codex_plus_profile_base_urls(settings_data)}
    matches_codex_plus_profile = bool(base_url and normalized_url(base_url) in profile_urls)
    looks_like_codex_plus = (
        provider_id in {"CodexPlusPlus", "CodexPP"}
        or provider_name in {"CodexPlusPlus", "CodexPP"}
        or (provider_id == "custom" and matches_codex_plus_profile)
    )
    configured = bool(provider_id and base_url and has_api_key)
    rows = [
        make_row("config.toml", "路径", str(config_path)),
        make_row("auth.json", "路径", str(auth_path)),
        make_row("当前 model_provider", "Codex", provider_id or "未设置"),
        make_row("Provider 名称", "Codex", provider_name or "未设置"),
        make_row("Base URL", "Codex", base_url or "未配置"),
        make_row("requires_openai_auth", "Codex", bool_text(requires_auth) if requires_auth is not None else "未设置"),
        make_row("API Key/Token", "Codex", secret_state(bearer_token or auth_api_key, show_sensitive)),
        make_row("model_catalog_json", "Codex", model_catalog or "未配置"),
        make_row("Codex++ Provider 规则", "源码", "当前版本默认写入 custom；旧版兼容 CodexPlusPlus/CodexPP"),
        make_row("匹配 Codex++ 中转配置", "判断", bool_text(matches_codex_plus_profile)),
        make_row("Codex++ 注入识别", "判断", bool_text(looks_like_codex_plus)),
        make_row("API 模式完整度", "判断", "已配置" if configured else "未完整配置"),
    ]
    return rows


def relay_mode_label(value: Any) -> str:
    mapping = {
        "official": "官方登录",
        "mixedApi": "混合 API",
        "pureApi": "纯 API",
        "aggregate": "聚合中转",
    }
    text = first_text_value(value)
    return mapping.get(text, text or "未设置")


def relay_protocol_label(value: Any) -> str:
    mapping = {
        "responses": "Responses",
        "chatCompletions": "Chat Completions",
    }
    text = first_text_value(value)
    return mapping.get(text, text or "未设置")


def model_list_summary(value: Any) -> str:
    text = first_text_value(value)
    if not text:
        return "未配置"
    models = [item.strip() for item in text.replace(",", "\n").splitlines() if item.strip()]
    if not models:
        return "未配置"
    preview = "、".join(models[:4])
    if len(models) > 4:
        preview += f" 等 {len(models)} 个"
    return preview


def relay_profile_api_key(profile: dict[str, Any], settings_data: dict[str, Any]) -> str:
    config_text = first_text_value(profile.get("configContents"))
    provider_id = first_text_value(parse_toml_text(config_text).get("model_provider"))
    provider = codex_provider_block(config_text, provider_id)
    return first_text_value(
        profile.get("apiKey"),
        provider.get("experimental_bearer_token"),
        api_key_from_json_text(first_text_value(profile.get("authContents"))),
        settings_data.get("relayApiKey"),
    )


def read_codex_plus(folder: Path | None, codex_folder: Path | None, show_sensitive: bool) -> dict[str, Any]:
    empty = {
        "path": str(folder) if folder else "",
        "found": False,
        "rows": [],
        "overview": [],
        "settings": [],
        "status": [],
        "codexInjection": codex_plus_config_status(codex_folder, show_sensitive),
        "relayProfiles": [],
        "relayProfileCards": [],
        "aggregateProfiles": [],
        "files": [],
        "errors": [],
    }
    if folder is None:
        empty["rows"] = [make_row("未找到", "文件夹", "请确认 Codex++ 状态目录 .codex-session-delete 是否存在，或输入自定义路径。")]
        empty["errors"].append("未找到 .codex-session-delete 文件夹")
        return empty

    settings_path = folder / "settings.json"
    status_path = folder / "latest-status.json"
    log_path = folder / "codex-plus.log"
    pending_import_path = folder / "pending-provider-import.json"
    provider_backup_dir = codex_folder / "backups_state" / "provider-sync" if codex_folder else None

    rows = directory_summary(folder)
    overview = [
        make_row("Codex++ 状态目录", "路径", str(folder)),
        make_row("settings.json", "配置文件", str(settings_path)),
        make_row("latest-status.json", "运行状态", str(status_path)),
        make_row("codex-plus.log", "诊断日志", str(log_path)),
        make_row("pending-provider-import.json", "待导入供应商", str(pending_import_path)),
        make_row("Provider 同步备份", "路径", str(provider_backup_dir) if provider_backup_dir else "未找到 .codex"),
    ]
    if log_path.exists():
        stat = log_path.stat()
        overview.append(make_row("日志大小", "文件", format_bytes(stat.st_size)))
        overview.append(make_row("日志更新时间", "文件", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))))
    if provider_backup_dir is not None:
        backup_count = len(list(provider_backup_dir.glob("*"))) if provider_backup_dir.exists() else 0
        overview.append(make_row("Provider 备份数量", "provider-sync", backup_count))

    settings_data, settings_error = read_json_or_empty(settings_path)
    status_data, status_error = read_json_or_empty(status_path)
    errors: list[str] = []
    if settings_error and settings_path.exists():
        errors.append(f"settings.json：{settings_error}")
    if status_error and status_path.exists():
        errors.append(f"latest-status.json：{status_error}")

    settings_rows: list[dict[str, str]] = []
    if settings_data:
        setting_labels = [
            ("launchMode", "启动模式"),
            ("enhancementsEnabled", "增强注入"),
            ("relayProfilesEnabled", "供应商配置总开关"),
            ("providerSyncEnabled", "Provider 同步"),
            ("providerSyncLastSelectedProvider", "上次选择供应商"),
            ("codexAppPath", "Codex App 路径"),
            ("codexExtraArgs", "Codex 启动参数"),
            ("codexAppPluginMarketplaceUnlock", "插件市场解锁"),
            ("codexAppPluginAutoExpand", "插件自动展开"),
            ("codexAppModelWhitelistUnlock", "模型白名单解锁"),
            ("codexAppSessionDelete", "会话删除增强"),
            ("codexAppMarkdownExport", "Markdown 导出"),
            ("codexAppPasteFix", "粘贴修复"),
            ("codexAppForceChineseLocale", "强制中文界面"),
            ("codexAppFastStartup", "快速启动"),
            ("codexAppProjectMove", "项目移动"),
            ("codexAppThreadIdBadge", "线程 ID 标记"),
            ("codexAppConversationView", "会话视图"),
            ("codexAppThreadScrollRestore", "线程滚动恢复"),
            ("codexAppZedRemoteOpen", "Zed 远程打开"),
            ("codexAppUpstreamWorktreeCreate", "上游 worktree 创建"),
            ("codexAppNativeMenuPlacement", "原生菜单位置"),
            ("codexAppNativeMenuLocalization", "原生菜单本地化"),
            ("codexAppServiceTierControls", "服务档位控制"),
            ("codexGoalsEnabled", "Codex Goals"),
            ("activeRelayId", "当前中转 ID"),
            ("activeAggregateRelayId", "当前聚合中转 ID"),
            ("relayTestModel", "中转测试模型"),
            ("relayBaseUrl", "旧版中转 Base URL"),
            ("relayApiKey", "旧版中转 API Key"),
            ("codexAppStepwiseEnabled", "Stepwise 增强"),
            ("codexAppStepwiseBaseUrl", "Stepwise Base URL"),
            ("codexAppStepwiseApiKey", "Stepwise API Key"),
            ("codexAppStepwiseModel", "Stepwise 模型"),
            ("cliWrapperEnabled", "CLI Wrapper"),
            ("cliWrapperBaseUrl", "CLI Wrapper Base URL"),
            ("cliWrapperApiKey", "CLI Wrapper API Key"),
            ("ccsLinkEnabled", "CC Switch 链接"),
        ]
        for key, label in setting_labels:
            if key not in settings_data:
                continue
            value = settings_data.get(key)
            if isinstance(value, bool):
                text = bool_text(value)
            elif key.casefold().endswith("apikey") or key.casefold().endswith("api_key") or "key" in key.casefold():
                text = secret_state(first_text_value(value), show_sensitive)
            elif isinstance(value, list):
                text = "、".join(value_to_text(item) for item in value) if value else "未配置"
            else:
                text = value_to_text(value) if value not in (None, "") else "未配置"
            settings_rows.append(make_row(label, key, text))

    status_rows: list[dict[str, str]] = []
    if status_data:
        status_rows = [
            make_row("运行状态", "status", status_data.get("status") or "未知"),
            make_row("状态消息", "message", status_data.get("message") or "无"),
            make_row("启动时间", "started_at_ms", format_millis(status_data.get("started_at_ms")) or "未知"),
            make_row("Helper 端口", "helper_port", status_data.get("helper_port") or "未设置"),
            make_row("Debug 端口", "debug_port", status_data.get("debug_port") or "未设置"),
            make_row("Codex App", "codex_app", status_data.get("codex_app") or "未设置"),
        ]
    elif not status_path.exists():
        status_rows = [make_row("运行状态", "latest-status.json", "未找到")]

    relay_rows: list[dict[str, str]] = []
    relay_profile_cards: list[dict[str, Any]] = []
    relay_profiles = settings_data.get("relayProfiles") if isinstance(settings_data, dict) else []
    if isinstance(relay_profiles, list):
        active_relay_id = first_text_value(settings_data.get("activeRelayId")) or "default"
        for profile in relay_profiles:
            if not isinstance(profile, dict):
                continue
            profile_id = first_text_value(profile.get("id")) or "default"
            is_current = profile_id == active_relay_id
            config_text = first_text_value(profile.get("configContents"))
            config_data = parse_toml_text(config_text)
            config_provider_id = first_text_value(config_data.get("model_provider"))
            config_provider = codex_provider_block(config_text, config_provider_id)
            base_url = first_text_value(
                profile.get("upstreamBaseUrl"),
                profile.get("baseUrl"),
                config_provider.get("base_url"),
                settings_data.get("relayBaseUrl"),
            ) or "未配置"
            api_key = relay_profile_api_key(profile, settings_data)
            model = first_text_value(
                profile.get("model"),
                config_data.get("model"),
                profile.get("testModel"),
            ) or model_list_summary(profile.get("modelList"))
            test_base_url = codex_plus_profile_base_url(profile)
            test_model = codex_plus_profile_test_model(profile, settings_data)
            test_api_key = codex_plus_profile_api_key(profile, settings_data)
            test_unavailable_reason = ""
            if not test_base_url:
                test_unavailable_reason = "未配置 Base URL"
            elif not valid_http_url(test_base_url):
                test_unavailable_reason = "Base URL 不是 http/https 地址"
            elif not test_api_key:
                test_unavailable_reason = "未配置 API Key"
            elif not test_model:
                test_unavailable_reason = "未配置测试模型"
            details = [
                f"ID：{profile_id}",
                f"模式：{relay_mode_label(profile.get('relayMode'))}",
                f"协议：{relay_protocol_label(profile.get('protocol'))}",
                f"Base URL：{base_url}",
                f"API Key：{secret_state(api_key, show_sensitive)}",
                f"模型：{model or '未配置'}",
                f"模型列表：{model_list_summary(profile.get('modelList'))}",
                f"模型写入方式：{first_text_value(profile.get('modelInsertMode')) or '未设置'}",
                f"上下文窗口：{first_text_value(profile.get('contextWindow')) or '未配置'}",
                f"自动压缩阈值：{first_text_value(profile.get('autoCompactLimit')) or '未配置'}",
                f"使用通用配置：{bool_text(profile.get('useCommonConfig', True))}",
                f"config.toml 存档：{'已保存' if config_text else '未保存'}",
                f"auth.json 存档：{'已保存' if first_text_value(profile.get('authContents')) else '未保存'}",
            ]
            relay_rows.append(
                make_row(
                    first_text_value(profile.get("name")) or profile_id,
                    "当前" if is_current else "备用",
                    "\n".join(details),
                )
            )
            relay_profile_cards.append(
                {
                    "source": "codexPlus",
                    "id": profile_id,
                    "appType": "codexPlus",
                    "appLabel": "Codex++",
                    "name": first_text_value(profile.get("name")) or profile_id,
                    "status": "当前" if is_current else "备用",
                    "isCurrent": is_current,
                    "category": relay_mode_label(profile.get("relayMode")),
                    "baseUrl": base_url,
                    "apiKey": secret_state(api_key, show_sensitive),
                    "websiteUrl": "",
                    "model": model or "未配置",
                    "apiFormat": relay_protocol_label(profile.get("protocol")),
                    "endpointCount": "",
                    "health": "按 Codex++ 源码发送最小 hi 请求",
                    "healthState": "neutral",
                    "sortIndex": "",
                    "icon": relay_protocol_label(profile.get("protocol")),
                    "iconColor": "#0f766e",
                    "extra": f"测试模型：{test_model or '未配置'}；使用通用配置：{bool_text(profile.get('useCommonConfig', True))}",
                    "createdAt": "",
                    "notes": "",
                    "inFailoverQueue": False,
                    "testable": not test_unavailable_reason,
                    "testUnavailableReason": test_unavailable_reason,
                }
            )

    if not relay_profile_cards and isinstance(settings_data, dict):
        legacy_base_url = first_text_value(settings_data.get("relayBaseUrl"))
        legacy_api_key = first_text_value(settings_data.get("relayApiKey"))
        legacy_model = first_text_value(settings_data.get("relayTestModel"))
        if legacy_base_url or legacy_api_key:
            test_unavailable_reason = ""
            if not legacy_base_url:
                test_unavailable_reason = "未配置 Base URL"
            elif not valid_http_url(legacy_base_url):
                test_unavailable_reason = "Base URL 不是 http/https 地址"
            elif not legacy_api_key:
                test_unavailable_reason = "未配置 API Key"
            elif not legacy_model:
                test_unavailable_reason = "未配置测试模型"
            relay_profile_cards.append(
                {
                    "source": "codexPlus",
                    "id": "legacy",
                    "appType": "codexPlus",
                    "appLabel": "Codex++",
                    "name": "旧版中转配置",
                    "status": "当前",
                    "isCurrent": True,
                    "category": "旧版",
                    "baseUrl": legacy_base_url or "未配置",
                    "apiKey": secret_state(legacy_api_key, show_sensitive),
                    "websiteUrl": "",
                    "model": legacy_model or "未配置",
                    "apiFormat": "Responses",
                    "endpointCount": "",
                    "health": "按 Codex++ 源码发送最小 hi 请求",
                    "healthState": "neutral",
                    "sortIndex": "",
                    "icon": "Responses",
                    "iconColor": "#0f766e",
                    "extra": f"测试模型：{legacy_model or '未配置'}",
                    "createdAt": "",
                    "notes": "",
                    "inFailoverQueue": False,
                    "testable": not test_unavailable_reason,
                    "testUnavailableReason": test_unavailable_reason,
                }
            )

    aggregate_rows: list[dict[str, str]] = []
    aggregate_profiles = settings_data.get("aggregateRelayProfiles") if isinstance(settings_data, dict) else []
    if isinstance(aggregate_profiles, list):
        active_aggregate_id = first_text_value(settings_data.get("activeAggregateRelayId"))
        for profile in aggregate_profiles:
            if not isinstance(profile, dict):
                continue
            members = profile.get("members") if isinstance(profile.get("members"), list) else []
            member_text = "、".join(
                f"{first_text_value(member.get('relayId')) or '未知'}(权重 {member.get('weight', 1)})"
                for member in members
                if isinstance(member, dict)
            )
            aggregate_rows.append(
                make_row(
                    first_text_value(profile.get("name"), profile.get("id")) or "未命名聚合",
                    "当前" if active_aggregate_id and first_text_value(profile.get("id")) == active_aggregate_id else "聚合",
                    f"ID：{first_text_value(profile.get('id')) or '未知'}；策略：{first_text_value(profile.get('strategy')) or 'failover'}；成员：{member_text or '未配置'}",
                )
            )

    return {
        "path": str(folder),
        "found": folder.exists(),
        "rows": rows,
        "overview": overview,
        "settings": settings_rows,
        "status": status_rows,
        "codexInjection": codex_plus_config_status(codex_folder, show_sensitive, settings_data),
        "relayProfiles": relay_rows,
        "relayProfileCards": relay_profile_cards,
        "aggregateProfiles": aggregate_rows,
        "files": rows,
        "errors": errors,
    }


def valid_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def unix_seconds() -> int:
    return int(time.time())


def stream_check_defaults() -> dict[str, int]:
    return {"timeoutSecs": 8, "maxRetries": 1, "degradedThresholdMs": 6000}


def merged_stream_check_config(global_config: dict[str, Any], meta: dict[str, Any]) -> dict[str, int]:
    config = stream_check_defaults()
    for key in ("timeoutSecs", "maxRetries", "degradedThresholdMs"):
        if global_config.get(key) is not None:
            try:
                config[key] = int(global_config[key])
            except (TypeError, ValueError):
                pass
    test_config = meta.get("testConfig") if isinstance(meta.get("testConfig"), dict) else {}
    if test_config.get("enabled"):
        for key in ("timeoutSecs", "maxRetries", "degradedThresholdMs"):
            if test_config.get(key) is not None:
                try:
                    config[key] = int(test_config[key])
                except (TypeError, ValueError):
                    pass
    config["timeoutSecs"] = max(1, config["timeoutSecs"])
    config["maxRetries"] = max(0, config["maxRetries"])
    config["degradedThresholdMs"] = max(1, config["degradedThresholdMs"])
    return config


def cc_switch_base_url(app_type: str, settings_config: dict[str, Any], meta: dict[str, Any]) -> str:
    details = extract_provider_settings(app_type, settings_config, meta, True)
    base_url = first_text_value(details.get("base_url"))
    if base_url and base_url != "未配置":
        return base_url
    if app_type == "opencode":
        options = settings_config.get("options") if isinstance(settings_config.get("options"), dict) else {}
        explicit = first_text_value(options.get("baseURL"), options.get("baseUrl"))
        if explicit:
            return explicit
        npm = first_text_value(settings_config.get("npm"))
        return {
            "@ai-sdk/openai": "https://api.openai.com/v1",
            "@ai-sdk/anthropic": "https://api.anthropic.com",
            "@ai-sdk/google": "https://generativelanguage.googleapis.com",
        }.get(npm, "")
    return ""


def cc_switch_provider_targets(folder: Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if folder is None:
        return [], ["未找到 .cc-switch 文件夹"]
    db_path = folder / "cc-switch.db"
    if not db_path.exists():
        return [], [f"未找到 {db_path}"]

    targets: list[dict[str, Any]] = []
    try:
        with sqlite_connect_readonly(db_path) as conn:
            global_config: dict[str, Any] = {}
            if sqlite_table_exists(conn, "settings"):
                row = conn.execute("SELECT value FROM settings WHERE key='stream_check_config' LIMIT 1").fetchone()
                if row:
                    global_config = parse_json_object(row["value"])
            if not sqlite_table_exists(conn, "providers"):
                return [], ["cc-switch.db 中没有 providers 表"]
            query = (
                "SELECT id, app_type, name, settings_config, website_url, category, meta "
                "FROM providers ORDER BY app_type, COALESCE(sort_index, 999999), created_at ASC, id ASC"
            )
            for row in conn.execute(query):
                settings_config = parse_json_object(row["settings_config"])
                meta = parse_json_object(row["meta"])
                base_url = cc_switch_base_url(row["app_type"], settings_config, meta)
                config = merged_stream_check_config(global_config, meta)
                custom_ua = first_text_value(meta.get("customUserAgent"))
                if "\r" in custom_ua or "\n" in custom_ua:
                    custom_ua = ""
                reason = ""
                if not base_url:
                    reason = "未配置 Base URL"
                elif not valid_http_url(base_url):
                    reason = "Base URL 不是 http/https 地址"
                targets.append(
                    {
                        "source": "ccSwitch",
                        "id": str(row["id"]),
                        "appType": str(row["app_type"]),
                        "name": str(row["name"] or row["id"]),
                        "appLabel": label_app(str(row["app_type"])),
                        "baseUrl": base_url,
                        "websiteUrl": first_text_value(row["website_url"]),
                        "category": label_category(row["category"]),
                        "categoryRaw": first_text_value(row["category"]),
                        "timeoutSecs": config["timeoutSecs"],
                        "maxRetries": config["maxRetries"],
                        "degradedThresholdMs": config["degradedThresholdMs"],
                        "customUserAgent": custom_ua,
                        "testable": not reason,
                        "testUnavailableReason": reason,
                    }
                )
    except Exception as exc:  # noqa: BLE001 - logged and shown through API
        write_exception_log("读取 CC Switch 供应商测试目标失败", exc, folder=str(folder))
        errors.append(str(exc))
    return targets, errors


def should_retry_stream_check(message: str) -> bool:
    lowered = message.casefold()
    return "timeout" in lowered or "abort" in lowered or "timed out" in lowered


def cc_switch_probe_once(target: dict[str, Any]) -> tuple[bool, int | None, str, int]:
    start = time.perf_counter()
    request = urllib.request.Request(
        target["baseUrl"],
        headers={
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    if target.get("customUserAgent"):
        request.add_header("User-Agent", target["customUserAgent"])
    try:
        with urllib.request.urlopen(request, timeout=float(target.get("timeoutSecs") or 8)) as response:
            status = int(response.getcode())
        elapsed = int((time.perf_counter() - start) * 1000)
        return True, status, "Reachable", elapsed
    except urllib.error.HTTPError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return True, int(exc.code), "Reachable", elapsed
    except Exception as exc:  # noqa: BLE001 - network errors are reported to the user
        elapsed = int((time.perf_counter() - start) * 1000)
        return False, None, str(exc), elapsed


def test_cc_switch_provider(target: dict[str, Any]) -> dict[str, Any]:
    if not target.get("testable"):
        return {
            "source": "ccSwitch",
            "id": target.get("id", ""),
            "appType": target.get("appType", ""),
            "name": target.get("name", ""),
            "success": False,
            "status": "failed",
            "message": target.get("testUnavailableReason") or "无法测试",
            "responseTimeMs": None,
            "httpStatus": None,
            "endpoint": target.get("baseUrl", ""),
            "modelUsed": "",
            "testedAt": now_text(),
            "retryCount": 0,
        }
    max_retries = int(target.get("maxRetries") or 0)
    last: tuple[bool, int | None, str, int] | None = None
    for attempt in range(max_retries + 1):
        last = cc_switch_probe_once(target)
        success, http_status, message, elapsed = last
        if success or attempt >= max_retries or not should_retry_stream_check(message):
            retry_count = attempt
            break
    else:
        retry_count = max_retries
    success, http_status, message, elapsed = last or (False, None, "Check failed", 0)
    status = "failed"
    if success:
        status = "operational" if elapsed <= int(target.get("degradedThresholdMs") or 6000) else "degraded"
    result = {
        "source": "ccSwitch",
        "id": target.get("id", ""),
        "appType": target.get("appType", ""),
        "name": target.get("name", ""),
        "success": success,
        "status": status,
        "message": "Base URL 可达" if success else message,
        "responseTimeMs": elapsed,
        "httpStatus": http_status,
        "endpoint": target.get("baseUrl", ""),
        "modelUsed": "",
        "testedAt": now_text(),
        "retryCount": retry_count,
    }
    write_log(
        "INFO" if success else "ERROR",
        "CC Switch 供应商连通性测试完成",
        provider=target.get("name"),
        app_type=target.get("appType"),
        endpoint=target.get("baseUrl"),
        status=status,
        http_status=http_status,
        response_time_ms=elapsed,
        result_message=message,
    )
    return result


def config_provider_from_text(config_text: str) -> dict[str, Any]:
    data = parse_toml_text(config_text)
    provider_id = first_text_value(data.get("model_provider"))
    providers = data.get("model_providers")
    if isinstance(providers, dict):
        if provider_id and isinstance(providers.get(provider_id), dict):
            return providers[provider_id]
        for provider in providers.values():
            if isinstance(provider, dict):
                return provider
    return {}


def codex_plus_profile_base_url(profile: dict[str, Any]) -> str:
    relay_mode = first_text_value(profile.get("relayMode"))
    if relay_mode == "aggregate" or profile.get("aggregate"):
        return "http://127.0.0.1:57321/v1"
    protocol = first_text_value(profile.get("protocol")) or "responses"
    config_text = first_text_value(profile.get("configContents"))
    config_data = parse_toml_text(config_text)
    if protocol == "chatCompletions":
        upstream = first_text_value(
            profile.get("upstreamBaseUrl"),
            config_data.get("codex_plus_chat_base_url"),
            profile.get("baseUrl"),
        )
        if upstream:
            return upstream
    provider_base_url = first_text_value(config_provider_from_text(config_text).get("base_url"))
    if protocol == "chatCompletions" and provider_base_url == "http://127.0.0.1:57321/v1":
        return ""
    return first_text_value(provider_base_url, profile.get("baseUrl"), profile.get("upstreamBaseUrl"))


def experimental_bearer_token_from_config(config_text: str) -> str:
    return first_text_value(config_provider_from_text(config_text).get("experimental_bearer_token"))


def codex_plus_profile_api_key(profile: dict[str, Any], settings_data: dict[str, Any]) -> str:
    relay_mode = first_text_value(profile.get("relayMode"))
    config_text = first_text_value(profile.get("configContents"))
    if relay_mode == "aggregate" or profile.get("aggregate"):
        return "codex-plus-aggregate"
    if relay_mode == "official":
        return first_text_value(experimental_bearer_token_from_config(config_text), profile.get("apiKey"), settings_data.get("relayApiKey"))
    return first_text_value(
        api_key_from_json_text(first_text_value(profile.get("authContents"))),
        experimental_bearer_token_from_config(config_text),
        profile.get("apiKey"),
        settings_data.get("relayApiKey"),
    )


def codex_plus_profile_model(profile: dict[str, Any]) -> str:
    config_model = first_text_value(parse_toml_text(first_text_value(profile.get("configContents"))).get("model"))
    return first_text_value(config_model, profile.get("model"))


def model_list_first(value: Any) -> str:
    text = first_text_value(value)
    if not text:
        return ""
    parts = [part.strip() for part in text.replace(",", "\n").splitlines() if part.strip()]
    return parts[0] if parts else ""


def codex_plus_profile_test_model(profile: dict[str, Any], settings_data: dict[str, Any]) -> str:
    return first_text_value(
        profile.get("testModel"),
        codex_plus_profile_model(profile),
        settings_data.get("relayTestModel"),
        model_list_first(profile.get("modelList")),
    )


def codex_plus_relay_targets(folder: Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    if folder is None:
        return [], ["未找到 Codex++ 状态目录"]
    settings_path = folder / "settings.json"
    settings_data, error = read_json_or_empty(settings_path)
    if error and settings_path.exists():
        return [], [f"settings.json：{error}"]
    targets: list[dict[str, Any]] = []
    profiles = settings_data.get("relayProfiles") if isinstance(settings_data, dict) else []
    active_id = first_text_value(settings_data.get("activeRelayId")) or "default"
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            profile_id = first_text_value(profile.get("id")) or "default"
            base_url = codex_plus_profile_base_url(profile)
            api_key = codex_plus_profile_api_key(profile, settings_data)
            model = codex_plus_profile_test_model(profile, settings_data)
            reason = ""
            if not base_url:
                reason = "未配置 Base URL"
            elif not valid_http_url(base_url):
                reason = "Base URL 不是 http/https 地址"
            elif not api_key:
                reason = "未配置 API Key"
            elif not model:
                reason = "未配置测试模型"
            targets.append(
                {
                    "source": "codexPlus",
                    "id": profile_id,
                    "appType": "codexPlus",
                    "name": first_text_value(profile.get("name")) or profile_id,
                    "baseUrl": base_url,
                    "apiKey": api_key,
                    "protocol": first_text_value(profile.get("protocol")) or "responses",
                    "relayMode": first_text_value(profile.get("relayMode")) or "official",
                    "model": model,
                    "isCurrent": profile_id == active_id,
                    "testable": not reason,
                    "testUnavailableReason": reason,
                }
            )
    if not targets and (first_text_value(settings_data.get("relayBaseUrl")) or first_text_value(settings_data.get("relayApiKey"))):
        base_url = first_text_value(settings_data.get("relayBaseUrl"))
        api_key = first_text_value(settings_data.get("relayApiKey"))
        model = first_text_value(settings_data.get("relayTestModel"))
        reason = ""
        if not base_url:
            reason = "未配置 Base URL"
        elif not valid_http_url(base_url):
            reason = "Base URL 不是 http/https 地址"
        elif not api_key:
            reason = "未配置 API Key"
        elif not model:
            reason = "未配置测试模型"
        targets.append(
            {
                "source": "codexPlus",
                "id": "legacy",
                "appType": "codexPlus",
                "name": "旧版中转配置",
                "baseUrl": base_url,
                "apiKey": api_key,
                "protocol": "responses",
                "relayMode": "legacy",
                "model": model,
                "isCurrent": True,
                "testable": not reason,
                "testUnavailableReason": reason,
            }
        )
    return targets, []


def codex_plus_endpoint(base_url: str, protocol: str) -> str:
    base = base_url.strip().rstrip("/")
    if protocol == "chatCompletions":
        return f"{base}/chat/completions"
    return f"{base}/responses"


def codex_plus_payload(protocol: str, model: str) -> dict[str, Any]:
    if protocol == "chatCompletions":
        return {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 16}
    return {"model": model, "input": "hi", "max_output_tokens": 16}


def codex_plus_models_endpoint(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        return ""
    if cleaned.casefold().endswith("/models"):
        return cleaned
    if cleaned.casefold().endswith("/v1"):
        return f"{cleaned}/models"
    return f"{cleaned}/v1/models"


def parse_model_payload(value: Any) -> list[str]:
    models: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                models.append(item.strip())
            elif isinstance(item, dict):
                model = first_text_value(item.get("id"), item.get("model"), item.get("name"))
                if model:
                    models.append(model)
    elif isinstance(value, dict):
        for key in ("data", "models", "items"):
            nested = parse_model_payload(value.get(key))
            if nested:
                models.extend(nested)
                break
        if not models:
            model = first_text_value(value.get("id"), value.get("model"), value.get("name"))
            if model:
                models.append(model)

    unique: list[str] = []
    seen: set[str] = set()
    for model in models:
        if model not in seen:
            seen.add(model)
            unique.append(model)
    return unique


def fetch_codex_plus_models(base_url: str, api_key: str) -> tuple[list[str], str, str]:
    endpoint = codex_plus_models_endpoint(base_url)
    if not endpoint:
        return [], "", "Base URL 为空"
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "CodexPlusPlus/RelayTest",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8", errors="replace"))
            return parse_model_payload(payload), endpoint, ""
    except urllib.error.HTTPError as exc:
        preview = exc.read(2048).decode("utf-8", errors="replace")
        return [], endpoint, f"HTTP {exc.code}：{short_text(sanitize_external_text(preview), 180)}"
    except Exception as exc:  # noqa: BLE001 - network errors are returned to UI
        return [], endpoint, str(exc)


def choose_codex_plus_test_model(configured_model: str, models: list[str]) -> str:
    configured = configured_model.strip()
    if configured and configured in models:
        return configured
    return models[0] if models else configured


def post_codex_plus_request(endpoint: str, api_key: str, payload: dict[str, Any]) -> tuple[int, str, int]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "CodexPlusPlus/RelayTest",
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = int(response.getcode())
            response_text = response.read(4096).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        response_text = exc.read(4096).decode("utf-8", errors="replace")
    elapsed = int((time.perf_counter() - start) * 1000)
    return status, response_text, elapsed


def test_codex_plus_provider(target: dict[str, Any]) -> dict[str, Any]:
    if not target.get("testable"):
        return {
            "source": "codexPlus",
            "id": target.get("id", ""),
            "appType": "codexPlus",
            "name": target.get("name", ""),
            "success": False,
            "status": "failed",
            "message": target.get("testUnavailableReason") or "无法测试",
            "responseTimeMs": None,
            "httpStatus": None,
            "endpoint": target.get("baseUrl", ""),
            "modelUsed": target.get("model", ""),
            "responsePreview": "",
            "testedAt": now_text(),
            "retryCount": 0,
        }
    base_url = target["baseUrl"].strip().rstrip("/")
    protocol = target.get("protocol") or "responses"
    configured_model = target.get("model") or ""
    models, models_endpoint, models_error = fetch_codex_plus_models(base_url, target["apiKey"])
    if not models:
        message = f"获取模型列表失败：{models_error or '上游没有返回可用模型'}"
        write_log(
            "ERROR",
            "Codex++ 获取模型列表失败",
            provider=target.get("name"),
            endpoint=models_endpoint,
            result_message=message,
        )
        return {
            "source": "codexPlus",
            "id": target.get("id", ""),
            "appType": "codexPlus",
            "name": target.get("name", ""),
            "success": False,
            "status": "failed",
            "message": message,
            "responseTimeMs": None,
            "httpStatus": None,
            "endpoint": models_endpoint,
            "modelUsed": "",
            "modelsEndpoint": models_endpoint,
            "modelsCount": 0,
            "responsePreview": "",
            "testedAt": now_text(),
            "retryCount": 0,
        }
    model = choose_codex_plus_test_model(configured_model, models)
    endpoint = codex_plus_endpoint(base_url, protocol)
    payload = codex_plus_payload(protocol, model)
    retry_count = 0
    v1_added = False
    try:
        status, preview, elapsed = post_codex_plus_request(endpoint, target["apiKey"], payload)
        if status == 404 and not base_url.endswith("/v1"):
            v1_endpoint = codex_plus_endpoint(f"{base_url}/v1", protocol)
            try:
                v1_status, v1_preview, v1_elapsed = post_codex_plus_request(v1_endpoint, target["apiKey"], payload)
                retry_count = 1
                if v1_status < 400:
                    v1_added = True
                    status, preview, elapsed, endpoint = v1_status, f"（Base URL 建议加上 /v1 前缀）{v1_preview}", v1_elapsed, v1_endpoint
            except Exception as exc:  # noqa: BLE001 - keep original 404 if /v1 retry itself fails
                write_exception_log("Codex++ /v1 重试失败", exc, provider=target.get("name"), endpoint=v1_endpoint)
        success = status < 400
        result = {
            "source": "codexPlus",
            "id": target.get("id", ""),
            "appType": "codexPlus",
            "name": target.get("name", ""),
            "success": success,
            "status": "operational" if success else "failed",
            "message": f"已用模型「{model}」发送 hi，HTTP {status}。" if success else f"测试失败，HTTP {status}。",
            "responseTimeMs": elapsed,
            "httpStatus": status,
            "endpoint": endpoint,
            "modelUsed": model,
            "configuredModel": configured_model,
            "modelsEndpoint": models_endpoint,
            "modelsCount": len(models),
            "v1Added": v1_added,
            "responsePreview": short_text(sanitize_external_text(preview.strip()), 320),
            "testedAt": now_text(),
            "retryCount": retry_count,
        }
        write_log(
            "INFO" if success else "ERROR",
            "Codex++ 供应商模型测试完成",
            provider=target.get("name"),
            endpoint=endpoint,
            model=model,
            models_endpoint=models_endpoint,
            models_count=len(models),
            v1_added=v1_added,
            status=result["status"],
            http_status=status,
            response_time_ms=elapsed,
        )
        return result
    except Exception as exc:  # noqa: BLE001 - network errors are returned to UI
        write_exception_log("Codex++ 供应商模型测试异常", exc, provider=target.get("name"), endpoint=endpoint, model=model)
        return {
            "source": "codexPlus",
            "id": target.get("id", ""),
            "appType": "codexPlus",
            "name": target.get("name", ""),
            "success": False,
            "status": "failed",
            "message": str(exc),
            "responseTimeMs": None,
            "httpStatus": None,
            "endpoint": endpoint,
            "modelUsed": model,
            "responsePreview": "",
            "testedAt": now_text(),
            "retryCount": 0,
        }


def provider_targets_for_source(source: str, discovery: FolderDiscovery) -> tuple[list[dict[str, Any]], list[str]]:
    if source == "ccSwitch":
        return cc_switch_provider_targets(discovery.cc_switch_folder)
    if source == "codexPlus":
        return codex_plus_relay_targets(discovery.codex_plus_folder)
    return [], [f"未知测试来源：{source}"]


def test_provider_result(source: str, target: dict[str, Any]) -> dict[str, Any]:
    if source == "ccSwitch":
        return test_cc_switch_provider(target)
    if source == "codexPlus":
        return test_codex_plus_provider(target)
    return {
        "source": source,
        "id": target.get("id", ""),
        "appType": target.get("appType", ""),
        "name": target.get("name", ""),
        "success": False,
        "status": "failed",
        "message": f"未知测试来源：{source}",
        "testedAt": now_text(),
    }


def discovery_from_payload(payload: dict[str, Any]) -> FolderDiscovery:
    return discover_folders(
        first_text_value(payload.get("codexPath")),
        first_text_value(payload.get("ccPath")),
        first_text_value(payload.get("codexPlusPath")),
    )


def handle_test_provider(payload: dict[str, Any]) -> dict[str, Any]:
    source = first_text_value(payload.get("source"))
    provider_id = first_text_value(payload.get("id"))
    app_type = first_text_value(payload.get("appType"))
    discovery = discovery_from_payload(payload)
    targets, errors = provider_targets_for_source(source, discovery)
    if errors:
        return {"ok": False, "errors": errors}
    target = next(
        (
            item
            for item in targets
            if item.get("id") == provider_id and (source == "codexPlus" or item.get("appType") == app_type)
        ),
        None,
    )
    if target is None:
        return {"ok": False, "errors": [f"未找到供应商：{provider_id}"]}
    write_log("INFO", "开始供应商测试", source=source, provider=target.get("name"), app_type=target.get("appType"), endpoint=target.get("baseUrl"))
    return {"ok": True, "result": test_provider_result(source, target)}


def handle_test_all_providers(payload: dict[str, Any]) -> dict[str, Any]:
    source = first_text_value(payload.get("source"))
    discovery = discovery_from_payload(payload)
    targets, errors = provider_targets_for_source(source, discovery)
    if errors:
        return {"ok": False, "errors": errors}
    write_log("INFO", "开始一键测试供应商", source=source, count=len(targets))
    results = [test_provider_result(source, target) for target in targets]
    return {"ok": True, "source": source, "results": results}


class SHFileOpStructW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_bool),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def move_path_to_recycle_bin(path: Path) -> None:
    if platform.system() != "Windows":
        raise RuntimeError("移入回收站目前仅支持 Windows。")
    absolute = str(path.resolve())
    operation = SHFileOpStructW()
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = absolute + "\0\0"
    operation.fFlags = 0x0040 | 0x0010 | 0x0400 | 0x0004  # allow undo, no confirm, no error UI, silent
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise RuntimeError(f"移入回收站失败，错误码：{result}")
    if operation.fAnyOperationsAborted:
        raise RuntimeError("移入回收站操作已取消")


def backup_codex_files(codex_folder: Path) -> dict[str, Any]:
    backup_root = app_directory() / "old codex"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / stamp
    counter = 1
    while backup_dir.exists():
        counter += 1
        backup_dir = backup_root / f"{stamp}_{counter}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    backed_up: list[str] = []
    missing: list[str] = []
    for filename in ("config.toml", "auth.json"):
        source = codex_folder / filename
        if source.exists() and source.is_file():
            shutil.copy2(source, backup_dir / filename)
            backed_up.append(filename)
        else:
            missing.append(filename)
    return {"backupDir": str(backup_dir), "backedUp": backed_up, "missing": missing}


def handle_repair_codex(payload: dict[str, Any]) -> dict[str, Any]:
    discovery = discovery_from_payload(payload)
    codex_folder = discovery.codex_folder
    if codex_folder is None or not codex_folder.exists():
        return {"ok": False, "errors": ["未找到 .codex 文件夹"]}
    if codex_folder.name.casefold() != ".codex":
        return {"ok": False, "errors": [f"当前路径不是 .codex 文件夹：{codex_folder}"]}
    try:
        backup = backup_codex_files(codex_folder)
        move_path_to_recycle_bin(codex_folder)
        write_log(
            "INFO",
            "一键修复已完成",
            codex_folder=str(codex_folder),
            backup_dir=backup["backupDir"],
            backed_up=backup["backedUp"],
            missing=backup["missing"],
        )
        return {
            "ok": True,
            "message": ".codex 已移入回收站，原 config.toml 和 auth.json 已按存在情况备份。",
            **backup,
        }
    except Exception as exc:  # noqa: BLE001 - repair failures are logged and shown
        write_exception_log("一键修复失败", exc, codex_folder=str(codex_folder))
        return {"ok": False, "errors": [str(exc)]}


def build_snapshot(query: dict[str, list[str]]) -> dict[str, Any]:
    codex_override = query.get("codex", [""])[0].strip() or None
    cc_override = query.get("cc", [""])[0].strip() or None
    codex_plus_override = query.get("codexPlus", [""])[0].strip() or None
    show_sensitive = query.get("sensitive", ["0"])[0] == "1"
    discovery = discover_folders(codex_override, cc_override, codex_plus_override)
    config = read_config(discovery.codex_folder)
    auth = read_auth(discovery.codex_folder, show_sensitive)
    cc_switch = read_cc_switch(discovery.cc_switch_folder, show_sensitive)
    codex_plus = read_codex_plus(discovery.codex_plus_folder, discovery.codex_folder, show_sensitive)
    return {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "system": collect_system_info(),
        "userEnvironment": collect_user_environment(show_sensitive),
        "paths": {
            "codex": str(discovery.codex_folder) if discovery.codex_folder else "",
            "ccSwitch": str(discovery.cc_switch_folder) if discovery.cc_switch_folder else "",
            "codexPlus": str(discovery.codex_plus_folder) if discovery.codex_plus_folder else "",
            "log": str(logs.get_log_path()),
            "codexCandidates": [str(path) for path in discovery.codex_candidates],
            "ccSwitchCandidates": [str(path) for path in discovery.cc_switch_candidates],
            "codexPlusCandidates": [str(path) for path in discovery.codex_plus_candidates],
        },
        "config": config,
        "auth": auth,
        "ccSwitch": cc_switch,
        "codexPlus": codex_plus,
    }


# HTML 模板已抽到 webui/cfgtpl.py（1526 行纯数据，不掺逻辑）。
# 这里保留同名引用，cfgcenter.HTML_PAGE 的调用方无需改动。
from .cfgtpl import HTML_PAGE  # noqa: F401  (向后兼容 cfgcenter.HTML_PAGE)
