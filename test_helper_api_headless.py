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

# 导入 server 模块会立刻把「本进程」的令牌写进 token.txt，盖掉用户正在运行的
# 那一个实例留下的值。先备份，§2b 断言完再还原，别影响用户手上的实例。
_TOKEN_FILE = logs.LOG_DIR / "token.txt"
_TOKEN_FILE_BACKUP = (_TOKEN_FILE.read_text(encoding="utf-8", errors="replace")
                      if _TOKEN_FILE.is_file() else None)

from codexhelper.webui import server as webui_server  # noqa: E402
from codexhelper.webui.server import CHServer, RequestHandler  # noqa: E402


_results = []
_bad = []

# 除 /、/favicon.ico、/api/ping 外，所有 /api/* 都要带 X-CH-Token。
# 测试客户端也得带上，否则一律 401——这本身就是本文件要守住的行为。
_TOKEN = webui_server.get_api_token()


def ok(name, cond):
    cond = bool(cond)
    _results.append(cond)
    if not cond:
        _bad.append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def section(t):
    print(f"== {t} ==")


def raw_get(url, token=True):
    """返回 (状态码, 响应体)；token=False 表示不带头，用于验证鉴权。"""
    headers = {}
    if token is not False:
        headers["X-CH-Token"] = token if isinstance(token, str) else _TOKEN
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def get(url, token=True):
    code, body = raw_get(url, token)
    if code != 200:
        raise AssertionError(f"GET {url} 返回 {code}：{body[:200]}")
    return body


def post(url, data, token=True):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token is not False:
        headers["X-CH-Token"] = token if isinstance(token, str) else _TOKEN
    req = urllib.request.Request(url, data=body, headers=headers)
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

    # ---- 2b. API 鉴权 ----
    # 端口写在 %LOCALAPPDATA%\CodexHelper\port.txt，本机任意进程都能直达端点，
    # 其中 shutdown / repair / 删会话 / 装依赖都是危险写操作，必须卡住。
    section("2b. API 鉴权")
    ok("/api/ping 免鉴权（单实例检测依赖它）",
       raw_get(base + "/api/ping", token=False)[0] == 200)
    code, _ = raw_get(base + "/api/helper-status", token=False)
    ok("不带令牌 → 401", code == 401)
    code, _ = raw_get(base + "/api/helper-status", token="wrong-token-value")
    ok("错误令牌 → 401", code == 401)
    code, _ = raw_get(base + "/api/helper-status")
    ok("正确令牌 → 200", code == 200)
    # 危险写操作同样要拦（这里只验证拦截，不真的执行）
    code, _ = raw_get(base + "/api/codex-threads?limit=1", token=False)
    ok("删/读会话端点不带令牌 → 401", code == 401)

    # 令牌落盘（交接文档 §12.13.3 选 a）：不落盘的话 §七 那套外部排查命令
    # 全部 401，"AI 友好"就是空话。这里守住"落了盘、且能用"。
    ok("令牌文件路径在 %LOCALAPPDATA%\\CodexHelper\\token.txt",
       "CodexHelper" in str(webui_server.TOKEN_FILE)
       and webui_server.TOKEN_FILE.name == "token.txt")
    ok("令牌文件已生成", webui_server.TOKEN_FILE.is_file())
    disk_token = webui_server.TOKEN_FILE.read_text(encoding="utf-8").strip()
    ok("令牌文件内容与进程令牌一致", disk_token == _TOKEN)
    ok("令牌不含空白字符（便于命令行读取）",
       bool(disk_token) and not any(c.isspace() for c in disk_token))
    code, _ = raw_get(base + "/api/helper-status", token=disk_token)
    ok("用令牌文件里的令牌能调通受保护端点", code == 200)
    # 还原用户实例留下的令牌（备份见文件头）
    if _TOKEN_FILE_BACKUP is not None:
        _TOKEN_FILE.write_text(_TOKEN_FILE_BACKUP, encoding="utf-8")

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
