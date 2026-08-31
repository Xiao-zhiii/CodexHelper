# -*- coding: utf-8 -*-
"""Codex 小帮手 本地 Web 服务（v1.6.0）。

路由：
    GET  /                    页面（page.get_page）
    GET  /api/ping            心跳（沿用收编项目约定，浏览器关闭后空闲自动退出）
    GET  /api/snapshot        配置中心快照（收编后端 build_snapshot）
    GET  /api/state           版本/权限/检测结果缓存
    GET  /api/appx            当前 OpenAI.Codex 桌面端版本
    GET  /api/task?id=        任务状态/日志/进度
    POST /api/task            启动后台任务 {action, params}
    POST /api/cancel          取消任务 {id}
    POST /api/relaunch-admin  以管理员身份重启（UAC）
    POST /api/test-provider | /api/test-all-providers | /api/repair-codex
    POST /api/shutdown        退出
任务在后台线程运行（复用 installer.Installer 的队列协议），前端轮询 /api/task。
同一时刻只允许一个任务（与原 tkinter 行为一致）。
"""
import json
import os
import queue
import threading
import time

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import cfgcenter, page
from .. import codexhistory, codexlogs, codexpaths, logs
from .. import deps as codexhelper_deps
from ..constants import APP_TITLE, APP_VENDOR, APP_VERSION
from ..gpt_fix import find_codex_desktop
from ..installer import Installer
from ..netenv import detect_proxy
from ..util import is_admin, relaunch_as_admin

SERVER_BRAND = "CodexHelper/1.6"

# ------------------------------------------------------------- 任务系统 ----

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_JOB_SEQ = 0
_CONFLICT = [None]   # 最近一次 409 时正在运行的任务 id（调试用）
_PUSHER = [None]     # 界面推送函数（webview 模式由 launcher 注入；浏览器模式为 None）


def set_pusher(fn):
    """注入 UI 推送函数：fn(job_dict_to_dict)。webview 模式下由 launcher 传入
    (基于 evaluate_js)，浏览器模式保持 None（前端轮询兜底）。"""
    _PUSHER[0] = fn


def _push_loop(job):
    """每秒把任务状态推给界面；结束后推一次最终状态。"""
    while job.status == "running":
        fn = _PUSHER[0]
        if fn:
            try:
                fn(job.to_dict())
            except Exception:
                pass
        time.sleep(1)
    fn = _PUSHER[0]
    if fn:
        try:
            fn(job.to_dict())
        except Exception:
            pass
_LAST_RELEASES: list | None = None
_LAST_APPX = [None]   # [0] = 最近一次探测的 OpenAI.Codex 包信息
_LAST_DETECT: dict | None = None


class _Job:
    def __init__(self, job_id: str, action: str, worker: Installer):
        self.id = job_id
        self.action = action
        self.worker = worker
        self.status = "running"
        self.ok = False
        self.summary = ""
        self.logs: list[dict] = []
        self.progress: float | None = None
        self.status_text = ""
        self.result: dict = {}
        self.created = time.time()

    def to_dict(self, tail: int = 400) -> dict:
        return {"id": self.id, "action": self.action, "status": self.status,
                "ok": self.ok, "summary": self.summary,
                "logs": self.logs[-tail:], "progress": self.progress,
                "statusText": self.status_text, "result": self.result}


def _pump(job: _Job, q: queue.Queue):
    """把 Installer 的队列消息搬进任务对象（后台线程）。"""
    global _LAST_RELEASES, _LAST_DETECT
    while True:
        try:
            msg = q.get(timeout=0.2)
        except queue.Empty:
            if job.status != "running":
                return
            continue
        kind = msg[0]
        if kind == "log":
            _, tag, text = msg
            entry = {"tag": tag, "text": str(text),
                     "t": time.strftime("%H:%M:%S")}
            job.logs.append(entry)
            # 同时持久化到任务专属日志，方便 AI/用户事后查看完整过程
            logs.write_task_log(job.id, tag, text)
        elif kind == "status":
            job.status_text = msg[1]
            # status 也落任务日志，确保 detect 这种不发 log 的任务也有迹可循
            logs.write_task_log(job.id, "status", msg[1])
        elif kind == "progress":
            job.progress = None if msg[1] is None else max(0.0, min(1.0, msg[1]))
        elif kind == "done":
            _, ok, summary = msg
            job.ok, job.summary, job.status = bool(ok), summary, "done"
            logs.write_task_log(job.id, "done",
                                f"{'完成' if ok else '失败'}：{summary}")
        elif kind == "info":
            job.result["info"] = msg[1]
            _LAST_DETECT = {"info": msg[1], "gpt": job.result.get("gpt") or {}}
        elif kind == "gpt_info":
            job.result["gpt"] = msg[1]
            if _LAST_DETECT:
                _LAST_DETECT["gpt"] = msg[1]
        elif kind == "mirror_list":
            job.result["releases"] = msg[1]
            _LAST_RELEASES = msg[1]
        elif kind == "appx_info":
            job.result["appx"] = msg[1]
        elif kind == "env_report":
            job.result["report"] = msg[1]
        # fix_manual 等 UI 弹窗类消息：转成日志行
        elif kind == "fix_manual":
            job.logs.append({"tag": "warn", "text": "未能自动键入修复指令：请到 Codex 窗口"
                             "【鼠标右键】粘贴提示词并回车（勿按 Ctrl+V）。", "t": ""})
            logs.write_task_log(job.id, "warn", job.logs[-1]["text"])


def start_job(action: str, params: dict) -> tuple[str | None, str]:
    """启动任务；同一时刻仅允许一个。返回 (job_id, 错误信息)。"""
    global _JOB_SEQ
    with _JOBS_LOCK:
        running = [j for j in _JOBS.values() if j.status == "running"]
        if running:
            _CONFLICT[0] = running[0].id
            return None, "已有任务在运行：" + running[0].action
        _JOB_SEQ += 1
        job_id = f"j{int(time.time())}_{_JOB_SEQ}"
        q: queue.Queue = queue.Queue()
        worker = Installer(q)
        worker.cancel.clear()
        job = _Job(job_id, action, worker)
        _JOBS[job_id] = job

    target = _ACTION_TARGETS.get(action)
    if target is None:
        # 未知 action 也走完整队列流程，确保任务日志/状态一致，便于 AI 排查
        q.put(("log", "warn", f"未知任务类型：{action}"))
        q.put(("done", False, f"未知任务类型：{action}"))

    # 内存中最多保留 50 个已完成任务，避免长期运行后无限增长
    with _JOBS_LOCK:
        done_jobs = [j for j in _JOBS.values() if j.status != "running"]
        if len(done_jobs) > 50:
            done_jobs.sort(key=lambda j: j.created)
            for old in done_jobs[:len(done_jobs) - 50]:
                _JOBS.pop(old.id, None)

    def run():
        if target is None:
            return
        try:
            target(worker, job, params or {})
        except Exception as exc:  # noqa: BLE001 - 任务异常进日志
            worker.log("发生错误：" + str(exc), "err")
            q.put(("done", False, "失败：" + str(exc)))

    threading.Thread(target=run, daemon=True).start()
    threading.Thread(target=_pump, args=(job, q), daemon=True).start()
    threading.Thread(target=_push_loop, args=(job,), daemon=True).start()
    return job_id, ""


def cancel_job(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if job and job.status == "running":
        job.worker.cancel.set()
        return True
    return False


# ------------------------------------------------------------ 任务实现 ----

def _t_detect(worker: Installer, job: _Job, params: dict):
    from ..util import detect
    worker.status("正在检测本机环境…")
    info = detect()
    # 先发 info：页面立刻渲染主徽章（gpt 检测的 PowerShell 冷启动可能很慢，
    # 不能让它拖住整个界面的首次反馈）
    worker.q.put(("info", info))
    worker.status("正在检测 ChatGPT 桌面端（可能较慢）…")
    gpt = detect_gpt_env_safe()
    worker.q.put(("gpt_info", gpt))
    worker.q.put(("done", True, "检测完成"))


def detect_gpt_env_safe():
    from ..gpt_fix import detect_gpt_env
    return detect_gpt_env()


def _t_install(worker: Installer, job: _Job, params: dict):
    worker.run(bool(params.get("node")), bool(params.get("codex")))


def _t_fix_plugin(worker: Installer, job: _Job, params: dict):
    worker.run_fix()


def _t_fix_gpt(worker: Installer, job: _Job, params: dict):
    worker.run_fix_gpt(restart=True)


def _t_fetch_mirror(worker: Installer, job: _Job, params: dict):
    worker.run_fetch_mirror()


def _t_install_msix(worker: Installer, job: _Job, params: dict):
    index = int(params.get("index", -1))
    if _LAST_RELEASES is None or not (0 <= index < len(_LAST_RELEASES)):
        worker.log("所选版本无效，请先获取镜像版本列表。", "warn")
        worker.q.put(("done", False, "未选择有效版本"))
        return
    worker.run_appx_install(_LAST_RELEASES[index])


def _t_env_scan(worker: Installer, job: _Job, params: dict):
    worker.run_env_scan()


# --------------------------------------------- Codex 历史 / 日志（v1.7.0）--

def _ids(params: dict) -> list[str]:
    raw = params.get("ids")
    if isinstance(raw, str):
        raw = [raw]
    return [str(x).strip() for x in (raw or []) if str(x).strip()]


def _finish(worker: Installer, job: _Job, result: dict, ok_word: str):
    """统一收尾：结果进 job.result，日志与 done 入队列。"""
    job.result["history"] = result
    worker.q.put(("progress", None))
    if result.get("ok"):
        worker.q.put(("done", True, ok_word))
    else:
        worker.log("失败：" + str(result.get("error") or "未知错误"), "err")
        worker.q.put(("done", False, str(result.get("error") or "操作失败")))


def _t_archive(worker: Installer, job: _Job, params: dict):
    ids = _ids(params)
    if not ids:
        worker.q.put(("done", False, "未选择会话"))
        return
    _finish(worker, job, codexhistory.set_archived(worker, ids, True),
            f"已归档 {len(ids)} 个会话")


def _t_restore(worker: Installer, job: _Job, params: dict):
    ids = _ids(params)
    if not ids:
        worker.q.put(("done", False, "未选择会话"))
        return
    _finish(worker, job, codexhistory.set_archived(worker, ids, False),
            f"已恢复 {len(ids)} 个会话")


def _t_delete_threads(worker: Installer, job: _Job, params: dict):
    ids = _ids(params)
    if not ids:
        worker.q.put(("done", False, "未选择会话"))
        return
    _finish(worker, job, codexhistory.delete_threads(worker, ids),
            f"已删除 {len(ids)} 个会话")


def _t_import_claude(worker: Installer, job: _Job, params: dict):
    _finish(worker, job,
            codexhistory.import_claude_code(worker, params.get("src") or ""),
            "Claude Code 会话导入完成")


def _t_import_codex(worker: Installer, job: _Job, params: dict):
    src = (params.get("src") or "").strip()
    if not src:
        worker.q.put(("done", False, "未选择源目录"))
        return
    _finish(worker, job, codexhistory.import_codex_dir(worker, src),
            "Codex 会话导入完成")


def _t_export_logs(worker: Installer, job: _Job, params: dict):
    res = codexlogs.export_logs(
        params.get("dest") or "",
        levels=params.get("levels") or None,
        keyword=params.get("keyword") or "",
        limit=int(params.get("limit") or 5000))
    _finish(worker, job, res, "日志导出完成")


# ------------------------------------------------------- 运行时依赖任务 ----

def _t_deps_scan(worker: Installer, job: _Job, params: dict):
    """扫描运行时依赖（WebView2 / Python Manager / VC++）。"""
    force = bool(params.get("force"))
    if force:
        codexhelper_deps.invalidate_cache()
    res = codexhelper_deps.scan(force=force)
    worker.log(f"扫描完成：缺失 {len(res['missing'])} 项", "info")
    _finish(worker, job, res,
            "环境依赖全部就绪" if res["all_ok"] else "有依赖缺失")


def _t_deps_install(worker: Installer, job: _Job, params: dict):
    """安装运行时依赖。可传单个 id，或 ids 列表批量装。"""
    ids = params.get("ids")
    if not ids:
        one = params.get("dep")
        ids = [one] if one else []
    if not ids:
        worker.q.put(("done", False, "未指定要安装的依赖"))
        return

    results = []
    for i, dep_id in enumerate(ids, 1):
        if worker.check_cancel():
            worker.q.put(("done", False, "已取消"))
            return
        worker.status(f"正在安装第 {i}/{len(ids)} 项：{dep_id}")
        r = codexhelper_deps.install_dep(dep_id)
        results.append(r)
        worker.log(f"{dep_id}：{r.get('message')}",
                   "ok" if r.get("ok") else "err")

    failed = [r["dep"] for r in results if not r.get("ok")]
    codexhelper_deps.invalidate_cache()
    # 装完重新扫一次，前端直接拿最新状态渲染，省一次往返
    res = {
        "results": results,
        "failed": failed,
        "scan": codexhelper_deps.scan(force=True),
    }
    _finish(worker, job, bool(results) and not failed,
            "依赖安装完成" if not failed else f"{len(failed)} 项安装失败")
    job.result["deps"] = res


_ACTION_TARGETS = {
    "detect": _t_detect,
    "deps_scan": _t_deps_scan,
    "deps_install": _t_deps_install,
    "install_all": lambda w, j, p: _t_install(w, j, {"node": True, "codex": True}),
    "install_node": lambda w, j, p: _t_install(w, j, {"node": True, "codex": False}),
    "install_codex": lambda w, j, p: _t_install(w, j, {"node": False, "codex": True}),
    "fix_plugin": _t_fix_plugin,
    "fix_gpt": _t_fix_gpt,
    "fetch_mirror": _t_fetch_mirror,
    "install_msix": _t_install_msix,
    "env_scan": _t_env_scan,
    "archive_threads": _t_archive,
    "restore_threads": _t_restore,
    "delete_threads": _t_delete_threads,
    "import_claude": _t_import_claude,
    "import_codex": _t_import_codex,
    "export_logs": _t_export_logs,
}


# ------------------------------------------------------------ HTTP 服务 ----

class CHServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class):
        super().__init__(server_address, handler_class)
        self.last_seen = time.time()
        self.first_seen = None     # 浏览器首次请求时间（空闲退出从它起算）
        self.boot_time = time.time()
        self.pid = os.getpid()
        self.url = ""              # 启动器填入，供重试打开页面


class RequestHandler(BaseHTTPRequestHandler):
    server_version = SERVER_BRAND

    # ---- 工具 ----
    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def send_bytes(self, body: bytes, content_type: str,
                   status: HTTPStatus = HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        data = json.loads(self.rfile.read(length).decode("utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}

    def log_message(self, format, *args):  # noqa: A002
        # 临时访问日志（调试轮询问题；正式版可改回 return）
        try:
            with open(os.path.join(os.environ.get("TEMP", "."),
                                   "ch_access.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + (format % args)
                        + chr(10))
        except Exception:
            pass

    # ---- GET ----
    def do_GET(self):
        try:
            self.server.last_seen = time.time()
            if self.server.first_seen is None:
                self.server.first_seen = time.time()
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                html = page.get_page(APP_VERSION, APP_VENDOR, _homepage(),
                                     is_admin()).encode("utf-8")
                self.send_bytes(html, "text/html; charset=utf-8")
                return
            if parsed.path == "/favicon.ico":
                from ..util import res_path
                ico = res_path("codex_helper.ico")
                if ico:
                    with open(ico, "rb") as f:
                        self.send_bytes(f.read(), "image/x-icon")
                else:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            if parsed.path == "/api/ping":
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/snapshot":
                self.send_json(cfgcenter.build_snapshot(parse_qs(parsed.query)))
                return
            if parsed.path == "/api/state":
                # deps 一并下发：页面初始化原本就要拉 /api/state，
                # 合并进去省一次往返，前端首屏就能渲染依赖卡片。
                # 扫描有缓存（PowerShell 检测慢），不会拖慢首屏。
                try:
                    deps_state = codexhelper_deps.scan()
                except Exception as exc:  # noqa: BLE001
                    deps_state = {"ok": False, "error": str(exc),
                                  "items": [], "missing": []}
                self.send_json({
                    "app": APP_TITLE, "version": APP_VERSION, "vendor": APP_VENDOR,
                    "homepage": _homepage(), "is_admin": is_admin(),
                    "proxy": detect_proxy(),
                    "detect": _LAST_DETECT,
                    "push": _PUSHER[0] is not None,
                    "deps": deps_state,
                })
                return
            if parsed.path == "/api/appx":
                query = parse_qs(parsed.query)
                if query.get("refresh", ["0"])[0] == "1" or _LAST_APPX[0] is None:
                    pkg = find_codex_desktop(log=lambda *a, **k: None)
                    _LAST_APPX[0] = pkg
                pkg = _LAST_APPX[0]
                self.send_json({"pkg": pkg, "version": (pkg or {}).get("version")})
                return
            if parsed.path == "/api/task":
                job = _JOBS.get(parse_qs(parsed.query).get("id", [""])[0])
                if not job:
                    self.send_json({"ok": False, "errors": ["任务不存在"]},
                                   HTTPStatus.NOT_FOUND)
                    return
                self.send_json(job.to_dict())
                return
            # ---- 运行时依赖（v1.8.0）：WebView2 / Python Manager / VC++ ----
            if parsed.path == "/api/deps-scan":
                q = parse_qs(parsed.query)
                force = q.get("force", ["0"])[0] == "1"
                if force:
                    codexhelper_deps.invalidate_cache()
                self.send_json(codexhelper_deps.scan(force=force))
                return
            if parsed.path == "/api/deps-install":
                # POST 单个依赖；多个用 ids 数组
                body = self.read_json_body() or {}
                ids = body.get("ids") or (
                    [body["dep"]] if body.get("dep") else [])
                if not ids:
                    self.send_json({"ok": False, "error": "未指定依赖"},
                                   HTTPStatus.BAD_REQUEST)
                    return
                job_id, _ = _start_job("deps_install", {"ids": ids})
                self.send_json({"ok": True, "id": job_id})
                return
            # ---- Codex 历史 / 日志（v1.7.0）----
            if parsed.path == "/api/codex-paths":
                self.send_json(codexpaths.describe())
                return
            if parsed.path == "/api/codex-threads":
                q = parse_qs(parsed.query)
                only = q.get("archived", [""])[0]
                only_arch = None if only == "" else (only == "1")
                self.send_json(codexhistory.list_threads(
                    only_archived=only_arch,
                    limit=int(q.get("limit", ["500"])[0]),
                    keyword=q.get("kw", [""])[0]))
                return
            if parsed.path == "/api/codex-stats":
                self.send_json(codexhistory.stats())
                return
            if parsed.path == "/api/codex-backups":
                self.send_json({"ok": True,
                                "items": codexhistory.list_backups()})
                return
            if parsed.path == "/api/import-sources":
                self.send_json({"ok": True,
                                "items": codexhistory.scan_import_sources()})
                return
            if parsed.path == "/api/codex-logs":
                q = parse_qs(parsed.query)
                levels = [x for x in q.get("level", [""])[0].split(",") if x]
                self.send_json(codexlogs.query_logs(
                    levels=levels or None,
                    keyword=q.get("kw", [""])[0],
                    thread_id=q.get("thread", [""])[0],
                    limit=int(q.get("limit", ["200"])[0]),
                    offset=int(q.get("offset", ["0"])[0])))
                return
            if parsed.path == "/api/codex-logs-summary":
                self.send_json(codexlogs.summary())
                return
            if parsed.path == "/api/helper-log":
                q = parse_qs(parsed.query)
                # 默认保持旧行为：返回纯文本 tail
                # 带 format=structured 时返回结构化 JSON（AI 友好）
                if q.get("format", ["text"])[0] == "structured":
                    self.send_json(logs.tail(
                        lines=int(q.get("lines", ["300"])[0]),
                        level=q.get("level", [""])[0],
                        keyword=q.get("keyword", [""])[0],
                        offset=int(q.get("offset", ["0"])[0])))
                else:
                    self.send_json(codexlogs.read_helper_log(
                        tail_lines=int(q.get("lines", ["300"])[0])))
                return
            # ---- helper 诊断接口：供 AI/排查随时查看运行状态 ----
            if parsed.path == "/api/helper-status":
                self.send_json(_build_helper_status(self.server))
                return
            if parsed.path == "/api/helper-tasks":
                self.send_json(_build_helper_tasks())
                return
            if parsed.path == "/api/helper-task-log":
                job_id = parse_qs(parsed.query).get("id", [""])[0]
                lines = int(parse_qs(parsed.query).get("lines", ["200"])[0])
                self.send_json(logs.tail_task_log(job_id, lines))
                return
            if parsed.path == "/api/helper-client-errors":
                q = parse_qs(parsed.query)
                self.send_json(logs.tail_client_errors(
                    lines=int(q.get("lines", ["100"])[0]),
                    keyword=q.get("keyword", [""])[0],
                    offset=int(q.get("offset", ["0"])[0])))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except (ConnectionResetError, BrokenPipeError):
            return
        except Exception as exc:  # noqa: BLE001
            cfgcenter.write_exception_log("GET 请求处理失败", exc, path=self.path)
            try:
                self.send_json({"ok": False, "errors": [str(exc)]},
                               HTTPStatus.INTERNAL_SERVER_ERROR)
            except Exception:
                pass

    # ---- POST ----
    def do_POST(self):
        global _LAST_DETECT
        try:
            self.server.last_seen = time.time()
            if self.server.first_seen is None:
                self.server.first_seen = time.time()
            parsed = urlparse(self.path)
            if parsed.path == "/api/shutdown":
                self.send_json({"ok": True})
                threading.Thread(target=self._shutdown_server, daemon=True).start()
                return
            if parsed.path == "/api/task":
                body = self.read_json_body()
                action = (body.get("action") or "").strip()
                params = body if action else {}
                job_id, err = start_job(action, params)
                if job_id is None:
                    self.send_json({"ok": False, "errors": [err],
                                    "running_id": _CONFLICT[0]},
                                   HTTPStatus.CONFLICT)
                    return
                self.send_json({"ok": True, "id": job_id})
                return
            if parsed.path == "/api/cancel":
                ok = cancel_job(self.read_json_body().get("id", ""))
                self.send_json({"ok": True, "cancelled": ok})
                return
            # 前端异常上报。页面 JS 出错时后端一切正常，日志里不会有痕迹，
            # 排查"卡片全空白"这类问题全靠它——故单独开一个端点落到本程序日志。
            if parsed.path == "/api/client-error":
                body = self.read_json_body() or {}
                # 前端异常单独落到 client-errors.log，方便与后端日志分流排查
                logs.client_error(
                    str(body.get("message") or "未知错误"),
                    kind=str(body.get("kind") or "onerror"),
                    source=str(body.get("source") or ""),
                    line=body.get("line"),
                    column=body.get("column"),
                    stack=str(body.get("stack") or "")[:3000],
                )
                # 同时在主日志留一条摘要，避免只看主日志时完全不知道前端异常
                cfgcenter.write_log(
                    "WARN",
                    "前端异常已记录到 client-errors.log",
                    kind=str(body.get("kind") or "onerror"),
                    source=str(body.get("source") or ""),
                    line=body.get("line"),
                )
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/relaunch-admin":
                self.send_json({"ok": True})
                def _relaunch():
                    relaunch_as_admin()
                    time.sleep(0.5)
                    self.server.shutdown()
                threading.Thread(target=_relaunch, daemon=True).start()
                return
            if parsed.path == "/api/test-provider":
                self.send_json(cfgcenter.handle_test_provider(self.read_json_body()))
                return
            if parsed.path == "/api/test-all-providers":
                self.send_json(cfgcenter.handle_test_all_providers(self.read_json_body()))
                return
            if parsed.path == "/api/repair-codex":
                self.send_json(cfgcenter.handle_repair_codex(self.read_json_body()))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except (ConnectionResetError, BrokenPipeError):
            # 浏览器中途关闭连接（导航/刷新/超时）属正常现象，静默处理
            return
        except Exception as exc:  # noqa: BLE001
            cfgcenter.write_exception_log("POST 请求处理失败", exc, path=self.path)
            try:
                self.send_json({"ok": False, "errors": [str(exc)]},
                               HTTPStatus.INTERNAL_SERVER_ERROR)
            except Exception:
                pass

    def _shutdown_server(self):
        time.sleep(0.2)
        try:
            import webview
            for window in webview.windows:
                try:
                    window.destroy()   # pywebview 销毁可在非 GUI 线程调用
                except Exception:
                    pass
        except Exception:
            pass   # 浏览器模式无窗口
        self.server.shutdown()
        # 兜底：若窗口销毁在 GUI 线程侧未及时生效，2.5 秒后强制退出进程
        threading.Timer(2.5, lambda: os._exit(0)).start()


def _job_summary(job: _Job) -> dict:
    """给 helper-status / helper-tasks 用的任务摘要。"""
    return {
        "id": job.id,
        "action": job.action,
        "status": job.status,
        "ok": job.ok,
        "summary": job.summary,
        "progress": job.progress,
        "statusText": job.status_text,
        "created": job.created,
        "finished": job.created if job.status != "running" else None,
        "log_tail": [l["text"] for l in job.logs[-6:]],
        "log_count": len(job.logs),
    }


def _build_helper_tasks() -> dict:
    """返回所有任务（内存中）的摘要列表，按创建时间倒序。"""
    with _JOBS_LOCK:
        items = sorted(_JOBS.values(), key=lambda j: j.created, reverse=True)
        return {"ok": True, "count": len(items),
                "tasks": [_job_summary(j) for j in items]}


def _build_helper_status(server: CHServer) -> dict:
    """聚合当前运行状态，供 AI 一键排查"卡在何处"。"""
    now = time.time()
    home = codexpaths.resolve_codex_home()
    log_dir = logs.get_log_dir()
    main_log = logs.get_log_path()
    client_err = log_dir / "client-errors.log"

    with _JOBS_LOCK:
        running = [j for j in _JOBS.values() if j.status == "running"]
        current = _job_summary(running[0]) if running else None
        recent = sorted(
            [j for j in _JOBS.values() if j.status != "running"],
            key=lambda j: j.created, reverse=True)[:20]

    return {
        "ok": True,
        "app": APP_TITLE,
        "version": APP_VERSION,
        "vendor": APP_VENDOR,
        "pid": getattr(server, "pid", os.getpid()),
        "port": server.server_address[1],
        "admin": is_admin(),
        "boot_time": time.strftime("%Y-%m-%d %H:%M:%S",
                                     time.localtime(getattr(server, "boot_time", now))),
        "uptime_sec": int(now - getattr(server, "boot_time", now)),
        "first_seen": (time.strftime("%Y-%m-%d %H:%M:%S",
                                       time.localtime(server.first_seen))
                       if server.first_seen else None),
        "last_seen": (time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(server.last_seen))
                      if server.last_seen else None),
        "idle_sec": int(now - server.last_seen) if server.last_seen else 0,
        "homepage": _homepage(),
        "proxy": detect_proxy(),
        "codex_home": str(home) if home else None,
        "detect": _LAST_DETECT,
        "appx": _LAST_APPX[0],
        "pusher_enabled": _PUSHER[0] is not None,
        "current_task": current,
        "recent_tasks": [_job_summary(j) for j in recent],
        "logs": {
            "main": {"path": str(main_log),
                     "size": main_log.stat().st_size if main_log.is_file() else 0},
            "client_errors": {"path": str(client_err),
                              "size": client_err.stat().st_size
                              if client_err.is_file() else 0},
        },
    }


def _homepage() -> str:
    from ..constants import _wm
    try:
        return _wm()
    except Exception:
        return ""


def _wm_homepage() -> str:
    from ..constants import _wm
    return _wm()
