# -*- coding: utf-8 -*-
"""v1.7.0 三个新模块的沙箱自测：codexpaths / codexhistory / codexlogs。

## 为什么不用 pytest

1. 本机未安装 pytest，引入新依赖会牵动 PyInstaller 打包体积与离线可用性。
2. 项目既有 `test_new_features_headless.py` 的同款无依赖自测风格，
   且 v1.7.0 的发布前 CI 已约定跑 `CodexHelper.exe --self-test`，
   保持一套 `ok(name, cond)` 汇总的写法，接入自检成本最低。

## 安全性

**全程不碰真实 `~/.codex`**：所有用例都在 `F:\\vibe code\\_tmp\\` 下的临时
沙箱里建库造文件，并把 `codexpaths.resolve_codex_home` 打桩指向沙箱。
写操作（归档/删除/导入）因此永远不会落在用户真实数据上。

跑法：
    cd F:\\vibe code\\src
    python test_codex_modules_headless.py
"""
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Windows 控制台默认 GBK，会把 emoji / 部分中文打死在编码环节。
# 统一改成 UTF-8 + 容错，保证脚本在 cmd / PowerShell / CI 里都能打印。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codexhelper import codexpaths, codexhistory, codexlogs  # noqa: E402

# ------------------------------------------------------------------ 断言器 --
_results = []
_bad = []
_code = 1          # 默认失败：用例中途抛异常时不至于误报通过


def ok(name, cond):
    cond = bool(cond)
    _results.append(cond)
    if not cond:
        _bad.append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def section(t):
    print(f"== {t} ==")


# ------------------------------------------------------------------ 沙箱 ----
TMP_ROOT = Path(r"F:\vibe code\_tmp")
TMP_ROOT.mkdir(parents=True, exist_ok=True)
SANDBOX = Path(tempfile.mkdtemp(prefix="cxmod_", dir=str(TMP_ROOT)))

# 每个用例独占一个假 CODEX_HOME，避免互相污染
_n = [0]


def new_home() -> Path:
    _n[0] += 1
    h = SANDBOX / f"home{_n[0]}"
    (h / "sessions").mkdir(parents=True, exist_ok=True)
    (h / "archived_sessions").mkdir(parents=True, exist_ok=True)
    codexpaths.resolve_codex_home = lambda *a, **k: h
    return h


THREAD_COLS = """
    id TEXT PRIMARY KEY,
    rollout_path TEXT,
    created_at INTEGER,
    created_at_ms INTEGER,
    updated_at INTEGER,
    updated_at_ms INTEGER,
    recency_at INTEGER,
    recency_at_ms INTEGER,
    source TEXT,
    model_provider TEXT,
    cwd TEXT,
    title TEXT,
    preview TEXT,
    first_user_message TEXT,
    tokens_used INTEGER,
    has_user_event INTEGER,
    archived INTEGER DEFAULT 0,
    archived_at INTEGER,
    is_pinned INTEGER DEFAULT 0,
    model TEXT,
    reasoning_effort TEXT,
    cli_version TEXT,
    thread_source TEXT,
    memory_mode TEXT,
    history_mode TEXT,
    sandbox_policy TEXT,
    approval_mode TEXT,
    name TEXT
"""

LOG_COLS = """
    id INTEGER PRIMARY KEY,
    ts REAL,
    ts_nanos INTEGER,
    level TEXT,
    target TEXT,
    feedback_log_body TEXT,
    module_path TEXT,
    file TEXT,
    line INTEGER,
    thread_id TEXT,
    process_uuid TEXT,
    estimated_bytes INTEGER
"""


def make_state_db(home: Path) -> Path:
    db = home / "state_5.sqlite"
    con = sqlite3.connect(str(db))
    con.execute(f"create table threads ({THREAD_COLS})")
    con.commit()
    con.close()
    return db


def make_logs_db(home: Path) -> Path:
    db = home / "logs_2.sqlite"
    con = sqlite3.connect(str(db))
    con.execute(f"create table logs ({LOG_COLS})")
    con.commit()
    con.close()
    return db


def make_history_db(home: Path) -> Path:
    db = home / "thread_history_1.sqlite"
    con = sqlite3.connect(str(db))
    con.execute("create table thread_items (thread_id TEXT, item TEXT)")
    con.execute("create table thread_turns (thread_id TEXT, turn TEXT)")
    con.execute("insert into thread_items values ('t1','x')")
    con.execute("insert into thread_turns values ('t1','y')")
    con.commit()
    con.close()
    return db


def add_thread(db: Path, tid, rollout="", archived=0, title=None,
               preview=None, first=None, name=None, cwd="", updated=0):
    con = sqlite3.connect(str(db))
    con.execute(
        "insert into threads (id, rollout_path, created_at, updated_at, source,"
        " model_provider, cwd, title, preview, first_user_message, tokens_used,"
        " has_user_event, archived, archived_at, is_pinned, thread_source,"
        " model, name)"
        " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid, str(rollout), 1700000000, updated or 1700000000, "cli", "openai",
         cwd, title, preview, first, 0, 1, archived,
         int(time.time()) if archived else None, 0, "cli", "gpt-5", name))
    con.commit()
    con.close()


def add_log(db: Path, lid, ts, level, body, target="codex_core", tid=None,
            module="codex_core::x", file="src/a.rs", line=1):
    con = sqlite3.connect(str(db))
    con.execute(
        "insert into logs (id, ts, ts_nanos, level, target, feedback_log_body,"
        " module_path, file, line, thread_id, process_uuid, estimated_bytes)"
        " values (?,?,?,?,?,?,?,?,?,?,?,?)",
        (lid, ts, int(ts * 1e9), level, target, body, module, file, line,
         tid, "pu", len(body)))
    con.commit()
    con.close()


def write_rollout(home: Path, sub: str, tid: str, ts="2026-08-29T10-00-00") -> Path:
    """在 home/sub/YYYY/MM/DD/ 下写一个合法 rollout（首行 session_meta）。"""
    y, m, d = "2026", "08", "29"
    p = home / sub / y / m / d / f"rollout-{ts}-{tid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {"timestamp": f"{y}-{m}-{d}T10:00:00Z", "type": "session_meta",
            "payload": {"id": tid, "session_id": tid, "cwd": "C:\\proj",
                        "timestamp": f"{y}-{m}-{d}T10:00:00Z", "source": "cli",
                        "model_provider": "openai", "cli_version": "0.1.0",
                        "thread_source": "cli"}}
    p.write_text(_json(meta) + "\n", encoding="utf-8")
    return p


def _json(o):
    import json
    return json.dumps(o, ensure_ascii=False)


# ------------------------------------------------------------------ worker --
class _Q:
    def put(self, *a, **k):
        pass


class FakeWorker:
    """替代后台 Worker：只收集调用，不触 UI。"""

    def __init__(self):
        self.q = _Q()
        self.logs = []
        self.statuses = []

    def status(self, msg):
        self.statuses.append(msg)

    def log(self, msg, level="info"):
        self.logs.append((level, str(msg)))

    def check_cancel(self):
        pass


try:
    # ============================================================ codexpaths ==
    section("1. codexpaths：Win32 长路径前缀")
    ok(r"\\?\C:\a 去前缀", codexpaths.strip_win32_prefix(r"\\?\C:\a") == r"C:\a")
    ok(r"\\?\UNC\srv\share → \\srv\share",
       codexpaths.strip_win32_prefix(r"\\?\UNC\srv\share") == r"\\srv\share")
    ok("普通路径原样返回",
       codexpaths.strip_win32_prefix(r"D:\x\.codex") == r"D:\x\.codex")
    ok("空串返回空", codexpaths.strip_win32_prefix("") == "")
    ok("None 返回空", codexpaths.strip_win32_prefix(None) == "")

    section("2. codexpaths：TOML 根级标量解析（无第三方依赖）")
    toml = ('# comment\nsqlite_home = "C:/data/codex/state.sqlite"\n'
            '[other]\nsqlite_home = "C:/bad"\n')
    ok("命中根级 key",
       codexpaths._toml_root_scalar(toml, "sqlite_home")
       == "C:/data/codex/state.sqlite")
    ok("忽略 [section] 内同名 key", "bad" not in (
        codexpaths._toml_root_scalar(toml, "sqlite_home") or ""))
    ok("不存在的 key 返回 None",
       codexpaths._toml_root_scalar(toml, "nope") is None)

    section("3. codexpaths：rollout 重定位（跨机器核心）")
    home = new_home()
    # 文件名必须与 write_rollout 生成的完全一致，否则重定位查无此文件
    fname = "rollout-2026-08-29T10-00-00-old.jsonl"
    old = "C:\\Users\\张三\\.codex\\sessions\\2026\\08\\29\\" + fname
    real = write_rollout(home, "sessions", "old")
    got = codexpaths.relocate_rollout(old, home)
    ok(f"旧机器绝对路径 → 新 home（{got}）", got is not None and got.is_file())
    ok("重定位结果落在新 home 之下",
       got is not None and str(got).lower().startswith(str(home).lower()))
    ok("UNC/长路径前缀也能重定位",
       codexpaths.relocate_rollout("\\\\?\\" + old, home) is not None)
    ok("正斜杠混用也能重定位",
       codexpaths.relocate_rollout(old.replace("\\", "/"), home) is not None)
    ok("目标不存在 → None",
       codexpaths.relocate_rollout(
           r"C:\Users\x\.codex\sessions\2026\08\29\rollout-none.jsonl",
           home) is None)
    ok("无 sessions 标记 → None",
       codexpaths.relocate_rollout(r"C:\Users\x\.codex\other\a.jsonl",
                                   home) is None)
    ok("空路径 → None", codexpaths.relocate_rollout("", home) is None)
    write_rollout(home, "archived_sessions", "old")
    ok("archived_sessions 也可重定位",
       codexpaths.relocate_rollout(
           "D:\\u\\.codex\\archived_sessions\\2026\\08\\29\\" + fname,
           home) is not None)

    section("4. codexpaths：展示路径")
    ok("rollout_display 截到 sessions 之后",
       codexpaths.rollout_display(old) == "sessions\\2026\\08\\29\\" + fname)
    ok("rollout_display 去长路径前缀",
       codexpaths.rollout_display("\\\\?\\" + old)
       == "sessions\\2026\\08\\29\\" + fname)
    ok("无标记时返回原串",
       codexpaths.rollout_display(r"D:\x\a.jsonl") == r"D:\x\a.jsonl")
    ok("空串返回空", codexpaths.rollout_display("") == "")

    section("5. codexpaths：库文件定位优先级")
    home = new_home()
    make_state_db(home)
    (home / "sqlite").mkdir(exist_ok=True)
    make_state_db(home / "sqlite")
    make_logs_db(home / "sqlite")
    # threads 在根 state_5.sqlite，新版 sqlite/ 目录里只有桌面端自有表。
    # 优先级必须是"根 state_5.sqlite 在前"，切勿按"新版目录优先"排序。
    ok("state_db 优先根目录 state_5.sqlite",
       codexpaths.state_db(home) == home / "state_5.sqlite")
    ok("logs_db 能回退到 sqlite/ 子目录",
       codexpaths.logs_db(home) == home / "sqlite" / "logs_2.sqlite")
    home2 = new_home()
    ok("state_db 都不存在时返回默认路径",
       codexpaths.state_db(home2) == home2 / "state_5.sqlite")
    ok("logs_db 都不存在时返回默认路径",
       codexpaths.logs_db(home2) == home2 / "logs_2.sqlite")
    ok("history_db 都不存在时返回默认路径",
       codexpaths.history_db(home2) == home2 / "thread_history_1.sqlite")
    ok("sessions_dir / archived_dir 正确",
       codexpaths.sessions_dir(home2) == home2 / "sessions"
       and codexpaths.archived_dir(home2) == home2 / "archived_sessions")

    section("6. codexpaths：describe 诊断信息")
    home = new_home()
    make_state_db(home)
    make_logs_db(home)
    write_rollout(home, "sessions", "d1")
    info = codexpaths.describe()
    ok("返回 home 且 exists", info["home"] == str(home) and info["exists"])
    ok("state_db / logs_db / sessions 均已识别",
       info["state_db"] and info["logs_db"] and info["sessions"])
    ok(f"sessions_count 正确（{info['sessions_count']}）",
       info["sessions_count"] == 1)
    ok("archived_count 为 0", info["archived_count"] == 0)

    # ========================================================== codexhistory ==
    section("7. codexhistory：标题回退链")
    home = new_home()
    db = make_state_db(home)
    add_thread(db, "t-title", title="显式标题")
    add_thread(db, "t-name", name="回退到 name")
    add_thread(db, "t-preview", preview="回退到 preview  ")
    add_thread(db, "t-first", first="回退到 first_user_message")
    add_thread(db, "t-none")
    (home / "session_index.jsonl").write_text(
        _json({"id": "t-none", "thread_name": "索引里的名字"}) + "\n"
        + "这不是 json\n" + "\n", encoding="utf-8")
    names = codexhistory._session_index_names(home)
    ok("session_index 坏行跳过仍解析出条目", names.get("t-none") == "索引里的名字")

    res = codexhistory.list_threads()
    ok("list_threads 成功", res["ok"])
    by = {t["id"]: t["title"] for t in res["threads"]}
    ok("title 优先", by.get("t-title") == "显式标题")
    ok("name 回退", by.get("t-name") == "回退到 name")
    ok("preview 回退且压掉多余空白", by.get("t-preview") == "回退到 preview")
    ok("first_user_message 回退",
       by.get("t-first") == "回退到 first_user_message")
    ok("session_index 兜底", by.get("t-none") == "索引里的名字")
    ok("rollout 缺失时 missing=True",
       all(t["missing"] for t in res["threads"]))

    section("8. codexhistory：列表过滤")
    home = new_home()
    db = make_state_db(home)
    r1 = write_rollout(home, "sessions", "a1")
    r2 = write_rollout(home, "sessions", "a2", ts="2026-08-29T11-00-00")
    add_thread(db, "a1", rollout=r1, archived=0, title="关于 Python 的讨论",
               updated=1700000001)
    add_thread(db, "a2", rollout=r2, archived=1, title="关于 Rust 的讨论",
               updated=1700000002)
    all_t = codexhistory.list_threads()
    act = codexhistory.list_threads(only_archived=False)
    arc = codexhistory.list_threads(only_archived=True)
    ok(f"全部 {all_t['total']} 条", all_t["total"] == 2)
    ok("仅活跃 1 条且是 a1",
       act["total"] == 1 and act["threads"][0]["id"] == "a1")
    ok("仅归档 1 条且是 a2",
       arc["total"] == 1 and arc["threads"][0]["id"] == "a2")
    ok("按 updated_at 倒序（归档在前）",
       all_t["threads"][0]["id"] == "a2")
    ok("关键字命中标题",
       [t["id"] for t in codexhistory.list_threads(keyword="python")["threads"]]
       == ["a1"])
    ok("关键字命中 id",
       codexhistory.list_threads(keyword="a2")["total"] == 1)
    ok("rollout 存在时 rollout_exists=True 且给出大小",
       act["threads"][0]["rollout_exists"] and act["threads"][0]["rollout_size"] > 0)
    ok("rollout 展示为相对形式",
       act["threads"][0]["rollout"].startswith("sessions"))
    st = codexhistory.stats()
    ok(f"stats：总 {st['total']} / 归档 {st['archived']} / 活跃 {st['active']}",
       st["total"] == 2 and st["archived"] == 1 and st["active"] == 1)
    ok(f"stats 未命中缺失 {st['missing']}，统计到 {st['size']} 字节",
       st["missing"] == 0 and st["size"] > 0)

    section("9. codexhistory：备份")
    home = new_home()
    db = make_state_db(home)
    (home / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
    (home / "state_5.sqlite-wal").write_bytes(b"wal")
    bak = codexhistory.backup_databases(home, "archive")
    ok("备份目录已创建", bak is not None and bak.is_dir())
    ok("备份了 state_5.sqlite", bak and (bak / "state_5.sqlite").is_file())
    ok("备份了 config.toml", bak and (bak / "config.toml").is_file())
    ok("-wal 副产物一并带走（否则单独拷主库读不到最新内容）",
       bak and (bak / "state_5.sqlite-wal").is_file())
    ok("备份目录位于 backups_state/codexhelper 之下",
       bak and "backups_state" in str(bak) and "codexhelper" in str(bak))
    lst = codexhistory.list_backups()
    ok(f"list_backups 能列出（{len(lst)} 项）", len(lst) >= 1 and lst[0]["size"] >= 0)

    section("10. codexhistory：归档 / 恢复（含 Bug 3 回归）")
    home = new_home()
    db = make_state_db(home)
    roll = write_rollout(home, "sessions", "b1")
    add_thread(db, "b1", rollout=roll, archived=0)
    w = FakeWorker()
    res = codexhistory.set_archived(w, ["b1"], True)
    ok("归档成功", res["ok"] and res["changed"] == 1)
    ok(f"rollout 已移动（moved={res['moved']}）", res["moved"] == 1)
    ok("原 sessions 下文件已不在", not roll.exists())
    moved = home / "archived_sessions" / "2026" / "08" / "29" / roll.name
    ok("新位置符合日期分层", moved.is_file())
    con = sqlite3.connect(str(db))
    row = con.execute(
        "select archived, archived_at, rollout_path from threads where id='b1'"
    ).fetchone()
    con.close()
    ok("DB archived=1 且写入 archived_at", row[0] == 1 and row[1])
    # Bug 3 回归：相对部分若带前导反斜杠，Windows 会把文件移到盘符根
    ok("DB rollout_path 已更新到 archived_sessions",
       "archived_sessions" in (row[2] or ""))
    ok("【Bug 3 回归】rollout 未泄漏到盘符根（仍在本 home 内）",
       str(moved).lower().startswith(str(home).lower()))
    ok("【Bug 3 回归】盘符根没有残留 rollout 目录",
       not Path("C:\\2026").exists())

    res = codexhistory.set_archived(w, ["b1"], False)
    ok("恢复成功", res["ok"] and res["changed"] == 1)
    back = home / "sessions" / "2026" / "08" / "29" / roll.name
    ok("文件已移回 sessions", back.is_file())
    con = sqlite3.connect(str(db))
    row = con.execute("select archived, archived_at from threads where id='b1'"
                      ).fetchone()
    con.close()
    ok("DB archived=0 且 archived_at 清空", row[0] == 0 and row[1] is None)
    again = codexhistory.set_archived(w, ["b1"], False)
    ok("重复恢复：已是目标状态则跳过", again["ok"] and again["changed"] == 0)
    ok("不存在的 id 计入 failed",
       codexhistory.set_archived(w, ["nope"], True)["failed"])
    ok("空 id 列表直接报错",
       codexhistory.set_archived(w, [], True)["error"] == "未选择会话")

    section("11. codexhistory：删除（连带投影与索引）")
    home = new_home()
    db = make_state_db(home)
    hdb = make_history_db(home)
    roll = write_rollout(home, "sessions", "t1")
    add_thread(db, "t1", rollout=roll, archived=0)
    (home / "session_index.jsonl").write_text(
        _json({"id": "t1", "thread_name": "待删"}) + "\n"
        + _json({"id": "keep", "thread_name": "保留"}) + "\n", encoding="utf-8")
    w = FakeWorker()
    res = codexhistory.delete_threads(w, ["t1"])
    ok("删除成功", res["ok"] and res["removed_db"] == 1)
    ok(f"rollout 文件已删（file={res['removed_file']}）",
       res["removed_file"] == 1 and not roll.exists())
    con = sqlite3.connect(str(db))
    ok("DB 记录已删",
       con.execute("select count(*) from threads").fetchone()[0] == 0)
    con.close()
    con = sqlite3.connect(str(hdb))
    ok("thread_items 投影已清理",
       con.execute("select count(*) from thread_items").fetchone()[0] == 0)
    ok("thread_turns 投影已清理",
       con.execute("select count(*) from thread_turns").fetchone()[0] == 0)
    con.close()
    idx = (home / "session_index.jsonl").read_text(encoding="utf-8")
    ok("session_index 已剔除被删条目", "待删" not in idx and "保留" in idx)
    ok("删除前已备份", bool(res.get("backup")))

    section("12. codexhistory：从另一个 Codex profile 导入")
    home = new_home()
    db = make_state_db(home)
    src = SANDBOX / "src_profile"
    (src / "sessions").mkdir(parents=True, exist_ok=True)
    (src / "archived_sessions").mkdir(parents=True, exist_ok=True)
    write_rollout(src, "sessions", "i1")
    write_rollout(src, "archived_sessions", "i2")
    (src / "sessions" / "2026" / "08" / "29" / "not-a-rollout.jsonl").write_text(
        _json({"type": "other"}) + "\n", encoding="utf-8")
    w = FakeWorker()
    res = codexhistory.import_codex_dir(w, str(src))
    ok(f"导入成功（imported={res.get('imported')}）",
       res["ok"] and res["imported"] == 2)
    ok("非 rollout 文件被跳过", res["skipped"] == 1)
    con = sqlite3.connect(str(db))
    rows = con.execute("select id, rollout_path from threads").fetchall()
    con.close()
    ok("两条记录入库", len(rows) == 2)
    ok("导入的 rollout 落在新 home 下",
       all(str(p).lower().startswith(str(home).lower()) for _, p in rows))
    ok("导入的 rollout 文件真实存在",
       all(Path(p).is_file() for _, p in rows))
    ok("归档目录里的也会被导入",
       any("sessions" in p for _, p in rows))
    res2 = codexhistory.import_codex_dir(w, str(src))
    ok(f"重复导入全部跳过（skipped={res2.get('skipped')}）",
       res2["ok"] and res2["imported"] == 0)
    ok("源目录不存在时报错",
       not codexhistory.import_codex_dir(
           w, str(SANDBOX / "nope"))["ok"])

    section("13. codexhistory：Claude Code 转换导入")
    home = new_home()
    db = make_state_db(home)
    csrc = SANDBOX / "claude" / "projects"
    csrc.mkdir(parents=True, exist_ok=True)
    line_user = {
        "type": "user", "sessionId": "sess-1", "cwd": "C:\\work",
        "timestamp": "2026-08-01T10:00:00Z", "uuid": "u1",
        "message": {"content": [
            {"type": "text",
             "text": "<command-name>ls</command-name>\n请帮我看下这个报错"},
            {"type": "tool_result", "content": "x"},
        ]}}
    line_asst = {
        "type": "assistant", "sessionId": "sess-1",
        "timestamp": "2026-08-01T10:00:05Z", "uuid": "u2",
        "message": {"content": "这是回复"}}
    line_tool = {
        "type": "assistant", "sessionId": "sess-1", "uuid": "u3",
        "message": {"content": [{"type": "tool_use", "name": "Read"}]}}
    f = csrc / "sess-1.jsonl"
    f.write_text("\n".join(_json(x) for x in
                           (line_user, line_asst, line_tool)) + "\n坏行\n",
                 encoding="utf-8")
    txt = codexhistory._claude_text(line_user["message"])
    ok("剥掉 Claude 注入的命令块", "<command-name>" not in txt)
    ok("保留真实提问文本", "请帮我看下这个报错" in txt)
    ok("工具结果转为占位", "[工具结果]" in txt)
    ok("字符串型 content 也能取文本",
       codexhistory._claude_text({"content": "纯文本"}) == "纯文本")
    ok("工具调用转占位",
       "[工具调用 Read]" in codexhistory._claude_text(line_tool["message"]))

    w = FakeWorker()
    res = codexhistory.import_claude_code(w, str(csrc))
    ok(f"导入成功（imported={res.get('imported')}）",
       res["ok"] and res["imported"] == 1)
    con = sqlite3.connect(str(db))
    row = con.execute(
        "select id, rollout_path, title, thread_source, cwd from threads"
    ).fetchone()
    con.close()
    ok("入库一条且 thread_source=import", row and row[3] == "import")
    ok("cwd 从 Claude 会话继承", row and row[4] == "C:\\work")
    ok(f"标题取自真实提问（{row[2][:20] if row and row[2] else ''}）",
       row and "请帮我看下这个报错" in (row[2] or ""))
    rp = Path(row[1])
    ok("生成的 rollout 存在", rp.is_file())
    ok("【往返一致】生成的 rollout 能被 Codex 解析器读出",
       (codexhistory._parse_rollout_meta(rp) or {}).get("id") == row[0])
    body = rp.read_text(encoding="utf-8").splitlines()
    ok("首行是 session_meta", '"session_meta"' in body[0])
    ok("user 消息写成 event_msg + response_item 两行",
       any('"user_message"' in b for b in body)
       and any('"input_text"' in b for b in body))
    ok("assistant 消息写成 output_text",
       any('"output_text"' in b for b in body))
    ok("scan_import_sources 不崩且含 Claude 来源",
       any(s["kind"] == "claude" for s in codexhistory.scan_import_sources()))
    ok("空目录导入报错",
       not codexhistory.import_claude_code(w, str(SANDBOX / "empty"))["ok"])

    section("14. codexhistory：目标路径日期分层")
    home = new_home()
    d = codexhistory._dest_rollout(home, "tid", "2026-08-29T10:00:00Z")
    ok("按 timestamp 分层到 YYYY/MM/DD",
       d == home / "sessions" / "2026" / "08" / "29" / "rollout-2026-08-29T10-00-00-tid.jsonl")
    d2 = codexhistory._dest_rollout(home, "tid2", None)
    ok("无 timestamp 时落到今天",
       d2.parent.parts[-3:] == (f"{time.localtime().tm_year:04d}",
                                f"{time.localtime().tm_mon:02d}",
                                f"{time.localtime().tm_mday:02d}"))

    # ============================================================= codexlogs ==
    section("15. codexlogs：时间戳格式化")
    ok("秒级时间戳可格式化",
       re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                codexlogs._fmt_ts(1700000000)) is not None)
    ok("毫秒级时间戳自动归一",
       codexlogs._fmt_ts(1700000000000) == codexlogs._fmt_ts(1700000000))
    ok("None → 空串", codexlogs._fmt_ts(None) == "")
    ok("0 / 负数 → 空串",
       codexlogs._fmt_ts(0) == "" and codexlogs._fmt_ts(-1) == "")
    ok("非数字 → 原样返回", codexlogs._fmt_ts("abc") == "abc")

    section("16. codexlogs：级别过滤下推（Bug 4 回归）")
    home = new_home()
    ldb = make_logs_db(home)
    # ERROR 集中在最早（id 小），后面紧跟 1000 条 INFO。
    # 旧实现"先按 id desc 取 200 条再在应用层过滤"会一条 ERROR 都拿不到。
    base = 1700000000
    for i in range(1, 17):
        add_log(ldb, i, base + i, "ERROR", f"boom-{i}", tid="T-err")
    for i in range(17, 1017):
        add_log(ldb, i, base + i, "INFO", "noise", tid="T-info")
    r = codexlogs.query_logs(levels=["ERROR"], limit=200)
    ok("查询成功", r["ok"])
    ok(f"【Bug 4 回归】早期 ERROR 全被查到（{len(r['rows'])}/16）",
       len(r["rows"]) == 16)
    ok("返回结果全是 ERROR",
       all(x["level"] == "ERROR" for x in r["rows"]))
    ok("级别大小写不敏感",
       codexlogs.query_logs(levels=["error"], limit=500)["rows"]
       and len(codexlogs.query_logs(levels=["error"], limit=500)["rows"]) == 16)
    ok("按 id 倒序（最新在前）",
       r["rows"][0]["id"] > r["rows"][-1]["id"])
    ok("不过滤级别时取满 200 条",
       len(codexlogs.query_logs(limit=200)["rows"]) == 200)
    ok("offset 生效",
       codexlogs.query_logs(levels=["ERROR"], limit=10, offset=10)["rows"][0]["id"] == 6)
    ok("has_more 在还有剩余时为 True",
       codexlogs.query_logs(levels=["ERROR"], limit=10)["has_more"])

    section("17. codexlogs：关键词 / 截断 / 上限")
    r = codexlogs.query_logs(keyword="boom-7", limit=500)
    ok(f"关键词命中（{len(r['rows'])} 条）",
       len(r["rows"]) == 1 and "boom-7" in r["rows"][0]["body"])
    ok("关键词不命中返回空",
       codexlogs.query_logs(keyword="zzz-not-exist", limit=500)["rows"] == [])
    ok("thread_id 过滤生效",
       all(x["thread_id"] == "T-err"
           for x in codexlogs.query_logs(thread_id="T-err", limit=50)["rows"]))
    add_log(ldb, 9999, base + 9999, "WARN", "x" * 5000)
    r = codexlogs.query_logs(levels=["WARN"], limit=10)
    ok("超长正文被截断到 2000", len(r["rows"][0]["body"]) == 2000)
    ok("truncated 标记为 True", r["rows"][0]["truncated"])
    ok("limit 被钳制到 MAX_ROWS（2000）",
       codexlogs.query_logs(limit=999999)["limit"] == codexlogs.MAX_ROWS)
    # 固化现有钳制语义：0 等同"未指定"（回落 200），负数被钳到最小 1。
    ok("limit=0 视为未指定 → 回落默认 200",
       codexlogs.query_logs(limit=0)["limit"] == 200)
    ok("limit 为负 → 钳到最小 1",
       codexlogs.query_logs(limit=-5)["limit"] == 1)
    ok("返回的字段齐全",
       set(("id", "ts", "level", "body", "target", "module", "file",
            "line", "thread_id", "truncated")).issubset(r["rows"][0]))

    section("18. codexlogs：概览与导出")
    s = codexlogs.summary()
    ok(f"总数正确（{s.get('total')}）", s["ok"] and s["total"] == 1017)
    ok("级别分布包含 ERROR/INFO/WARN",
       s["levels"].get("ERROR") == 16 and s["levels"].get("INFO") == 1000
       and s["levels"].get("WARN") == 1)
    ok("时间范围已给出", bool(s.get("min_ts")) and bool(s.get("max_ts")))
    ok(f"去重会话数正确（{s.get('threads')}，WARN 那条 thread_id 为空不计入）",
       s["threads"] == 2)
    ok("库体积已给出", s["size"] > 0)

    dest = TMP_ROOT / "export-logs.txt"
    if dest.exists():
        dest.unlink()
    exp = codexlogs.export_logs(str(dest), levels=["ERROR"], limit=100)
    ok("导出成功", exp["ok"] and exp["count"] == 16)
    ok("导出文件已生成", dest.is_file())
    txt = dest.read_text(encoding="utf-8")
    ok("导出内容含级别与正文", "ERROR" in txt and "boom-1" in txt)
    ok("导出含文件头", txt.startswith("# Codex 日志导出"))
    dest.unlink(missing_ok=True)

    section("19. codexlogs / codexhistory：无数据时的容错")
    empty = SANDBOX / "empty_home"
    empty.mkdir(parents=True, exist_ok=True)
    codexpaths.resolve_codex_home = lambda *a, **k: empty
    ok("无 state 库时 list_threads 报错而非崩溃",
       codexhistory.list_threads()["ok"] is False)
    ok("无 logs 库时 query_logs 报错而非崩溃",
       codexlogs.query_logs()["ok"] is False)
    ok("无 logs 库时 summary 报错而非崩溃",
       codexlogs.summary()["ok"] is False)
    codexpaths.resolve_codex_home = lambda *a, **k: None
    ok("定位不到 CODEX_HOME 时 list_threads 明确报错",
       codexhistory.list_threads()["error"] == "未能定位 CODEX_HOME")
    ok("定位不到 CODEX_HOME 时 query_logs 明确报错",
       codexlogs.query_logs()["ok"] is False)
    ok("定位不到 CODEX_HOME 时 relocate_rollout 返回 None",
       codexpaths.relocate_rollout("C:\\x\\.codex\\sessions\\2026\\08\\29\\a.jsonl")
       is None)

    # ---------------------------------------------------------------- 汇总 --
    print()
    if all(_results):
        print(f"全部 {len(_results)} 项测试通过")
        _code = 0
    else:
        print(f"有 {len(_bad)} 项失败")
        for b in _bad:
            print("   - " + b)
        _code = 1
except Exception:
    import traceback
    traceback.print_exc()
    _code = 1
finally:
    shutil.rmtree(SANDBOX, ignore_errors=True)
    print(f"\n沙箱已清理：{SANDBOX}")

raise SystemExit(_code)
