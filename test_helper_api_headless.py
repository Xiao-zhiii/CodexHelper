# -*- coding: utf-8 -*-
"""helper 诊断接口与持久化日志的回归测试。

验证目标：
1. 日志写到 ``%LOCALAPPDATA%\\CodexHelper\\Codex Helper.log``（而非临时目录）。
2. /api/helper-status 聚合所有关键状态。
3. /api/helper-tasks / helper-task-log 能查看任务历史与日志。
4. /api/helper-log?format=structured 返回结构化日志。
5. /api/helper-client-errors 能读取前端异常日志。
6. 任务日志同时落到 tasks/<job_id>.log。
"""
import json
import socket
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, Path(__file__).resolve().parent.as_posix())

from codexhelper import logs  # noqa: E402
from codexhelper.webui.server import CHServer, RequestHandler  # noqa: E402


_results = []
_bad = []


def ok(name, cond):
    cond = bool(cond)
    _results.append(cond)
    if not cond:
        _bad.append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def section(t):
    print(f"== {t} ==")


def get(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode("utf-8")


def post(url, data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")


# 找一个临时端口
def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


try:
    # ---- 1. 日志路径 ----
    section("1. 日志持久化位置")
    log_path = logs.get_log_path()
    ok("日志目录在 %LOCALAPPDATA%\\CodexHelper",
       "CodexHelper" in str(log_path))
    # 触发一条日志，确保文件已创建
    logs.write("INFO", "helper api test boot", test_marker=True)
    ok("日志文件已生成", log_path.is_file())
    ok("日志文件非空", log_path.stat().st_size > 0)

    # ---- 2. 启动服务 ----
    section("2. helper 接口")
    port = free_port()
    server = CHServer(("127.0.0.1", port), RequestHandler)
    server.url = f"http://127.0.0.1:{port}/"
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    base = f"http://127.0.0.1:{port}"
    ok("/api/ping 通", "ok" in get(base + "/api/ping"))

    status = json.loads(get(base + "/api/helper-status"))
    ok("/api/helper-status ok", status.get("ok"))
    for key in ("app", "version", "vendor", "pid", "port", "admin",
                "boot_time", "uptime_sec", "codex_home", "detect",
                "logs", "recent_tasks"):
        ok(f"helper-status 含 {key}", key in status)
    ok("port 与实际端口一致", status.get("port") == port)
    ok("logs.main.path 指向 Codex Helper.log",
       "Codex Helper.log" in str(status["logs"]["main"]["path"]))

    # 启动一个快速任务（未知 action，立即失败结束）
    r = post(base + "/api/task", {"action": "__unknown_test__"})
    job = json.loads(r)
    ok("任务创建成功", job.get("ok") and job.get("id"))
    job_id = job["id"]
    time.sleep(0.3)

    tasks = json.loads(get(base + "/api/helper-tasks"))
    ok("/api/helper-tasks ok", tasks.get("ok"))
    ids = [t["id"] for t in tasks.get("tasks", [])]
    ok("helper-tasks 包含刚创建的任务", job_id in ids)
    task_info = next((t for t in tasks["tasks"] if t["id"] == job_id), None)
    ok("任务摘要含 status/action/summary",
       task_info and "status" in task_info and "action" in task_info)

    tlog = json.loads(get(base + f"/api/helper-task-log?id={job_id}"))
    ok("/api/helper-task-log ok", tlog.get("ok"))
    ok("任务日志文件已生成", len(tlog.get("rows", [])) >= 1)

    # 结构化 helper-log
    slog = json.loads(get(base + "/api/helper-log?format=structured&lines=50"))
    ok("/api/helper-log structured ok", slog.get("ok"))
    ok("返回 rows 列表", isinstance(slog.get("rows"), list))
    ok("rows 含结构化字段",
       all("message" in r and "level" in r for r in slog.get("rows", [])))
    ok("能按 keyword 过滤",
       json.loads(get(base + "/api/helper-log?format=structured&lines=50&keyword=helper")).get("ok"))
    ok("能按 level 过滤",
       json.loads(get(base + "/api/helper-log?format=structured&lines=50&level=INFO")).get("ok"))

    # 模拟一个客户端错误
    post(base + "/api/client-error", {
        "message": "test client error", "kind": "onerror",
        "source": "test.js", "line": 10, "stack": "at test"})
    time.sleep(0.1)
    cerr = json.loads(get(base + "/api/helper-client-errors?lines=50"))
    ok("/api/helper-client-errors ok", cerr.get("ok"))
    ok("client-errors.log 能读到刚上报的异常",
       any("test client error" in str(r.get("message", ""))
           for r in cerr.get("rows", [])))

    server.shutdown()
    server.server_close()

    # ---- 3. 任务日志持久化 ----
    section("3. 任务日志文件")
    task_file = logs.ensure_task_log(job_id)
    ok("任务日志路径位于 %LOCALAPPDATA%\\CodexHelper\\tasks",
       "CodexHelper" in str(task_file) and "tasks" in str(task_file))
    ok("任务日志文件存在", task_file.is_file())
    txt = task_file.read_text(encoding="utf-8", errors="replace")
    ok("任务日志含至少一条记录", bool(txt.strip()))

    # ---- 4. 日志轮转配置 ----
    section("4. 日志轮转")
    ok("maxBytes = 10 MB", logs.MAX_BYTES == 10 * 1024 * 1024)
    ok("backupCount = 5", logs.BACKUP_COUNT == 5)

    print()
    if all(_results):
        print(f"全部 {len(_results)} 项测试通过")
        code = 0
    else:
        print(f"有 {len(_bad)} 项失败")
        for b in _bad:
            print("   - " + b)
        code = 1
except Exception:
    import traceback
    traceback.print_exc()
    code = 1

raise SystemExit(code)
