# -*- coding: utf-8 -*-
"""Codex 小帮手 Web 前端（v1.6.0）。

以收编项目（cfgcenter.HTML_PAGE）的页面为基底做四类注入：
① 品牌与配色（主色换成小帮手蓝、标题/副标题/关于）
② 三个新功能标签页（安装·修复 / 桌面端 升降级 / Codex 环境检测）
③ 任务系统 JS（/api/task 轮询：按钮加载态、进度条、日志控制台）
④ showTab 覆盖：九个标签页统一切换，支持 ?tab= 深链
加载动效沿用交接文档清单：骨架微光、按钮加载态、determinate 进度条、Spinner。
"""
from . import cfgcenter

VERSION = ""
VENDOR = "小枳ai分享"
HOMEPAGE = ""


def _build_html(version: str, vendor: str, homepage: str, is_admin: bool) -> str:
    html = cfgcenter.HTML_PAGE

    # ---------- ① CSS 覆盖与新增组件 ----------
    # 说明：品牌色、明暗模式、按钮/徽章语义色已全部收敛到 cfgcenter 的设计令牌。
    # 这里只补充小帮手特有的组件，且一律引用令牌，不再硬编码色值。
    css = """
    /* ---- 头部 ---- */
    .ver { font-size: var(--fs-12); color: var(--muted); font-weight: 600;
           margin-left: 6px; font-variant-numeric: tabular-nums; }
    .tabs { flex-wrap: wrap; }

    /* 权限徽章：既是状态显示，也是提权入口 */
    .adminbadge { border-color: var(--warn-line); background: var(--warn-soft);
                  color: var(--warn); cursor: pointer; }
    .adminbadge.ok { border-color: var(--ok-line); background: var(--ok-soft);
                     color: var(--ok); cursor: default; }

    /* 提权提示横幅 */
    .banner { display: none; align-items: center; gap: var(--sp-3);
      border: 1px solid var(--warn-line); background: var(--warn-soft); color: var(--warn);
      border-radius: var(--r-sm); padding: var(--sp-2) var(--sp-3);
      margin-bottom: var(--sp-4); font-size: var(--fs-13); line-height: 1.55; }
    .banner.show { display: flex; }
    .banner button { flex: 0 0 auto; }

    /* ---- 任务按钮加载态（Button Loading）---- */
    button.busy { position: relative; color: transparent !important; pointer-events: none; }
    button.busy::after { content: ""; position: absolute; inset: 0; margin: auto;
      width: 14px; height: 14px; border-radius: 50%;
      border: 2px solid var(--line-strong); border-top-color: var(--text-2);
      animation: ch-spin .7s linear infinite; }
    button.primary.busy::after { border-color: rgba(255, 255, 255, .35);
                                 border-top-color: var(--accent-fg); }
    @keyframes ch-spin { to { transform: rotate(360deg); } }

    /* ---- determinate 进度条：只在真正有进度时出现，避免 indeterminate 焦虑 ---- */
    .progress { height: 6px; border-radius: var(--r-pill); background: var(--surface-3);
                overflow: hidden; display: none; margin-top: var(--sp-2); }
    .progress.show { display: block; }
    .progress > i { display: block; height: 100%; width: 0; border-radius: var(--r-pill);
      background: var(--accent); transition: width var(--dur-slow) var(--ease-out); }
    .progress-label { color: var(--muted); font-size: var(--fs-12); margin-top: 6px;
                      min-height: 18px; line-height: 1.5; }

    /* ---- 日志控制台：固定深色终端语义 ---- */
    .console { background: var(--code-bg); color: var(--code-fg);
      border-radius: var(--r-md); padding: var(--sp-3);
      font-family: var(--font-mono); font-size: var(--fs-12); line-height: 1.65;
      max-height: 260px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
    .console .t-ok { color: #7ee2a8; } .console .t-warn { color: #ffd479; }
    .console .t-err { color: #ff9d92; } .console .t-dim { color: #8294ad; }
    .console .t-title { color: #e7eaf0; font-weight: 650; }

    /* ---- 骨架屏（Skeleton + Shimmer）：加载态占位，避免布局跳动 ---- */
    .skeleton { border-radius: var(--r-md);
      background: linear-gradient(90deg, var(--surface-3) 25%, var(--surface-2) 40%, var(--surface-3) 55%);
      background-size: 400px 100%; animation: ch-shimmer 1.4s infinite linear; }
    @keyframes ch-shimmer { from { background-position: -200px 0; } to { background-position: 200px 0; } }

    /* ---- 栅格与键值卡片 ---- */
    .grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--sp-2); }
    .grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--sp-2); }
    .kv { border: 1px solid var(--line); border-radius: var(--r-md); padding: var(--sp-3);
          background: var(--surface); min-width: 0; overflow: hidden;
          transition: border-color var(--dur-fast) var(--ease); }
    .kv:hover { border-color: var(--line-strong); }
    .kv .k { color: var(--muted); font-size: var(--fs-12); overflow-wrap: anywhere; }
    .kv .v { font-size: var(--fs-14); font-weight: 600; line-height: 1.45;
             overflow-wrap: anywhere; word-break: break-all; margin-bottom: 3px; }
    .btncol { display: flex; gap: var(--sp-2); flex-wrap: wrap; margin: var(--sp-3) 0; }
    .note { color: var(--muted); font-size: var(--fs-12); line-height: 1.6; }
    .section-gap { margin-top: var(--sp-4); }
    .ok-text { color: var(--ok); font-weight: 600; }
    .warn-text { color: var(--warn); font-weight: 600; }

    /* 版本列表：选中行用强调色软底，键盘同样可达 */
    .mirror-row { transition: background var(--dur-fast) var(--ease); }
    .mirror-row:hover { background: var(--surface-2); }
    .mirror-row[aria-selected="true"] { background: var(--accent-soft); }

    /* ---- 历史记录 / 日志（v1.7.0）---- */
    .toolbar {
      display: flex; align-items: center; gap: var(--sp-2);
      flex-wrap: wrap; margin-bottom: var(--sp-3);
    }
    .toolbar input[type="text"] { max-width: 260px; }
    .toolbar .spacer { flex: 1 1 auto; }

    .seg { display: inline-flex; gap: 2px; padding: 2px;
           background: var(--surface-3); border-radius: var(--r-sm); }
    .seg button { border-color: transparent; background: transparent;
                  box-shadow: none; min-height: 28px; padding: 0 var(--sp-3);
                  font-size: var(--fs-12); color: var(--muted); }
    .seg button.on { background: var(--surface); color: var(--text);
                     border-color: var(--line); box-shadow: var(--shadow-xs);
                     font-weight: 600; }

    .empty {
      border: 1px dashed var(--line-strong); border-radius: var(--r-md);
      padding: var(--sp-8) var(--sp-4); text-align: center;
      color: var(--muted); font-size: var(--fs-13);
      background: var(--surface-2);
    }

    /* 破坏性操作：仅用语义危险色描边/文字，:hover 需排除 :disabled
       （否则会盖掉统一的禁用态配色） */
    button.danger { border-color: var(--danger-line); color: var(--danger); }
    button.danger:hover:not(:disabled) {
      background: var(--danger-soft); border-color: var(--danger-line);
      color: var(--danger);
    }

    /* 会话行：左侧复选框 + 标题/元信息，右侧体积 */
    .hist { display: grid; gap: var(--sp-1); max-height: 62vh; overflow: auto; }
    .hist-row {
      display: grid; grid-template-columns: auto minmax(0, 1fr) auto;
      gap: var(--sp-3); align-items: center;
      padding: var(--sp-2) var(--sp-3);
      border: 1px solid var(--line); border-radius: var(--r-sm);
      background: var(--surface);
      transition: background var(--dur-fast) var(--ease),
                  border-color var(--dur-fast) var(--ease);
    }
    .hist-row:hover { background: var(--surface-2); }
    .hist-row.sel { border-color: var(--accent-line); background: var(--accent-soft); }
    .hist-row .t { font-size: var(--fs-13); font-weight: 550;
                   overflow-wrap: anywhere; }
    .hist-row .m { color: var(--muted); font-size: var(--fs-11);
                   margin-top: 2px; overflow-wrap: anywhere;
                   font-family: var(--font-mono); }
    .hist-row .sz { color: var(--muted); font-size: var(--fs-11);
                    font-variant-numeric: tabular-nums; white-space: nowrap; }
    .hist-row input[type="checkbox"] { margin: 0; }

    /* 日志级别徽章：五个级别各用一套语义色，明暗模式自动适配 */
    .lvl { display: inline-block; min-width: 46px; text-align: center;
           border-radius: var(--r-xs); padding: 0 5px;
           font-size: var(--fs-11); font-weight: 650; line-height: 18px; }
    .lvl-ERROR { background: var(--danger-soft); color: var(--danger); }
    .lvl-WARN  { background: var(--warn-soft); color: var(--warn); }
    .lvl-INFO  { background: var(--accent-soft); color: var(--accent-dark); }
    .lvl-DEBUG { background: var(--ok-soft); color: var(--ok); }
    .lvl-TRACE { background: var(--info-soft); color: var(--info-text); }

    .logs { max-height: 62vh; overflow: auto; }
    .log-row {
      border-bottom: 1px solid var(--line);
      padding: var(--sp-2) var(--sp-3); font-size: var(--fs-12);
    }
    .log-row:hover { background: var(--surface-2); }
    .log-head { display: flex; align-items: center; gap: var(--sp-2);
                flex-wrap: wrap; margin-bottom: 3px; }
    .log-ts { font-family: var(--font-mono); color: var(--muted);
              font-size: var(--fs-11); }
    .log-tgt { color: var(--text-2); font-weight: 550;
               overflow-wrap: anywhere; }
    .log-thr { font-family: var(--font-mono); font-size: var(--fs-11);
               color: var(--muted); }
    .log-body { font-family: var(--font-mono); font-size: var(--fs-12);
                line-height: 1.6; color: var(--text-2);
                white-space: pre-wrap; overflow-wrap: anywhere;
                max-height: 7.5em; overflow: auto; }
    .log-more { color: var(--accent-dark); font-size: var(--fs-11); }

    @media (max-width: 900px) {
      .grid3, .grid2 { grid-template-columns: 1fr; }
      .banner { flex-direction: column; align-items: flex-start; }
      .toolbar input[type="text"] { max-width: none; width: 100%; }
      .hist-row { grid-template-columns: auto minmax(0, 1fr); }
      .hist-row .sz { grid-column: 2; }
    }
"""
    html = html.replace("</style>", css + "</style>")
    assert "</style>" in html

    # ---------- ② 品牌头部 ----------
    html = html.replace("<h1>Codex Helper</h1>",
                        f'<h1>Codex 小帮手<span class="ver">v{version}</span></h1>')
    html = html.replace(
        "<p class=\"subtitle\">本机系统信息、Codex 配置和 CC Switch 文件夹查看器</p>",
        "<p class=\"subtitle\">Node.js + Codex CLI 一键安装 · 插件修复 · 桌面端升降级 · "
        "环境与配置中心</p>")
    html = html.replace(
        "<button class=\"primary\" id=\"refreshBtn\">刷新</button>",
        f'<span class="badge adminbadge" id="adminBadge">权限检测中…</span>\n'
        f'        <button class="primary" id="refreshBtn">刷新</button>')
    html = html.replace("<title>Codex Helper</title>",
                        '<title>Codex 小帮手</title>\n'
                        '  <link rel="icon" href="/favicon.ico">')

    # 管理员横幅（body 顶部，#shell 前）
    banner = """
  <div class="shell"><div class="banner" id="adminBanner">
    <span>⚠ 当前未以管理员身份运行：安装 Node.js / 修改系统设置时可能需要单独授权。</span>
    <button id="elevateBtn">以管理员身份重启</button>
  </div></div>
  <div class="shell" id="appShell">"""
    html = html.replace('  <div class="shell">\n    <header>', banner + "\n    <header>")
    html = html.replace('  </div>\n\n  <script>', "  </div>\n\n  <script>", 1)

    # ---------- ③ 新标签页按钮 ----------
    # 与 cfgcenter 的标签栏保持一致的无障碍语义（role=tab / aria-selected）。
    our_tabs = """<button class="tab active" data-tab="install" role="tab" aria-selected="true" aria-controls="tab-install">安装 · 修复</button>
          <button class="tab" data-tab="appx" role="tab" aria-selected="false" aria-controls="tab-appx">桌面端 升降级</button>
          <button class="tab" data-tab="envscan" role="tab" aria-selected="false" aria-controls="tab-envscan">Codex 环境检测</button>
          <button class="tab" data-tab="history" role="tab" aria-selected="false" aria-controls="tab-history">历史记录</button>
          <button class="tab" data-tab="logs" role="tab" aria-selected="false" aria-controls="tab-logs">日志</button>
          """
    anchor_tab = ('<button class="tab active" data-tab="system" role="tab" '
                  'aria-selected="true" aria-controls="tab-system">系统信息</button>')
    assert anchor_tab in html, "system tab anchor missing"
    # 小帮手自己的三个页签排在前面并默认激活，因此要把 system 的 active 让出去
    html = html.replace(anchor_tab,
                        our_tabs + '<button class="tab" data-tab="system" role="tab" '
                        'aria-selected="false" aria-controls="tab-system">系统信息</button>')

    # ---------- ④ 新标签页内容 ----------
    our_sections = """
          <section id="tab-install" role="tabpanel" aria-label="安装 · 修复">
            <h2 class="section-title">环境检测</h2>
            <div id="installDetect" class="grid3">
              <div class="skeleton" style="height:52px"></div>
              <div class="skeleton" style="height:52px"></div>
              <div class="skeleton" style="height:52px"></div>
            </div>
            <div class="btncol section-gap">
              <button class="primary" id="installAllBtn" data-task="install_all">一键安装 Node.js 和 Codex CLI</button>
              <button id="installNodeBtn" data-task="install_node">仅安装 Node.js</button>
              <button id="installCodexBtn" data-task="install_codex">仅安装 Codex CLI</button>
              <button id="fixPluginBtn" data-task="fix_plugin">🛠 一键修复 Codex 插件</button>
              <button id="fixGptBtn" data-task="fix_gpt">🔧 修复 ChatGPT 启动报错</button>
              <button id="cancelBtn" disabled>取消当前任务</button>
            </div>
            <div class="progress" id="taskProgress"><i></i></div>
            <div class="progress-label" id="taskStatus">就绪。</div>
            <h2 class="section-title section-gap">任务日志</h2>
            <div class="console" id="taskLog">等待任务…</div>
          </section>
          <section id="tab-appx" class="hidden" role="tabpanel" aria-label="桌面端 升降级">
            <h2 class="section-title">当前安装</h2>
            <div id="appxCurrent" class="grid2">
              <div class="skeleton" style="height:44px"></div>
              <div class="skeleton" style="height:44px"></div>
            </div>
            <div class="btncol section-gap">
              <button id="mirrorBtn" data-task="fetch_mirror">↻ 获取镜像版本列表（最近 50 个）</button>
              <button id="appxInstallBtn" disabled>⬇ 下载并安装所选版本（支持降级）</button>
            </div>
            <div class="progress" id="appxProgress"><i></i></div>
            <div class="progress-label" id="appxStatus">镜像列表未获取。单版本约 800 MB；降级会先卸载当前版本
              （只移除应用本体，不影响 ~/.codex 用户数据），安装会先关闭 ChatGPT。</div>
            <div id="mirrorTable" class="section-gap"></div>
          </section>
          <section id="tab-envscan" class="hidden" role="tabpanel" aria-label="Codex 环境检测">
            <h2 class="section-title">Codex 环境扫描</h2>
            <div class="note">扫描 ~/.codex 目录（.env）与 系统/用户/进程 三级环境变量中
              与 代理、API Key、Codex 相关的条目。密钥类值打码显示，代理地址与路径完整显示。</div>
            <div class="btncol section-gap">
              <button id="envScanBtn" data-task="env_scan">↻ 开始检测</button>
            </div>
            <div class="console" id="envReport">等待检测…</div>
          </section>
          <section id="tab-history" class="hidden" role="tabpanel" aria-label="历史记录">
            <h2 class="section-title">Codex 历史对话</h2>
            <div class="note">读取 <code>state_5.sqlite</code> 的会话索引；改库前会自动备份到
              <code>backups_state/codexhelper/</code>。归档 / 删除 / 导入期间请先关闭 Codex 桌面端，
              否则数据库被占用会失败。</div>
            <div id="histPaths" class="grid3" style="margin-top:10px"></div>
            <div class="toolbar section-gap">
              <div class="seg" id="histFilter">
                <button data-f="" class="on">全部</button>
                <button data-f="0">活跃</button>
                <button data-f="1">已归档</button>
              </div>
              <input type="text" id="histKw" placeholder="搜索标题 / 会话 ID…" aria-label="搜索会话">
              <button id="histRefresh">↻ 刷新</button>
              <span class="spacer"></span>
              <button id="histArchiveBtn" disabled>📥 归档所选</button>
              <button id="histRestoreBtn" disabled>📤 恢复所选</button>
              <button id="histDeleteBtn" disabled class="danger">🗑 删除所选</button>
            </div>
            <div class="btncol" style="margin-top:0">
              <button id="importClaudeBtn">⇩ 从 Claude Code 导入</button>
              <button id="importCodexBtn">⇩ 从另一 Codex 目录导入</button>
            </div>
            <div id="histList" class="hist">
              <div class="skeleton" style="height:44px"></div>
              <div class="skeleton" style="height:44px"></div>
              <div class="skeleton" style="height:44px"></div>
            </div>
            <div class="note section-gap" id="histNote">—</div>
          </section>
          <section id="tab-logs" class="hidden" role="tabpanel" aria-label="日志">
            <h2 class="section-title">Codex 运行日志</h2>
            <div class="note">读取 <code>.codex/logs_2.sqlite</code>。日志库可能有上百 MB，
              因此每次只取最新的一页，关键词在服务端过滤后返回。</div>
            <div id="logSummary" class="grid3" style="margin-top:10px"></div>
            <div class="toolbar section-gap">
              <div class="seg" id="logLevel">
                <button data-lv="" class="on">全部</button>
                <button data-lv="ERROR">错误</button>
                <button data-lv="WARN">警告</button>
                <button data-lv="INFO">信息</button>
              </div>
              <input type="text" id="logKw" placeholder="搜索正文 / 模块…" aria-label="搜索日志">
              <button id="logRefresh">↻ 刷新</button>
              <span class="spacer"></span>
              <button id="logMoreBtn" disabled>加载更多</button>
              <button id="logExportBtn">⭳ 导出为 txt</button>
            </div>
            <div id="logList" class="logs">
              <div class="skeleton" style="height:60px"></div>
              <div class="skeleton" style="height:60px"></div>
            </div>
            <h2 class="section-title section-gap">本程序日志（Codex Helper.log）</h2>
            <div class="console" id="helperLog">—</div>
          </section>"""
    anchor = ('<section id="tab-raw" class="hidden" role="tabpanel" '
              'aria-label="原始文件"></section>')
    assert anchor in html, "raw section anchor missing"
    html = html.replace(anchor, our_sections + "\n" + anchor)

    # ---------- ⑤ 任务系统 JS（注入到 </script> 前）----------
    js = """
    /* ==================== 全局错误兜底（必须最先注册）====================
       页面 JS 一旦抛错，整段 script 会中断，所有渲染静默失效——
       表现就是"卡片全空白"，而后端日志干干净净，极难定位。
       因此这里把异常同时送到三处：后端日志、页面日志面板、可见横幅。 */
    (function () {
      function report(msg, kind, extra) {
        try {
          fetch("/api/client-error", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(Object.assign({
              message: String(msg || "未知错误").slice(0, 500),
              kind: kind || "onerror"
            }, extra || {}))
          }).catch(function () {});
        } catch (e) {}
        try {
          var box = document.getElementById("taskLog");
          if (box) {
            var line = document.createElement("div");
            line.textContent = "[" + (kind || "error") + "] " + msg;
            line.style.color = "var(--danger)";
            box.appendChild(line);
          }
        } catch (e) {}
      }

      window.addEventListener("error", function (event) {
        var t = event.target;
        // 资源加载失败（img/script）不带 error 对象，单独处理
        if (t && t !== window && t.tagName) {
          report("资源加载失败：" + (t.src || t.href || t.tagName), "resource");
          return;
        }
        report(event.message, "onerror", {
          source: event.filename, line: event.lineno,
          column: event.colno,
          stack: event.error && event.error.stack ? event.error.stack : ""
        });
      }, true);

      window.addEventListener("unhandledrejection", function (event) {
        var r = event.reason || {};
        report(r.message || String(r), "unhandledrejection", {
          stack: r.stack || ""
        });
      });
    })();

    /* ==================== Codex 小帮手 任务系统 ==================== */
    const CH = {
      logSeen: {},
      push: false,
      version: {{VERSION_JSON}},
      vendor: {{VENDOR_JSON}},
      homepage: {{HOMEPAGE_JSON}},
      currentJob: null,
      releases: [],
      selectedRelease: null
    };

    const TASK_LABELS = {
      install_all: "正在安装", install_node: "正在安装", install_codex: "正在安装",
      fix_plugin: "正在修复", fix_gpt: "正在修复",
      fetch_mirror: "正在获取", install_msix: "正在下载安装", env_scan: "正在扫描",
      detect: "正在检测"
    };

    function setProgress(sel, frac, label) {
      const box = $(sel);
      if (!box) return;
      const bar = box.querySelector("i");
      if (frac === null || frac === undefined || !bar) { box.classList.remove("show"); return; }
      box.classList.add("show");
      bar.style.width = Math.round(frac * 100) + "%";
      if (label !== undefined) {
        const lab = $(sel.replace(".progress", ".progress-label"));
        if (lab) lab.textContent = label;
      }
    }

    function appendLog(sel, text, cls) {
      const box = $(sel);
      const line = document.createElement("div");
      if (cls) line.className = "t-" + cls;
      line.textContent = text;
      box.appendChild(line);
      box.scrollTop = box.scrollHeight;
    }

    async function apiState() {
      const r = await fetch("/api/state");
      return await r.json();
    }

    async function startTask(action, params) {
      if (CH.currentJob) { alert("已有任务在运行，请先等待完成或取消。"); return null; }
      let data;
      try {
        data = await postJson("/api/task", { action, params: params || {} });
      } catch (error) {
        appendLog("#taskLog", "任务启动失败：" + error.message, "err");
        return null;
      }
      CH.currentJob = data.id;
      document.querySelectorAll("[data-task]").forEach(b => {
        if (b.id !== "cancelBtn") { b.classList.add("busy"); b.disabled = true; }
      });
      $("#cancelBtn").disabled = false;
      const label = TASK_LABELS[action] || "正在处理";
      setProgress("#taskProgress", 0, label + "…");
      appendLog("#taskLog", "—— " + label + " ——", "ok");
      if (!CH.push) pollJob(data.id);   // 推送模式下由 Python 每秒推 __applyJob
      return data.id;
    }

    // 统一的任务渲染入口：
    // - webview 推送模式：Python 每秒 evaluate_js 调用 __applyJob（不受页面
    //   定时器节流影响——WebView2 里 setTimeout/fetch 轮询可能被冻结）；
    // - 浏览器回退模式：pollJob 每 700ms 拉取一次再走同一渲染函数。
    window.__applyJob = function (job) {
      try {
      window.__trace = window.__trace || [];
      window.__pc = (window.__pc || 0) + 1;
      window.__trace.push("apply#" + window.__pc + " status=" + job.status);

      // 增量渲染任务日志（按已读条数去重）
      const seen = CH.logSeen[job.id] || 0;
      (job.logs || []).slice(seen).forEach(line => {
        appendLog("#taskLog", line.t ? line.t + " " + line.text : line.text,
                  line.tag === "normal" ? "" : line.tag);
      });
      CH.logSeen[job.id] = (job.logs || []).length;

      // 渐进渲染：后台任务一有部分结果就先上屏（不等整个任务结束）
      const res = job.result || {};
      if (res.info) renderInstallDetect(res.info, res.gpt || {});
      if (res.appx) renderAppxCurrent(res.appx);
      if (res.report) renderEnvReport(res.report);
      if (res.releases) renderMirrorTable(res.releases);

      // 进度条 / 状态文字
      if (typeof job.progress === "number") {
        setProgress("#taskProgress", job.progress,
          (job.statusText || "处理中") + "（" + Math.round(job.progress * 100) + "%）");
      } else if (job.statusText) {
        setProgress("#taskProgress", 0, job.statusText);
        $("#taskProgress").classList.add("show");
      }

      if (job.status === "running") {
        // ⚠ 这里曾写成 pollJob(id)：本函数形参是 job 而非 id，
        // ReferenceError 被外层 try/catch 吞掉，导致任务永远停在 busy。
        // 浏览器回退模式下才需要续轮询；推送模式由 Python 每秒调用本函数。
        if (!CH.push) setTimeout(() => pollJob(job.id), 700);
        return;
      }

      window.__trace.push("jobDone action=" + job.action + " ok=" + job.ok);
      // 任务结束：恢复按钮、渲染结果
      CH.currentJob = null;
      document.querySelectorAll("[data-task]").forEach(b => {
        b.classList.remove("busy"); b.disabled = false;
      });
      $("#cancelBtn").disabled = true;
      setProgress("#taskProgress", null);
      $("#taskStatus").textContent = (job.ok ? "✔ 已完成：" : "⚠ 已结束：") + (job.summary || "");
      appendLog("#taskLog", (job.ok ? "✔ " : "⚠ ") + (job.summary || ""), job.ok ? "ok" : "warn");
      onJobDone(job);
      // 只有非检测任务结束才自动刷新检测结果；
      // 否则 detect→完成→refreshDetect→detect… 会形成无限循环（按钮一直转圈）
      if (job.action !== "detect") refreshDetect();
      } catch (e) {
        window.__trace.push("applyErr: " + (e.message || e));
      }
    }

    async function pollJob(id) {
      let job;
      try {
        const r = await fetch("/api/task?id=" + encodeURIComponent(id));
        job = await r.json();
      } catch (error) {
        job = { id: id, status: "running", logs: [], progress: null };
        setTimeout(() => pollJob(id), 1500);
        return;
      }
      job.id = id;
      window.__applyJob(job);
      if (job.status === "running") setTimeout(() => pollJob(id), 700);
    }

    function onJobDone(job) {
      // 兼容占位：结果渲染已由 __applyJob 统一处理（勿在此再调 __applyJob，会无限递归）
    }

    /* ---- 安装 · 修复 ---- */
    function detectBadge(name, okFlag, value, okText, badText) {
      return `<div class="kv"><div class="k">${escapeHtml(name)}</div>
        <div class="v ${okFlag ? "ok-text" : "warn-text"}">${escapeHtml(okFlag ? (okText || "✓") : (badText || "✗"))}</div>
        ${value ? `<div class="k" style="margin-top:3px">${escapeHtml(value)}</div>` : ""}</div>`;
    }

    function renderInstallDetect(info, gpt) {
      info = info || {};
      gpt = gpt || {};
      const box = $("#installDetect");
      box.className = "grid3";
      const node = info.node_ver, npm = info.npm_ver, codex = info.codex_ver;
      const gptPkg = gpt.pkg;
      const cliPath = info.codex_shim || "";
      const gptLoc = (gptPkg && gptPkg.location) || "";
      box.innerHTML = [
        detectBadge("Node.js", node, info.node_dir, "✓ v" + node, "✗ 未安装"),
        detectBadge("npm", npm, info.npm_prefix, "✓ v" + npm, "✗ 不可用"),
        detectBadge("Codex CLI", codex, cliPath, "✓ v" + codex, "✗ 未安装"),
        detectBadge("ChatGPT 桌面端", gptPkg, gptLoc,
          gptPkg ? "✓ v" + gptPkg.version : "✗ 未安装", "✗ 未安装"),
        detectBadge("CODEX_CLI_PATH", gpt.env, "", gpt.env ? "✓ 已设置" : "✗ 未设置", "✗ 未设置"),
        detectBadge("运行权限", true, "", window.CH_IS_ADMIN ? "✓ 管理员" : "⚠ 普通权限", "")
      ].join("");
    }

    /* ---- 桌面端 升降级 ---- */
    function renderAppxCurrent(pkg) {
      const box = $("#appxCurrent");
      box.className = "grid2";
      box.innerHTML = pkg ? [
        detectBadge("已安装版本", true, pkg.location, "✓ v" + pkg.version),
        detectBadge("应用架构与状态", true, "", "x64/arm64 自动匹配 · 已安装")
      ].join("") : detectBadge("OpenAI.Codex 桌面应用", false, "", "", "✗ 未安装");
    }

    function relLabel(ver) {
      if (ver === "安装时解析" || !window.CH_INSTALLED) return "—";
      const cmp = (a, b) => {
        const pa = a.split(".").map(Number), pb = b.split(".").map(Number);
        for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
          const d = (pa[i] || 0) - (pb[i] || 0);
          if (d) return d;
        }
        return 0;
      };
      const d = cmp(ver, window.CH_INSTALLED);
      return d > 0 ? "▲ 可升级" : (d < 0 ? "▼ 可降级" : "● 当前版本");
    }

    function renderMirrorTable(releases) {
      CH.releases = releases || [];
      const rows = CH.releases.map((rel, i) => {
        const msix = rel.msix;
        const ver = msix ? msix.version : "安装时解析";
        const size = msix ? (msix.size / 1048576).toFixed(0) + " MB" : "—";
        const relLabel2 = relLabel(ver);
        const cls = relLabel2.includes("升级") ? "badge success"
          : (relLabel2.includes("降级") ? "badge testing" : "badge current");
        return `<tr data-idx="${i}" class="mirror-row" tabindex="0" role="button"
          aria-selected="false" style="cursor:pointer">
          <td>${escapeHtml(ver)}</td><td>${escapeHtml(size)}</td>
          <td>${escapeHtml(rel.published || "—")}</td>
          <td><span class="${cls}">${relLabel2}</span></td></tr>`;
      }).join("");
      $("#mirrorTable").innerHTML = `
        <div class="table-wrap"><table>
          <thead><tr><th>版本 (MSIX)</th><th>大小</th><th>发布日期</th><th>与当前相比</th></tr></thead>
          <tbody>${rows}</tbody></table></div>`;

      const pick = (tr) => {
        document.querySelectorAll(".mirror-row").forEach(x => {
          x.setAttribute("aria-selected", "false");
          x.style.background = "";
        });
        tr.setAttribute("aria-selected", "true");
        CH.selectedRelease = Number(tr.dataset.idx);
        $("#appxInstallBtn").disabled = false;
        const rel = CH.releases[CH.selectedRelease];
        const ver = rel.msix ? rel.msix.version : "安装时解析";
        setProgress("#appxProgress", 0, "已选：" + ver + "（" + rel.tag + "）");
      };

      document.querySelectorAll(".mirror-row").forEach(tr => {
        tr.addEventListener("click", () => pick(tr));
        // 键盘等效操作：焦点落在行上时回车 / 空格即选中
        tr.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          pick(tr);
        });
      });
    }

    /* ---- 环境检测 ---- */
    function renderEnvReport(report) {
      const box = $("#envReport");
      box.innerHTML = "";
      const add = (text, cls) => {
        const line = document.createElement("div");
        if (cls) line.className = "t-" + cls;
        line.textContent = text;
        box.appendChild(line);
      };
      const p = report.proxy || {};
      add(p.enabled ? "【代理】已检测到" + p.source + "：" + p.server : "【代理】未检测到系统代理或代理环境变量", p.enabled ? "ok" : "warn");
      const ef = report.env_file || {};
      add("【.codex 目录】" + report.home, "title");
      if (ef.exists) {
        add("  .env 文件：✓ 存在（" + ef.count + " 项）→ " + ef.path, "ok");
        (ef.entries || []).forEach(e => add("    " + e.name + " = " + e.masked, e.secret ? "warn" : ""));
      } else {
        add("  .env 文件：✗ 不存在（可选的本地环境配置，不影响使用）", "dim");
      }
      const vars = report.vars || [];
      add("【相关环境变量】共 " + vars.length + " 条命中（代理 / API Key / Codex 相关）", "title");
      vars.forEach(v => add("  [" + v.source + "] " + (v.secret ? "🔑 " : (v.proxy ? "🛜 " : "• ")) + v.name + " = " + v.masked, v.secret ? "warn" : ""));
      add("【CODEX_CLI_PATH】" + (report.cli_path || "（未设置）"), report.cli_path ? "ok" : "dim");
    }

    /* ---- showTab 覆盖：十一个标签页 + 深链 ---- */
    const CH_TABS = ["install", "appx", "envscan", "history", "logs",
                     "system", "config", "auth", "cc", "codexplus", "raw"];
    const _origShowTab = showTab;
    showTab = function (name) {
      state.activeTab = name;
      document.querySelectorAll(".tab").forEach(tab => {
        const active = tab.dataset.tab === name;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
        tab.tabIndex = active ? 0 : -1;
      });
      CH_TABS.forEach(tab => {
        const el = document.getElementById("tab-" + tab);
        if (el) el.classList.toggle("hidden", tab !== name);
      });
      // 键盘导航需要覆盖到全部九个页签（原实现只覆盖后六个）
      if (!CH._tabKeysBound) {
        CH._tabKeysBound = true;
        document.getElementById("tabs").addEventListener("keydown", (event) => {
          const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
          if (!keys.includes(event.key)) return;
          const tabs = [...document.querySelectorAll(".tab")];
          const index = tabs.findIndex(tab => tab.dataset.tab === state.activeTab);
          if (index < 0) return;
          event.preventDefault();
          let next = index;
          if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
          if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
          if (event.key === "Home") next = 0;
          if (event.key === "End") next = tabs.length - 1;
          showTab(tabs[next].dataset.tab);
          tabs[next].focus();
        });
      }
    };

    /* ---- 事件绑定 ---- */
    document.querySelectorAll("[data-task]").forEach(btn => {
      btn.addEventListener("click", () => startTask(btn.dataset.task));
    });
    $("#cancelBtn").addEventListener("click", async () => {
      if (!CH.currentJob) return;
      await postJson("/api/cancel", { id: CH.currentJob });
      appendLog("#taskLog", "已请求取消…", "warn");
    });
    $("#appxInstallBtn").addEventListener("click", () => {
      if (CH.selectedRelease == null) { alert("请先在列表中选择一个版本。"); return; }
      const rel = CH.releases[CH.selectedRelease];
      if (!confirm("将下载并安装 " + (rel.msix ? rel.msix.version : rel.tag) +
        "。若为降级，会先卸载当前版本（只移除应用本体，不影响 ~/.codex 用户数据）。是否继续？")) return;
      startTask("install_msix", { index: CH.selectedRelease });
    });
    $("#elevateBtn") && $("#elevateBtn").addEventListener("click", async () => {
      try { await postJson("/api/relaunch-admin", {}); } catch (error) {}
      document.body.innerHTML = '<div class="shell"><div class="panel content"><h1>正在以管理员身份重启…</h1><p class="subtitle">如果系统弹出了授权窗口，请点【是】；取消授权则继续以普通权限运行。</p></div></div>';
    });
    $("#aboutBtn") && $("#aboutBtn").addEventListener("click", () => {
      alert("Codex 小帮手 v" + CH.version + "\\n—— Node.js + Codex CLI 一键安装 · 插件修复 · 桌面端升降级 \\n 历史记录管理 · 日志查看\\n\\n© 2026 " + CH.vendor + " · 版权所有\\n作者主页：" + CH.homepage);
    });

    /* ================= 历史记录 ================= */
    const HIST = { rows: [], sel: new Set(), filter: "", kw: "", loaded: false };

    function fmtTime(sec) {
      if (!sec) return "—";
      const d = new Date(Number(sec) * 1000);
      if (isNaN(d.getTime())) return "—";
      const p = n => String(n).padStart(2, "0");
      return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate())
        + " " + p(d.getHours()) + ":" + p(d.getMinutes());
    }

    function fmtSize(b) {
      if (!b) return "—";
      if (b < 1024) return b + " B";
      if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
      return (b / 1048576).toFixed(1) + " MB";
    }

    function renderHistPaths(paths) {
      const box = $("#histPaths");
      if (!paths || !paths.home) {
        box.innerHTML = '<div class="kv"><div class="k">存储位置</div>'
          + '<div class="v warn-text">✗ 未定位到 CODEX_HOME</div></div>';
        return;
      }
      box.innerHTML = [
        detectBadge("存储位置", paths.exists, paths.home,
          "✓ " + paths.home, "✗ 未找到"),
        detectBadge("会话文件", paths.sessions_count > 0,
          (paths.sessions || "") + " · " + (paths.archived_count || 0) + " 个归档",
          "✓ " + paths.sessions_count + " 个", "✗ 无"),
        detectBadge("定位方式", true, paths.env_codex_home
          ? "CODEX_HOME 环境变量" : "用户主目录（默认）",
          paths.env_codex_home ? "环境变量" : "默认路径", "")
      ].join("");
    }

    function renderThreads(rows) {
      HIST.rows = rows || [];
      const box = $("#histList");
      if (!HIST.rows.length) {
        box.innerHTML = '<div class="empty">没有匹配的会话。'
          + '若刚导入或归档，点【↻ 刷新】重新加载。</div>';
        updateHistBtns();
        return;
      }
      box.innerHTML = HIST.rows.map(r => {
        const badges = [
          r.archived ? '<span class="badge testing">已归档</span>' : "",
          r.is_pinned ? '<span class="badge key">置顶</span>' : "",
          r.missing ? '<span class="badge error">文件缺失</span>' : "",
          r.model_provider ? '<span class="badge">' + escapeHtml(r.model_provider) + '</span>' : ""
        ].filter(Boolean).join(" ");
        return `<div class="hist-row${HIST.sel.has(r.id) ? " sel" : ""}" data-id="${escapeHtml(r.id)}">
          <input type="checkbox" ${HIST.sel.has(r.id) ? "checked" : ""}
                 aria-label="选择会话 ${escapeHtml(r.title)}">
          <div>
            <div class="t">${escapeHtml(r.title)}</div>
            <div class="m">${escapeHtml(r.id.slice(0, 8))} · ${fmtTime(r.updated_at)}
              · ${fmtSize(r.rollout_size)}${badges ? " · " + badges : ""}</div>
          </div>
          <div class="sz">${escapeHtml(r.cwd || "")}</div>
        </div>`;
      }).join("");

      box.querySelectorAll(".hist-row").forEach(row => {
        const id = row.dataset.id;
        row.querySelector("input").addEventListener("change", (e) => {
          e.target.checked ? HIST.sel.add(id) : HIST.sel.delete(id);
          row.classList.toggle("sel", e.target.checked);
          updateHistBtns();
        });
      });
      updateHistBtns();
    }

    function updateHistBtns() {
      const n = HIST.sel.size;
      $("#histArchiveBtn").disabled = n === 0;
      $("#histRestoreBtn").disabled = n === 0;
      $("#histDeleteBtn").disabled = n === 0;
      $("#histNote").textContent = n
        ? "已选中 " + n + " 个会话。"
        : "共 " + HIST.rows.length + " 个会话。勾选后可归档 / 恢复 / 删除。";
    }

    async function loadThreads() {
      const kw = $("#histKw").value.trim();
      const q = new URLSearchParams({ limit: "500" });
      if (HIST.filter !== "") q.set("archived", HIST.filter);
      if (kw) q.set("kw", kw);
      try {
        const r = await fetch("/api/codex-threads?" + q.toString());
        const d = await r.json();
        if (!d.ok) {
          $("#histList").innerHTML = '<div class="empty">'
            + escapeHtml(d.error || "读取失败") + '</div>';
          return;
        }
        renderThreads(d.threads);
      } catch (error) {
        $("#histList").innerHTML = '<div class="empty">读取失败：'
          + escapeHtml(error.message) + '</div>';
      }
      try {
        const p = await fetch("/api/codex-paths").then(x => x.json());
        renderHistPaths(p);
      } catch (error) { /* 路径诊断失败不阻塞列表 */ }
    }

    $("#histRefresh").addEventListener("click", loadThreads);
    $("#histKw").addEventListener("keydown", (e) => {
      if (e.key === "Enter") loadThreads();
    });
    $("#histFilter").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      $("#histFilter").querySelectorAll("button").forEach(x => x.classList.remove("on"));
      b.classList.add("on");
      HIST.filter = b.dataset.f;
      loadThreads();
    });

    async function histAction(action, confirmMsg) {
      const ids = [...HIST.sel];
      if (!ids.length) return;
      if (confirmMsg && !confirm(confirmMsg.replace("{n}", ids.length))) return;
      await startTask(action, { ids: ids });
      HIST.sel.clear();
      loadThreads();
    }

    // 注意：下面 confirm/prompt 文案里的换行必须写成转义形式（反斜杠加 n）。
    // 若误写成真实换行，JS 双引号字符串不能跨行，整个 script 块会抛
    // SyntaxError 而停摆，页面所有渲染静默失效（表现为卡片全空白）。
    // 改完务必跑 node --check 校验（见 _js_check.py）。
    $("#histArchiveBtn").addEventListener("click", () =>
      histAction("archive_threads", "将 {n} 个会话归档？\\n归档后会话文件移入 archived_sessions，"
        + "Codex 列表里不再显示，可随时恢复。"));
    $("#histRestoreBtn").addEventListener("click", () =>
      histAction("restore_threads", "恢复 {n} 个归档会话？\\n会话文件将移回 sessions 目录。"));
    $("#histDeleteBtn").addEventListener("click", () =>
      histAction("delete_threads", "确定删除 {n} 个会话？\\n"
        + "这会同时删除数据库记录和会话文件，不可撤销。\\n"
        + "操作前会自动备份数据库到 backups_state/codexhelper/。"));
    $("#importClaudeBtn").addEventListener("click", async () => {
      if (!confirm("从 ~/.claude/projects 导入 Claude Code 会话？\\n"
        + "会转换为 Codex 会话格式（仅迁移文本内容）。")) return;
      await startTask("import_claude", {});
      loadThreads();
    });
    $("#importCodexBtn").addEventListener("click", async () => {
      const src = prompt("输入另一个 Codex 数据目录（含 sessions 文件夹）：",
        "C:\\\\Users\\\\你的用户名\\\\.codex");
      if (!src) return;
      await startTask("import_codex", { src: src });
      loadThreads();
    });

    /* ================= 日志 ================= */
    const LOGS = { offset: 0, limit: 100, level: "", kw: "", rows: [], loaded: false };

    function renderLogSummary(s) {
      const box = $("#logSummary");
      if (!s || !s.ok) {
        box.innerHTML = '<div class="kv"><div class="k">日志库</div>'
          + '<div class="v warn-text">✗ '
          + escapeHtml((s && s.error) || "不可用") + '</div></div>';
        return;
      }
      const lv = s.levels || {};
      box.innerHTML = [
        detectBadge("日志总数", true, fmtSize(s.size || 0), "✓ " + s.total + " 条", "—"),
        detectBadge("时间范围", true, (s.min_ts || "") + " → " + (s.max_ts || ""),
          "✓ 有数据", "—"),
        detectBadge("级别分布", true,
          "错误 " + (lv.ERROR || 0) + " · 警告 " + (lv.WARN || 0)
          + " · 信息 " + (lv.INFO || 0),
          "✓ " + Object.keys(lv).length + " 种", "—")
      ].join("");
    }

    function renderLogs(rows, append, has_more) {
      const box = $("#logList");
      if (!rows.length && !append) {
        box.innerHTML = '<div class="empty">没有匹配的日志。</div>';
        $("#logMoreBtn").disabled = true;
        return;
      }
      const html = rows.map(r =>
        `<div class="log-row">
          <div class="log-head">
            <span class="lvl lvl-${escapeHtml(r.level)}">${escapeHtml(r.level)}</span>
            <span class="log-ts">${escapeHtml(r.ts)}</span>
            <span class="log-tgt">${escapeHtml(r.target || r.module || "")}</span>
            ${r.thread_id ? '<span class="log-thr">线程 ' + escapeHtml(r.thread_id.slice(0, 8)) + '</span>' : ""}
          </div>
          <div class="log-body">${escapeHtml(r.body)}${r.truncated ? '<span class="log-more"> …（已截断）</span>' : ""}</div>
        </div>`).join("");
      box.innerHTML = append ? box.innerHTML + html : html;
      // 以服务端 has_more 为准：关键词/级别过滤后本页行数常小于 limit，
      // 但库里可能还有更多，用行数判断会过早禁用"加载更多"。
      $("#logMoreBtn").disabled = !has_more;
    }

    async function loadLogs(append) {
      if (!append) LOGS.offset = 0;
      const q = new URLSearchParams({
        limit: String(LOGS.limit), offset: String(LOGS.offset)
      });
      if (LOGS.level) q.set("level", LOGS.level);
      const kw = $("#logKw").value.trim();
      if (kw) q.set("kw", kw);
      try {
        const d = await fetch("/api/codex-logs?" + q.toString()).then(x => x.json());
        if (!d.ok) {
          $("#logList").innerHTML = '<div class="empty">'
            + escapeHtml(d.error || "读取失败") + '</div>';
          return;
        }
        renderLogs(d.rows || [], append, d.has_more);
        LOGS.offset += (d.rows || []).length;
      } catch (error) {
        $("#logList").innerHTML = '<div class="empty">读取失败：'
          + escapeHtml(error.message) + '</div>';
      }
      try {
        renderLogSummary(await fetch("/api/codex-logs-summary").then(x => x.json()));
      } catch (error) { /* 概览失败不阻塞 */ }
    }

    $("#logRefresh").addEventListener("click", () => loadLogs(false));
    $("#logKw").addEventListener("keydown", (e) => {
      if (e.key === "Enter") loadLogs(false);
    });
    $("#logMoreBtn").addEventListener("click", () => loadLogs(true));
    $("#logLevel").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      $("#logLevel").querySelectorAll("button").forEach(x => x.classList.remove("on"));
      b.classList.add("on");
      LOGS.level = b.dataset.lv;
      loadLogs(false);
    });
    $("#logExportBtn").addEventListener("click", async () => {
      await startTask("export_logs", {
        levels: LOGS.level ? [LOGS.level] : null,
        keyword: $("#logKw").value.trim(), limit: 5000
      });
    });

    async function loadHelperLog() {
      try {
        const d = await fetch("/api/helper-log?lines=200").then(x => x.json());
        const box = $("#helperLog");
        box.textContent = d.ok ? (d.text || "（空）")
          : ("未找到：" + (d.error || "不可用"));
      } catch (error) { /* 忽略 */ }
    }

    // 切到历史 / 日志页时才首次加载，避免开屏就打两个大查询
    const _origShowTab2 = showTab;
    showTab = function (name) {
      _origShowTab2(name);
      if (name === "history" && !HIST.loaded) { HIST.loaded = true; loadThreads(); }
      if (name === "logs" && !LOGS.loaded) {
        LOGS.loaded = true; loadLogs(false); loadHelperLog();
      }
    };

    /* ---- 初始化 ---- */
    (async () => {
      // 深链切页最先执行（不等任何网络请求）
      const wanted = new URLSearchParams(location.search).get("tab");
      showTab(CH_TABS.includes(wanted) ? wanted : "install");
      try {
        const st = await apiState();
        CH.push = !!st.push;
        window.CH_IS_ADMIN = st.is_admin;
        const badge = $("#adminBadge");
        if (st.is_admin) { badge.textContent = "✓ 管理员模式"; badge.classList.add("ok"); }
        else { badge.textContent = "⚠ 普通权限"; badge.title = "点击以管理员身份重启"; badge.addEventListener("click", () => $("#elevateBtn").click()); }
        if (!st.is_admin) $("#adminBanner").classList.add("show");
        // 优先用服务端缓存即时渲染（配合 /api/appx?refresh=1 才会真正重新探测）
        if (st.detect && st.detect.info) renderInstallDetect(st.detect.info, st.detect.gpt || {});
        const appx = await fetch("/api/appx").then(r => r.json());
        window.CH_INSTALLED = appx.version || null;
        renderAppxCurrent(appx.pkg);
        if (!(st.detect && st.detect.info)) refreshDetect();
      } catch (error) { /* 状态获取失败不阻塞页面 */ }
    })();

    async function refreshDetect() {
      try { await startTask("detect"); } catch (error) { /* 忽略 */ }
    }
"""
    js = (js.replace("{{VERSION_JSON}}", json_dumps(version))
            .replace("{{VENDOR_JSON}}", json_dumps(vendor))
            .replace("{{HOMEPAGE_JSON}}", json_dumps(homepage)))
    anchor = '    setInterval(() => fetch("/api/ping").catch(() => {}), 10000);'
    assert anchor in html, "ping anchor missing"
    html = html.replace(anchor, anchor + "\n" + js)

    # 修一处原页面遗留：副标题里的产品名（已换）；标题行“关于”按钮
    html = html.replace(
        '<button id="shutdownBtn">关闭程序</button>',
        '<button id="aboutBtn">关于</button>\n        <button id="shutdownBtn">关闭程序</button>')
    html = html.replace("Codex Helper 已关闭", "Codex 小帮手 已关闭")
    return html


def json_dumps(value: str) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


def get_page(version: str, vendor: str, homepage: str, is_admin: bool) -> str:
    """服务端每次 GET / 调用：按当前权限状态渲染页面。"""
    global VERSION, VENDOR, HOMEPAGE
    VERSION, VENDOR, HOMEPAGE = version, vendor, homepage
    html = _build_html(version, vendor, homepage, is_admin)
    if not is_admin:
        return html
    # 管理员模式：隐藏提权横幅
    return html.replace('<div class="banner" id="adminBanner">',
                        '<div class="banner" id="adminBanner" style="display:none">')
