# -*- coding: utf-8 -*-
"""读取 Codex 运行日志（.codex 内的 logs_2.sqlite）+ 本程序自身日志。

## 数据源

`logs_2.sqlite` 的 `logs` 表：

    id, ts, ts_nanos, level, target, feedback_log_body,
    module_path, file, line, thread_id, process_uuid, estimated_bytes

实测（2026-08-30）：本机 170 MB / 1.2 万行——**单行正文很大**，
因此绝不能 `select *` 后全量搬到前端，必须：

1. **只取需要的列**，且一律带 `limit`（走主键 `id` 的索引，避免全表扫）。
2. **按 ts 过滤会退化为全表扫**（ts 无索引），因此时间过滤放在拿到
   主键有序的结果后再做，或直接用 id 近似切片。
3. **关键词过滤在 Python 侧做**：正文大，`like '%x%'` 同样要全表扫，
   而应用侧过滤可以边扫边截断，内存可控。
4. 正文在返回前端前截断（默认 2000 字符），避免 170MB 库把浏览器打爆。

## 跨机器

日志库的位置一律经 `codexpaths` 解析，不拼接任何硬编码用户名/盘符，
因此换电脑、改用户名、主目录重定向到 D 盘都能读到。
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from . import codexpaths, logs
from .util import res_path

# 返回给前端的单条正文截断长度
BODY_LIMIT = 2000
# 单次查询硬上限，防止浏览器卡死
MAX_ROWS = 2000

LEVELS = ("ERROR", "WARN", "INFO", "DEBUG", "TRACE")


def _open(db: Path) -> sqlite3.Connection | None:
    """只读打开日志库。

    优先 mode=ro；若因 -wal/-shm 权限问题失败，回退 immutable=1
    （不尝试加锁、忽略 WAL，可能少读最新几条，但保证"能读到"）。
    """
    for uri in ("file:" + str(db) + "?mode=ro",
                "file:" + str(db) + "?immutable=1"):
        try:
            con = sqlite3.connect(uri, uri=True, timeout=5)
            con.row_factory = sqlite3.Row
            con.execute("select 1 from logs limit 1")
            return con
        except sqlite3.Error:
            try:
                con.close()
            except Exception:
                pass
            continue
    return None


def _fmt_ts(ts) -> str:
    """秒级/毫秒级时间戳 → 本地时间字符串。"""
    if ts is None:
        return ""
    try:
        v = float(ts)
    except (TypeError, ValueError):
        return str(ts)
    if v > 1e11:      # 毫秒
        v /= 1000.0
    if v <= 0:
        return ""
    try:
        return datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(ts)


def query_logs(levels: list[str] | None = None,
               keyword: str = "",
               thread_id: str = "",
               limit: int = 200,
               offset: int = 0,
               body_limit: int = BODY_LIMIT) -> dict:
    """查询日志。默认按 id 倒序（最新在前）。

    levels    ：级别过滤，空表示全部
    keyword   ：正文/模块/目标关键词（Python 侧过滤）
    thread_id ：按会话 id 过滤（SQL 侧，thread_id 有值才生效）
    """
    home = codexpaths.resolve_codex_home()
    if not home:
        return {"ok": False, "error": "未能定位 CODEX_HOME", "rows": []}
    db = codexpaths.logs_db(home)
    if not db or not db.is_file():
        return {"ok": False, "error": f"未找到日志库 logs_2.sqlite（{home}）",
                "rows": []}

    con = _open(db)
    if con is None:
        return {"ok": False, "error": "无法打开日志库（可能被占用或权限不足）",
                "rows": []}

    limit = max(1, min(int(limit or 200), MAX_ROWS))
    offset = max(0, int(offset or 0))
    kw = (keyword or "").strip().lower()
    tid = (thread_id or "").strip()
    want = {str(x).upper() for x in (levels or []) if str(x).strip()}

    # 级别过滤下推到 SQL。
    # 不能只在应用层过滤：ERROR 通常只有十几条且集中在早期，
    # 若先按 id 倒序取候选页再过滤，用户翻很多页都看不到它们——
    # 而错误日志恰恰是最需要被找到的。level 列很短，让 SQLite 扫更快。
    sql = ("select id, ts, ts_nanos, level, target, module_path, file, line, "
           "thread_id, estimated_bytes, feedback_log_body "
           "from logs")
    args: list = []
    conds = []
    if want:
        conds.append(
            "upper(level) in (%s)" % ",".join("?" for _ in want))
        args.extend(want)
    if tid:
        conds.append("thread_id = ?")
        args.append(tid)
    if conds:
        sql += " where " + " and ".join(conds)
    # 关键词仍在应用层过滤（正文很大，且没有可用索引），
    # 因此多取一些候选，保证过滤后还能凑满一页。
    fetch = limit if not kw else min(limit * 8 + 400, MAX_ROWS * 4)
    sql += " order by id desc limit ? offset ?"
    args += [fetch, offset]

    rows = []
    scanned = 0
    try:
        for r in con.execute(sql, args):
            scanned += 1
            lvl = str(r["level"] or "").upper()
            if want and lvl not in want:
                continue
            body = r["feedback_log_body"] or ""
            if kw:
                hay = (body + " " + str(r["target"] or "") + " "
                       + str(r["module_path"] or "")).lower()
                if kw not in hay:
                    continue
            text = " ".join(str(body).split())
            truncated = len(text) > body_limit
            rows.append({
                "id": r["id"],
                "ts": _fmt_ts(r["ts"]),
                "raw_ts": r["ts"],
                "level": lvl,
                "target": r["target"] or "",
                "module": r["module_path"] or "",
                "file": r["file"] or "",
                "line": r["line"],
                "thread_id": r["thread_id"] or "",
                "bytes": r["estimated_bytes"] or 0,
                "body": text[:body_limit],
                "truncated": truncated,
            })
            if len(rows) >= limit:
                break
    except sqlite3.Error as exc:
        con.close()
        return {"ok": False, "error": f"查询失败：{exc}", "rows": []}
    con.close()

    return {"ok": True, "rows": rows, "limit": limit, "offset": offset,
            "scanned": scanned, "home": str(home), "db": str(db),
            "has_more": len(rows) >= limit}


def summary() -> dict:
    """日志库概览：总条数、各级别数量、时间范围、占用大小。"""
    home = codexpaths.resolve_codex_home()
    if not home:
        return {"ok": False, "error": "未能定位 CODEX_HOME"}
    db = codexpaths.logs_db(home)
    if not db or not db.is_file():
        return {"ok": False, "error": "未找到日志库", "levels": {}}
    con = _open(db)
    if con is None:
        return {"ok": False, "error": "无法打开日志库", "levels": {}}

    out = {"ok": True, "db": str(db), "size": db.stat().st_size,
           "total": 0, "levels": {}, "min_ts": None, "max_ts": None,
           "threads": 0}
    try:
        out["total"] = con.execute("select count(*) from logs").fetchone()[0]
        for lvl, cnt in con.execute(
                "select level, count(*) c from logs group by level order by c desc"):
            out["levels"][str(lvl)] = cnt
        r = con.execute("select min(ts), max(ts) from logs").fetchone()
        if r:
            out["min_ts"] = _fmt_ts(r[0])
            out["max_ts"] = _fmt_ts(r[1])
        r2 = con.execute(
            "select count(distinct thread_id) from logs where thread_id is not null"
        ).fetchone()
        out["threads"] = r2[0] if r2 else 0
    except sqlite3.Error as exc:
        out["error"] = str(exc)
    finally:
        con.close()
    return out


def export_logs(dest: str, levels: list[str] | None = None,
                keyword: str = "", limit: int = 5000) -> dict:
    """导出日志为纯文本，便于用户拿去排查或发群里求助。"""
    res = query_logs(levels=levels, keyword=keyword, limit=limit,
                     offset=0, body_limit=100000)
    if not res.get("ok"):
        return res
    rows = res["rows"]
    path = Path(dest) if dest else Path.home() / "Desktop" / (
        "codex-logs-" + time.strftime("%Y%m%d-%H%M%S") + ".txt")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# Codex 日志导出\n# 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            fh.write(f"# 共 {len(rows)} 条\n\n")
            for r in rows:
                fh.write(f"[{r['ts']}] {r['level']:<5} {r['target']}\n")
                if r["thread_id"]:
                    fh.write(f"  thread: {r['thread_id']}\n")
                if r["file"]:
                    fh.write(f"  at {r['file']}:{r['line']}\n")
                fh.write(f"  {r['body']}\n\n")
    except OSError as exc:
        return {"ok": False, "error": f"写入失败：{exc}"}
    return {"ok": True, "path": str(path), "count": len(rows)}


# --------------------------------------------------- 本程序自身的日志 ----
def helper_log_path() -> str | None:
    """本程序（Codex 小帮手）自身的运行日志。

    优先使用 logs 模块的持久化位置（%LOCALAPPDATA%\\CodexHelper\\），
    找不到时回退 exe / 脚本旁边的旧位置，保证 onefile 与脚本模式都能读到。
    """
    new = logs.get_log_path()
    if new.is_file():
        return str(new)
    # 兼容旧位置：脚本模式或历史日志
    p = res_path("Codex Helper.log")
    if p:
        return p
    try:
        base = Path(os.path.dirname(os.path.abspath(
            __import__("sys").executable)))
        cand = base / "Codex Helper.log"
        return str(cand) if cand.is_file() else None
    except Exception:
        return None


def read_helper_log(tail_lines: int = 300) -> dict:
    """读本程序自身日志的末尾若干行（返回纯文本，保留历史格式）。"""
    p = helper_log_path()
    if not p or not os.path.isfile(p):
        return {"ok": False, "error": "未找到本程序日志（Codex Helper.log）",
                "path": p or "", "text": ""}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        return {"ok": False, "error": f"读取失败：{exc}", "path": p, "text": ""}
    tail = lines[-max(1, int(tail_lines)):]
    return {"ok": True, "path": p, "text": "\n".join(tail),
            "total_lines": len(lines)}
