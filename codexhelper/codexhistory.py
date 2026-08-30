# -*- coding: utf-8 -*-
"""Codex 历史会话（threads）管理：列表 / 归档恢复 / 删除 / 从其它 agent 导入。

## 数据布局（实测 2026-08-30，Codex Desktop 0.142.5）

```
<codex_home>/
├── sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl   # 会话正文（rollout）
├── archived_sessions/…                              # 归档后的 rollout
├── session_index.jsonl                              # {id, thread_name, updated_at}
├── state_5.sqlite        ← threads 表（权威索引，含 archived 标记）
├── thread_history_1.sqlite                          # thread_items / thread_turns 投影
└── logs_2.sqlite         ← logs 表（运行日志，见 codexlogs.py）
```

**threads 表关键列**：`id, rollout_path, created_at, updated_at, source,
model_provider, cwd, title, tokens_used, has_user_event, archived,
archived_at, first_user_message, preview, is_pinned, thread_source`

## 标题回退链

实测 60 条会话里 title 只有 52 条非空、且 CLI 来源的会话 title 常为空串，
但 `preview` 非空率最高（56/60）。因此按下列顺序回退：

    title → name → preview → first_user_message → session_index.thread_name → "(无标题)"

## 写操作安全约定

1. **改库前一律备份**到 `backups_state/codexhelper/<时间戳>/`
   （与 codex-provider-sync 的 `backups_state/provider-sync/` 同层级，互不干扰）。
2. **只读操作走 `mode=ro` URI**，绝不因读而加锁或产生 -wal/-shm 副产物。
3. 写入时 Codex 若正在运行会锁库，捕获 `OperationalError` 并提示用户关闭。
4. 删除会连带清理 rollout 文件 + thread_history 投影，**不可撤销**（故强制备份）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import codexpaths

BACKUP_ROOT = "backups_state"
BACKUP_DIR = "codexhelper"

# 归档 / 活跃会话目录名（与 codexpaths._PORTABLE_MARKERS 保持一致）
SESSIONS = "sessions"
ARCHIVED = "archived_sessions"


# -------------------------------------------------------------------- 连接 --
def _ro(db: Path) -> sqlite3.Connection:
    """只读连接。Codex 运行时也能读，且不会生成 -wal/-shm。"""
    con = sqlite3.connect("file:" + str(db) + "?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _rw(db: Path) -> sqlite3.Connection:
    """读写连接。给足 busy_timeout 以应对 Codex 短时间占用。"""
    con = sqlite3.connect(str(db), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 15000")
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "select 1 from sqlite_master where type='table' and name=?", (name,)
    ).fetchone()
    return row is not None


# ------------------------------------------------------------ 索引辅助读取 --
def _session_index_names(codex_home: Path) -> dict[str, str]:
    """读 session_index.jsonl：{thread_id: thread_name}。

    该文件可能很大或含坏行，逐行容错解析，坏行跳过而不是整体失败。
    """
    out: dict[str, str] = {}
    f = codex_home / "session_index.jsonl"
    if not f.is_file():
        return out
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            tid = d.get("id")
            name = d.get("thread_name")
            if tid and name:
                out[str(tid)] = str(name)
    except Exception:
        pass
    return out


def _pick_title(row: sqlite3.Row, index_names: dict[str, str]) -> str:
    """按回退链取标题。"""
    for key in ("title", "name", "preview", "first_user_message"):
        try:
            v = row[key]
        except (IndexError, KeyError):
            v = None
        if v:
            s = " ".join(str(v).split())
            if s:
                return s[:120]
    nm = index_names.get(str(row["id"]))
    if nm:
        return " ".join(nm.split())[:120]
    return "(无标题)"


def _stat_size_mtime(p: Path | None) -> tuple[int, int]:
    if not p:
        return 0, 0
    try:
        st = p.stat()
        return st.st_size, int(st.st_mtime)
    except OSError:
        return 0, 0


# ------------------------------------------------------------------ 列表 ----
def list_threads(only_archived: bool | None = None,
                 limit: int = 500,
                 keyword: str = "") -> dict:
    """列出会话。only_archived: None=全部 / True=仅归档 / False=仅活跃。"""
    home = codexpaths.resolve_codex_home()
    if not home:
        return {"ok": False, "error": "未能定位 CODEX_HOME", "threads": []}
    db = codexpaths.state_db(home)
    if not db or not db.is_file():
        return {"ok": False, "error": f"未找到状态库 state_5.sqlite（{home}）",
                "threads": []}

    names = _session_index_names(home)
    con = _ro(db)
    try:
        if not _table_exists(con, "threads"):
            return {"ok": False, "error": "状态库中没有 threads 表", "threads": []}
        sql = ("select * from threads")
        where, args = [], []
        if only_archived is True:
            where.append("archived = 1")
        elif only_archived is False:
            where.append("archived = 0")
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by coalesce(updated_at, created_at, 0) desc limit ?"
        args.append(int(limit))
        rows = con.execute(sql, args).fetchall()
    finally:
        con.close()

    kw = (keyword or "").strip().lower()
    items = []
    for r in rows:
        title = _pick_title(r, names)
        if kw and kw not in title.lower() and kw not in str(r["id"]).lower():
            continue
        rollout = codexpaths.relocate_rollout(r["rollout_path"], home)
        size, mtime = _stat_size_mtime(rollout)
        items.append({
            "id": r["id"],
            "title": title,
            "archived": int(r["archived"] or 0),
            "archived_at": r["archived_at"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "source": r["source"],
            "thread_source": r["thread_source"],
            "model_provider": r["model_provider"],
            "model": r["model"],
            "cwd": codexpaths.strip_win32_prefix(str(r["cwd"] or "")),
            "tokens_used": r["tokens_used"],
            "is_pinned": int(r["is_pinned"] or 0),
            "rollout": codexpaths.rollout_display(r["rollout_path"]),
            "rollout_exists": bool(rollout),
            "rollout_size": size,
            "missing": rollout is None,
        })
    return {"ok": True, "home": str(home), "threads": items,
            "total": len(items)}


def stats() -> dict:
    """会话总数 / 归档数 / 占用空间等概览。"""
    home = codexpaths.resolve_codex_home()
    if not home:
        return {"ok": False, "error": "未能定位 CODEX_HOME"}
    db = codexpaths.state_db(home)
    out = {"ok": True, "home": str(home), "total": 0, "archived": 0,
           "active": 0, "size": 0, "missing": 0, "providers": {}}
    if not db or not db.is_file():
        return out
    con = _ro(db)
    try:
        if not _table_exists(con, "threads"):
            return out
        out["total"] = con.execute("select count(*) from threads").fetchone()[0]
        out["archived"] = con.execute(
            "select count(*) from threads where archived=1").fetchone()[0]
        out["active"] = out["total"] - out["archived"]
        for pid, cnt in con.execute(
                "select model_provider, count(*) c from threads group by model_provider"):
            out["providers"][pid or "(空)"] = cnt
        rows = con.execute("select id, rollout_path from threads").fetchall()
    finally:
        con.close()
    for r in rows:
        p = codexpaths.relocate_rollout(r["rollout_path"], home)
        if p is None:
            out["missing"] += 1
        else:
            out["size"] += _stat_size_mtime(p)[0]
    return out


# -------------------------------------------------------------------- 备份 --
def backup_databases(home: Path, tag: str) -> Path | None:
    """把要修改的库备份到 backups_state/codexhelper/<时间戳>_<tag>/。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = home / BACKUP_ROOT / BACKUP_DIR / f"{stamp}_{tag}"
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    for name in ("state_5.sqlite", "thread_history_1.sqlite",
                 "session_index.jsonl", "config.toml"):
        src = home / name
        if src.is_file():
            try:
                shutil.copy2(src, dest / name)
                # -wal / -shm 一并带走，否则单拷主库可能读不到最新内容
                for suf in ("-wal", "-shm"):
                    w = home / (name + suf)
                    if w.is_file():
                        shutil.copy2(w, dest / (name + suf))
            except OSError:
                pass
    return dest


def list_backups() -> list[dict]:
    home = codexpaths.resolve_codex_home()
    if not home:
        return []
    root = home / BACKUP_ROOT / BACKUP_DIR
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir(), reverse=True):
        if d.is_dir():
            out.append({"name": d.name,
                        "size": sum(f.stat().st_size for f in d.rglob("*")
                                    if f.is_file())})
    return out[:20]


# ---------------------------------------------------------- 归档 / 恢复 ----
def _move_rollout(src: Path, dst_dir: Path, home: Path) -> Path | None:
    """把 rollout 移动到目标目录，保持 `sessions` 之后的 YYYY/MM/DD 分层。

    ⚠ 坑（实测踩过）：相对部分**绝不能带前导反斜杠**。
    `Path(r"D:\\x\\archived_sessions") / "\\2026\\08\\29\\a.jsonl"` 在
    Windows 上会被当成从盘符根起的绝对路径 `C:\\2026\\08\\29\\a.jsonl`，
    文件会被静默移到 C 盘根目录。因此这里统一走
    `codexpaths.rollout_display()` 拿 `sessions\\2026\\...` 形式，
    再切掉首段得到 `2026\\...`，确保是真正的相对路径。
    """
    if not src or not src.is_file():
        return None
    disp = codexpaths.rollout_display(str(src))    # sessions\2026\08\29\x.jsonl
    if not disp:
        return None
    parts = disp.replace("/", "\\").split("\\")
    if len(parts) < 2 or parts[0] not in (SESSIONS, ARCHIVED):
        return None
    rel = "\\".join(parts[1:])                     # 2026\08\29\x.jsonl
    dst = dst_dir / rel
    # 兜底断言：dst 必须落在 dst_dir 之内。
    # 注意不能判 `dst.is_absolute()` —— dst_dir 自身就是绝对路径，
    # 那样会把正常情况也误杀。真正的风险是 rel 带前导分隔符导致
    # 路径跳到盘符根，用"是否位于 dst_dir 之下"来卡才准确。
    try:
        if dst_dir.resolve() not in dst.resolve().parents:
            return None
    except OSError:
        return None
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return dst
    except OSError:
        return None


def set_archived(worker, ids: list[str], archived: bool) -> dict:
    """归档（True）或恢复（False）一批会话。

    归档 = 置 archived 标记 + 把 rollout 移入 archived_sessions/；
    恢复 = 反向操作。rollout 移动失败不阻断，仅登记标记变化。
    """
    home = codexpaths.resolve_codex_home()
    if not home:
        return {"ok": False, "error": "未能定位 CODEX_HOME"}
    db = codexpaths.state_db(home)
    if not db or not db.is_file():
        return {"ok": False, "error": "未找到状态库"}

    ids = [str(i).strip() for i in (ids or []) if str(i).strip()]
    if not ids:
        return {"ok": False, "error": "未选择会话"}

    word = "归档" if archived else "恢复"
    worker.status(f"正在{word} {len(ids)} 个会话…")
    bak = backup_databases(home, "archive" if archived else "restore")
    worker.log(f"已备份数据库到 {bak}" if bak else "备份数据库失败，已中止",
               "ok" if bak else "err")
    if not bak:
        return {"ok": False, "error": "备份失败，已中止以防数据损坏"}

    done, moved, failed = 0, 0, []
    now = int(time.time())
    con = _rw(db)
    try:
        for i, tid in enumerate(ids):
            worker.check_cancel()
            worker.q.put(("progress", (i + 1) / len(ids)))
            row = con.execute(
                "select id, rollout_path, archived from threads where id=?",
                (tid,)).fetchone()
            if not row:
                failed.append(f"{tid[:8]}：库中不存在")
                continue
            if int(row["archived"] or 0) == int(archived):
                continue  # 已是目标状态，跳过

            # 移动 rollout 文件
            raw = row["rollout_path"]
            cur = codexpaths.relocate_rollout(raw, home)
            target_dir = home / (ARCHIVED if archived else SESSIONS)
            new_path = None
            if cur:
                new_path = _move_rollout(cur, target_dir, home)
            if new_path:
                moved += 1
                con.execute("update threads set rollout_path=? where id=?",
                            (str(new_path), tid))
            elif cur is None:
                worker.log(f"{tid[:8]}：rollout 文件已缺失，仅更新标记", "warn")

            if archived:
                con.execute(
                    "update threads set archived=1, archived_at=? where id=?",
                    (now, tid))
            else:
                con.execute(
                    "update threads set archived=0, archived_at=NULL where id=?",
                    (tid,))
            done += 1
        con.commit()
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
    except sqlite3.OperationalError as exc:
        con.rollback()
        msg = str(exc)
        if "locked" in msg.lower():
            return {"ok": False,
                    "error": "数据库被占用：请先完全关闭 Codex 桌面端 / CLI 后重试"}
        return {"ok": False, "error": f"数据库写入失败：{msg}"}
    finally:
        con.close()

    worker.log(f"{word}完成：标记 {done} 个，移动会话文件 {moved} 个",
               "ok" if not failed else "warn")
    for f in failed[:10]:
        worker.log(f"· {f}", "warn")
    return {"ok": True, "changed": done, "moved": moved, "failed": failed,
            "backup": str(bak)}


# ------------------------------------------------------------------ 删除 ----
def delete_threads(worker, ids: list[str]) -> dict:
    """删除会话：库记录 + 投影 + rollout 文件。操作前强制备份。"""
    home = codexpaths.resolve_codex_home()
    if not home:
        return {"ok": False, "error": "未能定位 CODEX_HOME"}
    db = codexpaths.state_db(home)
    hdb = codexpaths.history_db(home)
    if not db or not db.is_file():
        return {"ok": False, "error": "未找到状态库"}

    ids = [str(i).strip() for i in (ids or []) if str(i).strip()]
    if not ids:
        return {"ok": False, "error": "未选择会话"}

    worker.status(f"正在删除 {len(ids)} 个会话…")
    bak = backup_databases(home, "delete")
    if not bak:
        return {"ok": False, "error": "备份失败，已中止以防数据丢失"}
    worker.log(f"已备份数据库到 {bak}", "ok")

    removed_db, removed_file = 0, 0
    failed = []
    con = _rw(db)
    try:
        for i, tid in enumerate(ids):
            worker.check_cancel()
            worker.q.put(("progress", (i + 1) / len(ids)))
            row = con.execute(
                "select id, rollout_path from threads where id=?", (tid,)).fetchone()
            cur = codexpaths.relocate_rollout(row["rollout_path"], home) if row else None

            con.execute("delete from threads where id=?", (tid,))
            removed_db += 1

            # 清理 thread_history 投影（可能不存在该表/记录，忽略）
            if hdb and hdb.is_file():
                try:
                    h = _rw(hdb)
                    for t in ("thread_items", "thread_turns",
                              "thread_history_projection_state",
                              "thread_realtime_items"):
                        if _table_exists(h, t):
                            h.execute(f"delete from {t} where thread_id=?", (tid,))
                    h.commit()
                    h.close()
                except sqlite3.Error:
                    pass

            if cur and cur.is_file():
                try:
                    cur.unlink()
                    removed_file += 1
                except OSError as e:
                    failed.append(f"{tid[:8]}：删除文件失败（{e}）")
        con.commit()
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
    except sqlite3.OperationalError as exc:
        con.rollback()
        msg = str(exc)
        if "locked" in msg.lower():
            return {"ok": False,
                    "error": "数据库被占用：请先完全关闭 Codex 桌面端 / CLI 后重试"}
        return {"ok": False, "error": f"数据库写入失败：{msg}"}
    finally:
        con.close()

    # 同步清理 session_index.jsonl（Codex 启动时也会自行重建，这里尽力而为）
    _prune_session_index(home, set(ids))

    worker.log(f"删除完成：库记录 {removed_db} 条，会话文件 {removed_file} 个",
               "ok" if not failed else "warn")
    for f in failed[:10]:
        worker.log(f"· {f}", "warn")
    return {"ok": True, "removed_db": removed_db, "removed_file": removed_file,
            "failed": failed, "backup": str(bak)}


def _prune_session_index(home: Path, ids: set[str]) -> None:
    f = home / "session_index.jsonl"
    if not f.is_file():
        return
    try:
        keep = []
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                d = json.loads(s)
            except Exception:
                keep.append(s)
                continue
            if str(d.get("id")) in ids:
                continue
            keep.append(s)
        tmp = f.with_suffix(".tmp")
        tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
        tmp.replace(f)
    except Exception:
        pass


# ------------------------------------------------------------------ 导入 ----
def _parse_rollout_meta(path: Path) -> dict | None:
    """读 rollout 首行的 session_meta。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if d.get("type") == "session_meta":
                    p = d.get("payload") or {}
                    return {
                        "id": p.get("id") or p.get("session_id"),
                        "cwd": p.get("cwd") or "",
                        "timestamp": p.get("timestamp") or d.get("timestamp"),
                        "source": p.get("source"),
                        "model_provider": p.get("model_provider") or "",
                        "cli_version": p.get("cli_version") or "",
                        "originator": p.get("originator") or "",
                        "thread_source": p.get("thread_source") or "",
                    }
                return None  # 首行不是 meta，非 Codex rollout
    except Exception:
        return None
    return None


def _first_user_text(path: Path) -> str:
    """从 rollout 里取首条用户输入，作为标题兜底。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 200:
                    break
                s = line.strip()
                if not s:
                    continue
                try:
                    d = json.loads(s)
                except Exception:
                    continue
                p = d.get("payload") or {}
                if d.get("type") == "event_msg" and p.get("type") == "user_message":
                    return " ".join(str(p.get("message") or "").split())[:200]
                if d.get("type") == "response_item" and p.get("role") == "user":
                    for c in (p.get("content") or []):
                        if isinstance(c, dict) and c.get("type") in (
                                "input_text", "text"):
                            return " ".join(str(c.get("text") or "").split())[:200]
    except Exception:
        pass
    return ""


def scan_import_sources() -> list[dict]:
    """扫描本机可导入的会话来源（其它 agent 或另一个 Codex profile）。"""
    home = Path.home()
    out: list[dict] = []
    cands = [
        ("Claude Code", home / ".claude" / "projects",
         "claude", "~/.claude/projects 下的 *.jsonl"),
        ("Codex（另一 profile）", None, "codex-dir",
         "手动选择另一个 .codex 目录"),
    ]
    for name, path, kind, hint in cands:
        if path is None:
            out.append({"name": name, "path": "", "kind": kind, "hint": hint,
                        "count": 0, "exists": False})
            continue
        n = 0
        if path.is_dir():
            n = len(list(path.rglob("*.jsonl")))
        out.append({"name": name, "path": str(path), "kind": kind, "hint": hint,
                    "count": n, "exists": path.is_dir()})
    return out


def _dest_rollout(home: Path, thread_id: str, ts: str | None) -> Path:
    """按 Codex 的 日期分层 规则算出目标 rollout 路径。"""
    if ts:
        s = str(ts).replace("Z", "").strip()
        date_part = s[:10]                      # 2026-08-29
        y, m, d = (date_part.split("-") + ["01", "01", "01"])[:3]
        stamp = s.replace(":", "-").replace(".", "-")[:19]
    else:
        now = datetime.now()
        y, m, d = f"{now.year:04d}", f"{now.month:02d}", f"{now.day:02d}"
        stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    name = f"rollout-{stamp}-{thread_id}.jsonl"
    return home / SESSIONS / y / m / d / name


def _insert_thread(con: sqlite3.Connection, meta: dict, rollout: Path,
                   first_user: str, source_tag: str) -> bool:
    """向 threads 表插入一条记录。缺列时自动降级为最小字段集。"""
    cols = [r[1] for r in con.execute("PRAGMA table_info(threads)")]
    now = int(time.time())
    title = (first_user or "")[:200]
    base = {
        "id": meta["id"],
        "rollout_path": str(rollout),
        "created_at": now, "updated_at": now,
        "created_at_ms": now * 1000, "updated_at_ms": now * 1000,
        "recency_at": now, "recency_at_ms": now * 1000,
        "source": "cli", "model_provider": meta.get("model_provider") or "custom",
        "cwd": meta.get("cwd") or "",
        "title": title, "preview": title, "first_user_message": title,
        "sandbox_policy": "", "approval_mode": "", "tokens_used": 0,
        "has_user_event": 1 if title else 0,
        "archived": 0, "archived_at": None, "is_pinned": 0,
        "model": "", "reasoning_effort": "", "cli_version": meta.get("cli_version") or "",
        "thread_source": source_tag, "memory_mode": "",
        "history_mode": "", "name": None,
    }
    data = {k: v for k, v in base.items() if k in cols}
    keys = ",".join(f'"{k}"' for k in data)
    marks = ",".join("?" for _ in data)
    con.execute(f"insert or replace into threads ({keys}) values ({marks})",
                list(data.values()))
    return True


def import_codex_dir(worker, src_dir: str, limit: int = 500) -> dict:
    """从另一个 Codex profile 目录导入会话（同格式，直接复制 rollout）。"""
    home = codexpaths.resolve_codex_home()
    if not home:
        return {"ok": False, "error": "未能定位 CODEX_HOME"}
    src = Path(codexpaths.strip_win32_prefix(src_dir or ""))
    if not src.is_dir():
        return {"ok": False, "error": f"源目录不存在：{src_dir}"}

    files: list[Path] = []
    for base in (src / SESSIONS, src / ARCHIVED):
        if base.is_dir():
            files.extend(base.rglob("*.jsonl"))
    if not files:
        return {"ok": False, "error": f"源目录里没有会话文件：{src}"}
    files = files[:limit]

    worker.status(f"扫描到 {len(files)} 个会话文件，开始导入…")
    bak = backup_databases(home, "import-codex")
    worker.log(f"已备份数据库到 {bak}" if bak else "备份失败，已中止",
               "ok" if bak else "err")
    if not bak:
        return {"ok": False, "error": "备份失败，已中止"}

    db = codexpaths.state_db(home)
    con = _rw(db)
    imported, skipped, failed = 0, 0, []
    try:
        for i, f in enumerate(files):
            worker.check_cancel()
            worker.q.put(("progress", (i + 1) / len(files)))
            meta = _parse_rollout_meta(f)
            if not meta or not meta.get("id"):
                skipped += 1
                continue
            exist = con.execute("select 1 from threads where id=?",
                                (meta["id"],)).fetchone()
            if exist:
                skipped += 1
                continue
            try:
                dest = _dest_rollout(home, meta["id"], meta.get("timestamp"))
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
                _insert_thread(con, meta, dest, _first_user_text(dest), "import")
                imported += 1
            except Exception as e:  # noqa: BLE001
                failed.append(f"{f.name}：{e}")
        con.commit()
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
    except sqlite3.OperationalError as exc:
        con.rollback()
        msg = str(exc)
        if "locked" in msg.lower():
            return {"ok": False, "error": "数据库被占用：请先关闭 Codex 后重试"}
        return {"ok": False, "error": f"数据库写入失败：{msg}"}
    finally:
        con.close()

    worker.log(f"导入完成：新增 {imported} 个，跳过（已存在/非会话）{skipped} 个",
               "ok" if not failed else "warn")
    for f in failed[:10]:
        worker.log(f"· {f}", "warn")
    return {"ok": True, "imported": imported, "skipped": skipped,
            "failed": failed, "backup": str(bak)}


# ------------------------------------------------- Claude Code 格式转换 ----
# Claude 会在会话里注入这些 XML 标记包裹的系统文本（命令回显、免责声明等）。
# 它们不是用户的真实输入，必须剥掉，否则导入后标题会变成一串 Caveat 说明。
_CLAUDE_INJECTED = re.compile(
    r"<(?:local-command-caveat|command-name|command-message|command-args|"
    r"local-command-stdout|local-command-stderr|system-reminder)>.*?"
    r"</(?:local-command-caveat|command-name|command-message|command-args|"
    r"local-command-stdout|local-command-stderr|system-reminder)>",
    re.S,
)


def _claude_text(msg: dict) -> str:
    """从 Claude 的 message.content 取纯文本（content 可能是字符串或块数组）。"""
    c = msg.get("content")
    if isinstance(c, str):
        text = c
    else:
        parts = []
        if isinstance(c, list):
            for blk in c:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text":
                    parts.append(str(blk.get("text") or ""))
                elif blk.get("type") == "tool_use":
                    parts.append(f"[工具调用 {blk.get('name', '')}]")
                elif blk.get("type") == "tool_result":
                    parts.append("[工具结果]")
        text = "\n".join(p for p in parts if p)
    # 剥掉注入块，并压掉多余空行
    text = _CLAUDE_INJECTED.sub("", text)
    text = "\n".join(ln for ln in (t.strip() for t in text.splitlines()) if ln)
    return text.strip()


def _read_claude_session(f: Path) -> dict | None:
    """解析一个 Claude Code 会话文件，返回可转换的中间结构。"""
    rows = []
    session_id = None
    cwd = ""
    ts = None
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                d = json.loads(s)
            except Exception:
                continue
            if not session_id and d.get("sessionId"):
                session_id = str(d["sessionId"])
            if not cwd and d.get("cwd"):
                cwd = str(d["cwd"])
            if not ts and d.get("timestamp"):
                ts = str(d["timestamp"])
            if d.get("type") in ("user", "assistant"):
                msg = d.get("message") or {}
                text = _claude_text(msg)
                if text:
                    rows.append({
                        "role": "user" if d.get("type") == "user" else "assistant",
                        "text": text,
                        "ts": d.get("timestamp") or ts,
                        "uuid": d.get("uuid") or "",
                    })
    except Exception:
        return None
    if not rows:
        return None
    return {"session_id": session_id or f.stem, "cwd": cwd, "timestamp": ts,
            "rows": rows, "file": f}


def _write_rollout(dest: Path, session: dict, thread_id: str) -> None:
    """按 Codex rollout 格式写出：session_meta + 逐条消息。

    每条消息写两行，与实测的 Codex rollout 结构一致：
      - user      → event_msg(user_message) + response_item(message/user)
      - assistant → response_item(message/assistant)
    """
    meta_ts = session.get("timestamp") or datetime.now().isoformat()
    lines = [{
        "timestamp": meta_ts,
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "session_id": thread_id,
            "timestamp": meta_ts,
            "cwd": session.get("cwd") or "",
            "originator": "Codex 小帮手（自 Claude Code 导入）",
            "cli_version": "", "source": "cli",
            "thread_source": "import",
            "model_provider": "custom",
            "base_instructions": {"text": ""},
        },
    }]
    for r in session["rows"]:
        rid = r.get("uuid") or str(uuid.uuid4())
        ts = r.get("ts") or meta_ts
        if r["role"] == "user":
            lines.append({
                "timestamp": ts, "type": "event_msg",
                "payload": {"type": "user_message", "client_id": rid,
                            "message": r["text"], "images": [],
                            "local_images": [], "text_elements": []},
            })
            lines.append({
                "timestamp": ts, "type": "response_item",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": r["text"]}]},
            })
        else:
            lines.append({
                "timestamp": ts, "type": "response_item",
                "payload": {"type": "message", "role": "assistant",
                            "id": rid, "phase": "final_answer",
                            "content": [{"type": "output_text", "text": r["text"]}]},
            })
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def import_claude_code(worker, src_dir: str = "", limit: int = 200) -> dict:
    """从 Claude Code 导入会话（~/.claude/projects 下的 *.jsonl）。

    做格式转换：Claude 的 `{"type":"user"|"assistant","message":{...}}`
    转成 Codex rollout 的 session_meta / event_msg / response_item 结构。
    只迁移纯文本，工具调用以 `[工具调用 名称]` 占位保留上下文可读性。
    """
    home = codexpaths.resolve_codex_home()
    if not home:
        return {"ok": False, "error": "未能定位 CODEX_HOME"}
    src = Path(codexpaths.strip_win32_prefix(src_dir or "")) \
        if src_dir else Path.home() / ".claude" / "projects"
    if not src.is_dir():
        return {"ok": False, "error": f"Claude 会话目录不存在：{src}"}

    files = sorted(src.rglob("*.jsonl"))[:limit]
    if not files:
        return {"ok": False, "error": f"目录里没有会话文件：{src}"}

    worker.status(f"扫描到 {len(files)} 个 Claude 会话文件…")
    sessions, skipped = [], 0
    for f in files:
        s = _read_claude_session(f)
        if s:
            sessions.append(s)
        else:
            skipped += 1
    if not sessions:
        return {"ok": False, "error": "没有解析出可导入的对话内容"}

    bak = backup_databases(home, "import-claude")
    worker.log(f"已备份数据库到 {bak}" if bak else "备份失败，已中止",
               "ok" if bak else "err")
    if not bak:
        return {"ok": False, "error": "备份失败，已中止"}

    db = codexpaths.state_db(home)
    con = _rw(db)
    imported, dup, failed = 0, 0, []
    try:
        for i, s in enumerate(sessions):
            worker.check_cancel()
            worker.q.put(("progress", (i + 1) / len(sessions)))
            tid = str(uuid.uuid4())
            try:
                dest = _dest_rollout(home, tid, s.get("timestamp"))
                _write_rollout(dest, s, tid)
                first_user = ""
                for r in s["rows"]:
                    if r["role"] == "user":
                        first_user = " ".join(r["text"].split())[:200]
                        break
                _insert_thread(con,
                               {"id": tid, "cwd": s.get("cwd") or "",
                                "model_provider": "custom", "cli_version": "",
                                "timestamp": s.get("timestamp")},
                               dest, first_user, "import")
                imported += 1
            except Exception as e:  # noqa: BLE001
                failed.append(f"{Path(s['file']).name}：{e}")
        con.commit()
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
    except sqlite3.OperationalError as exc:
        con.rollback()
        msg = str(exc)
        if "locked" in msg.lower():
            return {"ok": False, "error": "数据库被占用：请先关闭 Codex 后重试"}
        return {"ok": False, "error": f"数据库写入失败：{msg}"}
    finally:
        con.close()

    worker.log(f"导入完成：新增 {imported} 个会话（跳过空会话 {skipped} 个）",
               "ok" if not failed else "warn")
    for f in failed[:10]:
        worker.log(f"· {f}", "warn")
    return {"ok": True, "imported": imported, "skipped": skipped,
            "failed": failed, "backup": str(bak)}
