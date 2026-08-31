# -*- coding: utf-8 -*-
"""统一日志模块：持久化 + 轮转 + 敏感值脱敏 + 尾部读取。

设计目标
--------
1. **持久化到固定位置**：优先 ``%LOCALAPPDATA%\\CodexHelper\\``，
   无论 exe 是 onefile 还是脚本模式都能找得到。
2. **轮转**：10 MB × 5 份，避免日志无限增长。
3. **结构化**：每行 JSON，含时间戳、级别、模块名、行号、消息、脱敏后的 extra。
4. **AI 友好**：提供 `tail()` 函数，支持按级别过滤与分页，方便 `/api/helper-log`
   直接返回给 AI 排查。
5. **向后兼容**：原 `cfgcenter.write_log` / `write_exception_log` 的调用点无需修改。
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "CodexHelper"
LOG_FILE = LOG_DIR / "Codex Helper.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5

# 同步兼容 onefile 打包：把旧位置（exe 旁边的 Codex Helper.log）作为只读历史源
_OLD_LOG_NAME = "Codex Helper.log"

_SENSITIVE_KEYS = (
    "access", "apikey", "api_key", "auth", "cookie", "credential", "key",
    "password", "refresh", "secret", "session", "token", "api-key",
    "authorization", "proxy_authorization", "x-api-key",
)


def _is_sensitive_key(key: str) -> bool:
    k = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(s in k for s in _SENSITIVE_KEYS) or k.endswith("key")


def redact(value: Any, key_path: str = "") -> Any:
    """递归脱敏。嵌套 dict/list 都能处理，字符串值替换为 ***。"""
    if isinstance(value, dict):
        return {k: redact(v, f"{key_path}.{k}" if key_path else k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key_path) for v in value]
    if key_path and _is_sensitive_key(key_path):
        return "***"
    return value


class _JsonFormatter(logging.Formatter):
    """每行输出一条 JSON 日志。"""

    def format(self, record: logging.LogRecord) -> str:
        # 解析 extra 字段：排除 logging 自带字段
        builtins = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msec", "relativeCreated", "thread", "threadName",
            "processName", "process", "asctime", "message", "msecs", "taskName",
            }
        extra = {k: v for k, v in record.__dict__.items() if k not in builtins}
        entry = {
            "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "module": record.module,
            "filename": record.filename,
            "line": record.lineno,
            "message": record.getMessage(),
            "extra": redact(extra) if extra else None,
        }
        if record.exc_info:
            entry["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            entry["error"] = str(record.exc_info[1]) if record.exc_info[1] else None
            entry["traceback"] = "".join(traceback.format_exception(*record.exc_info)).strip()
        return json.dumps(entry, ensure_ascii=False)


# 延迟初始化：首次写日志时才创建 logger / handler，避免导入副作用
_logger: logging.Logger | None = None


def _ensure_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    _logger = logging.getLogger("CodexHelper")
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
        encoding="utf-8", delay=False,
    )
    handler.setFormatter(_JsonFormatter())
    _logger.addHandler(handler)

    # 首次启动时在日志里留一条元信息，方便排查
    _logger.info("日志服务启动", extra={
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "frozen": getattr(sys, "frozen", False),
        "log_dir": str(LOG_DIR),
    })
    return _logger


def get_log_dir() -> Path:
    return LOG_DIR


def get_log_path() -> Path:
    return LOG_FILE


def write(level: str, message: str, **kwargs: Any) -> None:
    """对外主要入口。兼容原 cfgcenter.write_log 签名。"""
    logger = _ensure_logger()
    lvl = getattr(logging, level.upper(), logging.INFO)
    extra = {"raw_level": level.upper()}
    if kwargs:
        extra.update(kwargs)
    logger.log(lvl, message, extra=extra)


def exception(message: str, exc: BaseException | None = None, **kwargs: Any) -> None:
    """写异常日志。兼容原 cfgcenter.write_exception_log 签名。"""
    logger = _ensure_logger()
    extra = kwargs.copy()
    if exc:
        extra["error_code"] = type(exc).__name__
        extra["error"] = str(exc)
    logger.exception(message, extra=extra)


def tail(lines: int = 300, level: str | None = None,
         keyword: str = "", offset: int = 0) -> dict[str, Any]:
    """读日志文件末尾。返回与 codexlogs 风格一致的 dict。"""
    path = get_log_path()
    if not path.is_file():
        # 兼容旧日志：exe 旁边的 Codex Helper.log（脚本模式或历史文件）
        old = Path(sys.executable).parent / _OLD_LOG_NAME if getattr(sys, "frozen", False) else None
        if old and old.is_file():
            path = old
        else:
            return {"ok": False, "error": "日志文件不存在", "path": str(path), "rows": []}

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read().splitlines()
    except OSError as exc:
        return {"ok": False, "error": f"读取失败：{exc}", "path": str(path), "rows": []}

    rows = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # 旧格式（纯文本或 JSONL 不严格）兜底，按文本行处理
            obj = {"time": "", "level": "INFO", "module": "", "line": 0,
                   "message": line, "raw": True}
        lvl = str(obj.get("level") or "").upper()
        if level and lvl != level.upper():
            continue
        msg = str(obj.get("message") or "")
        if keyword and keyword.lower() not in msg.lower():
            continue
        rows.append(obj)

    total = len(rows)
    end = max(0, total - offset)
    start = max(0, end - max(1, lines))
    return {
        "ok": True,
        "path": str(path),
        "total": total,
        "offset": offset,
        "limit": lines,
        "rows": rows[start:end],
    }


def client_error(message: str, kind: str = "onerror", **kwargs: Any) -> None:
    """前端异常上报：单独落到 client-errors.log（同样做 10MB×5 轮转）。"""
    logger = _ensure_logger()
    path = get_log_dir() / "client-errors.log"
    handler = None
    for h in logger.handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == str(path):
            handler = h
            break
    if handler is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
            encoding="utf-8", delay=False,
        )
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
    record = logger.makeRecord(
        logger.name, logging.ERROR, "", 0,
        f"[{kind}] {message}", (), None)
    record.extra = redact(kwargs) if kwargs else None
    logger.handle(record)


def tail_client_errors(lines: int = 100, keyword: str = "",
                       offset: int = 0) -> dict[str, Any]:
    """读取 client-errors.log 末尾。"""
    path = get_log_dir() / "client-errors.log"
    if not path.is_file():
        return {"ok": False, "error": "客户端错误日志不存在",
                "path": str(path), "rows": [], "total": 0}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read().splitlines()
    except OSError as exc:
        return {"ok": False, "error": f"读取失败：{exc}",
                "path": str(path), "rows": []}
    rows = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            obj = {"message": line}
        if keyword and keyword.lower() not in str(obj.get("message", "")).lower():
            continue
        rows.append(obj)
    total = len(rows)
    start = max(0, min(offset, total))
    end = min(total, start + max(1, lines))
    return {"ok": True, "path": str(path), "total": total,
            "offset": start, "limit": lines, "rows": rows[start:end]}


def ensure_task_log(job_id: str) -> Path:
    """为每个后台任务生成独立日志文件，方便失败后单独查看。"""
    d = LOG_DIR / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", job_id)
    return d / f"{safe}.log"


def write_task_log(job_id: str, tag: str, text: str) -> None:
    """把任务日志同时落到任务专属文件。"""
    try:
        p = ensure_task_log(job_id)
        line = json.dumps({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tag": tag,
            "text": str(text),
        }, ensure_ascii=False)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        # 任务日志失败不应拖垮主流程，但开发期把异常写入主日志方便排查
        write("ERROR", "任务日志写入失败", job_id=job_id, error=str(exc))


def tail_task_log(job_id: str, lines: int = 200) -> dict[str, Any]:
    p = ensure_task_log(job_id)
    if not p.is_file():
        return {"ok": False, "error": "任务日志不存在", "rows": []}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read().splitlines()
    except OSError as exc:
        return {"ok": False, "error": f"读取失败：{exc}", "rows": []}
    out = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"time": "", "tag": "info", "text": line})
    return {"ok": True, "rows": out[-max(1, lines):], "total": len(out)}


# 兼容旧 cfgcenter 的导入习惯
def write_log(level: str, message: str, **kwargs: Any) -> None:
    write(level, message, **kwargs)


def write_exception_log(message: str, exc: BaseException | None = None, **kwargs: Any) -> None:
    exception(message, exc, **kwargs)
