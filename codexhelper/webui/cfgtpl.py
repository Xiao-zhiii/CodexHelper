# -*- coding: utf-8 -*-
"""配置中心（收编项目）的 HTML 模板（v1.6.0 收编时随 cfgcenter.py 一起进来）。

为什么单独成文件：它是一段 **1526 行的纯数据常量**，占 cfgcenter.py 的 38.6%，
和任何后端逻辑都没有耦合。混在一起让 cfgcenter.py 看起来像 4000 行的巨石，
实际上逻辑只有一半。

本文件**不含任何逻辑**，只放模板字符串。改样式/结构请直接改这里；
改完必须跑 preflight（它会校验 JS 语法与页签结构）。
"""

# r-string：模板里有大量 \d \s 之类的正则与 CSS 转义，不能让它被 Python 解释
HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Helper</title>
  <style>
    /* ==========================================================================
       设计令牌 · Design Tokens
       三层结构：调色板 → 语义色 → 组件样式。组件只消费语义色，
       因此明暗模式 / 高对比度切换时无需改动任何组件规则。
       对比度目标：正文 ≥ 4.5:1，UI 图形与焦点环 ≥ 3:1（WCAG AA）。
       ========================================================================== */
    :root {
      color-scheme: light dark;

      /* 间距刻度：4 的倍数，保证栅格节奏一致 */
      --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
      --sp-5: 20px; --sp-6: 24px; --sp-8: 32px; --sp-10: 40px;

      /* 圆角刻度：由小到大，容器越大半径越大 */
      --r-xs: 5px; --r-sm: 7px; --r-md: 10px; --r-lg: 14px;
      --r-xl: 20px; --r-pill: 999px;

      /* 字体：优先系统可变字体，中文回退到雅黑 / 苹方 */
      --font-sans: "Segoe UI Variable Display", "Segoe UI", -apple-system,
                   BlinkMacSystemFont, "Microsoft YaHei UI", "PingFang SC",
                   "Hiragino Sans GB", "Noto Sans CJK SC", Arial, sans-serif;
      --font-mono: "Cascadia Mono", "Cascadia Code", "SF Mono", ui-monospace,
                   Consolas, "Microsoft YaHei UI", monospace;

      /* 字号刻度 */
      --fs-11: 11px; --fs-12: 12px; --fs-13: 13px; --fs-14: 14px;
      --fs-16: 16px; --fs-18: 18px; --fs-22: 22px; --fs-28: 28px;

      /* 动效：统一的缓动曲线与时长，禁止 ease-in-out / linear 的机械感 */
      --ease: cubic-bezier(.32, .72, 0, 1);
      --ease-out: cubic-bezier(.16, 1, .3, 1);
      --dur-fast: 120ms; --dur: 200ms; --dur-slow: 360ms;

      /* ---- 语义色（浅色）---- */
      --bg: #f2f4f7;
      --surface: #ffffff;
      --surface-2: #f8fafc;
      --surface-3: #eef2f7;
      --panel: #ffffff;                       /* 兼容旧名 */
      --line: rgba(16, 24, 40, .09);
      --line-strong: rgba(16, 24, 40, .17);
      --text: #101828;
      --text-2: #3a4553;
      --muted: #5b6472;
      --text-disabled: #98a2b3;
      --surface-disabled: #f2f4f7;

      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-fg: #ffffff;
      --accent-dark: #1d4ed8;                 /* 强调文字（白底 6.7:1）*/
      --accent-soft: #eff6ff;
      --accent-line: #bfdbfe;
      --soft: #eff6ff;                        /* 兼容旧名 */

      --ok: #067647;   --ok-soft: #ecfdf3;   --ok-line: #a6f4c5;
      --warn: #a16207; --warn-soft: #fff8e1; --warn-line: #f0d68a;
      --danger: #b42318; --danger-soft: #fef3f2; --danger-line: #fda29b;
      --info-soft: #f2f4f7; --info-line: rgba(16, 24, 40, .14); --info-text: #3a4553;

      /* 代码 / 日志控制台：始终保持深色，模拟终端语义 */
      --code-bg: #0f1626;
      --code-fg: #d5e0f0;

      /* 分层阴影：大扩散、低透明度，避免生硬的硬投影 */
      --shadow-xs: 0 1px 2px rgba(16, 24, 40, .05);
      --shadow-sm: 0 1px 3px rgba(16, 24, 40, .06), 0 1px 2px rgba(16, 24, 40, .04);
      --shadow: 0 4px 12px -2px rgba(16, 24, 40, .07), 0 2px 6px -2px rgba(16, 24, 40, .05);
      --shadow-lg: 0 20px 40px -16px rgba(16, 24, 40, .16), 0 4px 12px -4px rgba(16, 24, 40, .08);
      --ring: 0 0 0 3px rgba(37, 99, 235, .30);
    }

    /* ---- 暗色模式：语义色整体换挡，组件规则零改动 ---- */
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #16181d;
        --surface: #1c1f26;
        --surface-2: #22262e;
        --surface-3: #2a2f38;
        --panel: #1c1f26;
        --line: rgba(255, 255, 255, .09);
        --line-strong: rgba(255, 255, 255, .18);
        --text: #e7eaf0;
        --text-2: #c2c8d4;
        --muted: #98a1b2;
        --text-disabled: #5c6472;
        --surface-disabled: #22262e;

        --accent: #2b6df0;
        --accent-hover: #1d5fd6;
        --accent-fg: #ffffff;
        --accent-dark: #8ab4ff;
        --accent-soft: rgba(43, 109, 240, .20);
        --accent-line: #2f4d82;
        --soft: rgba(43, 109, 240, .20);

        --ok: #5fd39a;   --ok-soft: rgba(95, 211, 154, .13);   --ok-line: rgba(95, 211, 154, .38);
        --warn: #f5c565; --warn-soft: rgba(245, 197, 101, .13); --warn-line: rgba(245, 197, 101, .38);
        --danger: #ff8a80; --danger-soft: rgba(255, 138, 128, .13); --danger-line: rgba(255, 138, 128, .38);
        --info-soft: rgba(255, 255, 255, .06); --info-line: rgba(255, 255, 255, .16); --info-text: #c2c8d4;

        --code-bg: #0b0e15;
        --code-fg: #cfdaeb;

        --shadow-xs: 0 1px 2px rgba(0, 0, 0, .30);
        --shadow-sm: 0 1px 3px rgba(0, 0, 0, .36), 0 1px 2px rgba(0, 0, 0, .24);
        --shadow: 0 4px 14px -2px rgba(0, 0, 0, .40), 0 2px 6px -2px rgba(0, 0, 0, .28);
        --shadow-lg: 0 24px 48px -18px rgba(0, 0, 0, .55), 0 6px 16px -6px rgba(0, 0, 0, .35);
        --ring: 0 0 0 3px rgba(138, 180, 255, .38);
      }
    }

    * { box-sizing: border-box; }

    ::selection { background: var(--accent-soft); color: var(--text); }

    body {
      margin: 0;
      min-width: 320px;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      font-size: var(--fs-14);
      line-height: 1.5;
      letter-spacing: .01em;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }

    .shell {
      max-width: 1200px;
      margin: 0 auto;
      padding: var(--sp-6) var(--sp-6) var(--sp-8);
    }

    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: var(--sp-4);
      margin-bottom: var(--sp-5);
    }

    h1 {
      margin: 0;
      font-size: var(--fs-22);
      line-height: 1.25;
      font-weight: 650;
      letter-spacing: -.01em;
    }

    .subtitle {
      margin: var(--sp-1) 0 0;
      color: var(--muted);
      font-size: var(--fs-13);
      line-height: 1.55;
      max-width: 68ch;
    }

    .actions {
      display: flex;
      align-items: center;
      gap: var(--sp-2);
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    /* ---- 按钮 ---- */
    button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border: 1px solid var(--line-strong);
      background: var(--surface);
      color: var(--text);
      border-radius: var(--r-sm);
      min-height: 34px;
      padding: 0 var(--sp-3);
      font: inherit;
      font-size: var(--fs-13);
      font-weight: 550;
      cursor: pointer;
      white-space: nowrap;
      box-shadow: var(--shadow-xs);
      transition: background var(--dur-fast) var(--ease),
                  border-color var(--dur-fast) var(--ease),
                  color var(--dur-fast) var(--ease),
                  transform var(--dur-fast) var(--ease),
                  box-shadow var(--dur-fast) var(--ease);
    }

    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: var(--accent-fg);
      box-shadow: 0 1px 2px rgba(16, 24, 40, .12);
    }

    button:hover { background: var(--surface-2); border-color: var(--line-strong); }
    button.primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
    button:active { transform: scale(.985); }
    button.primary:active { transform: scale(.985); }

    /* 键盘可达性：每个可交互元素都有可见焦点环 */
    :focus-visible {
      outline: none;
      box-shadow: var(--ring), var(--shadow-xs);
      border-radius: var(--r-sm);
    }
    input:focus-visible,
    button:focus-visible,
    summary:focus-visible {
      outline: none;
      box-shadow: var(--ring);
    }
    input[type="text"]:focus-visible { border-color: var(--accent); }

    .layout {
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      gap: var(--sp-4);
      align-items: start;
    }

    /* 容器：发丝级描边 + 分层柔和阴影，弱化“边框盒子”的观感 */
    .panel {
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--r-lg);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .sidebar {
      min-width: 0;
      padding: var(--sp-4);
      position: sticky;
      top: var(--sp-4);
      max-height: calc(100vh - var(--sp-8));
      overflow: auto;
    }

    .field {
      display: grid;
      gap: 6px;
      margin-bottom: var(--sp-3);
    }

    label {
      color: var(--muted);
      font-size: var(--fs-12);
      font-weight: 550;
    }

    input[type="text"] {
      width: 100%;
      border: 1px solid var(--line-strong);
      border-radius: var(--r-sm);
      min-height: 34px;
      padding: 0 10px;
      font: inherit;
      font-size: var(--fs-13);
      color: var(--text);
      background: var(--surface);
      transition: border-color var(--dur-fast) var(--ease),
                  box-shadow var(--dur-fast) var(--ease);
    }
    input[type="text"]::placeholder { color: var(--text-disabled); }

    input[type="checkbox"] {
      width: 16px;
      height: 16px;
      accent-color: var(--accent);
      cursor: pointer;
    }

    .toggle {
      display: flex;
      align-items: center;
      gap: var(--sp-2);
      margin: var(--sp-2) 0 var(--sp-4);
      color: var(--text);
      font-size: var(--fs-13);
      cursor: pointer;
      user-select: none;
    }

    .path-block {
      display: grid;
      gap: 6px;
      border-top: 1px solid var(--line);
      padding-top: var(--sp-4);
      margin-top: var(--sp-4);
    }

    .path-line {
      overflow-wrap: anywhere;
      line-height: 1.5;
      color: var(--text-2);
      background: var(--surface-2);
      border: 1px solid var(--line);
      border-radius: var(--r-sm);
      padding: 7px var(--sp-2);
      font-size: var(--fs-12);
      font-family: var(--font-mono);
    }

    .status {
      margin-top: var(--sp-3);
      color: var(--muted);
      font-size: var(--fs-12);
      line-height: 1.6;
      overflow-wrap: anywhere;
    }

    /* ---- 标签栏：分段控件形态，替代原来的下边框 + 描边胶囊 ---- */
    .tabs {
      display: flex;
      gap: var(--sp-1);
      padding: var(--sp-1);
      border-bottom: 1px solid var(--line);
      background: var(--surface-2);
      overflow-x: auto;
      scrollbar-width: none;
    }
    .tabs::-webkit-scrollbar { height: 0; }

    .tab {
      flex: 0 0 auto;
      min-height: 32px;
      padding: 0 var(--sp-3);
      border-color: transparent;
      background: transparent;
      color: var(--muted);
      font-size: var(--fs-13);
      font-weight: 550;
      border-radius: var(--r-sm);
      box-shadow: none;
      white-space: nowrap;
    }

    .tab:hover { background: var(--surface-3); color: var(--text-2); }

    .tab.active {
      background: var(--surface);
      border-color: var(--line);
      color: var(--accent-dark);
      font-weight: 600;
      box-shadow: var(--shadow-xs);
    }

    .content {
      min-width: 0;
      padding: var(--sp-5);
      min-height: 520px;
    }

    .summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--sp-2);
      margin-bottom: var(--sp-4);
    }

    .metric {
      border: 1px solid var(--line);
      border-radius: var(--r-md);
      padding: var(--sp-3);
      background: var(--surface-2);
      min-height: 76px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 5px;
    }

    .metric .name {
      color: var(--muted);
      font-size: var(--fs-12);
      margin-bottom: 0;
    }

    .metric .value {
      font-size: var(--fs-16);
      font-weight: 600;
      overflow-wrap: anywhere;
      line-height: 1.35;
      letter-spacing: -.005em;
      font-variant-numeric: tabular-nums;
    }

    .table-wrap {
      border: 1px solid var(--line);
      border-radius: var(--r-md);
      overflow: auto;
      background: var(--surface);
      max-height: 70vh;
    }

    table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      table-layout: fixed;
      min-width: 720px;
    }

    th, td {
      border-bottom: 1px solid var(--line);
      padding: var(--sp-2) var(--sp-3);
      text-align: left;
      vertical-align: top;
      line-height: 1.55;
      font-size: var(--fs-13);
      overflow-wrap: anywhere;
    }

    td { white-space: pre-wrap; color: var(--text-2); }
    td:first-child { color: var(--text); font-weight: 550; }

    tbody tr { transition: background var(--dur-fast) var(--ease); }
    tbody tr:hover { background: var(--surface-2); }

    th {
      color: var(--muted);
      background: var(--surface-2);
      font-weight: 600;
      font-size: var(--fs-12);
      position: sticky;
      top: 0;
      z-index: 1;
      backdrop-filter: blur(8px);
    }

    tr:last-child td { border-bottom: 0; }
    td:nth-child(1), th:nth-child(1) { width: 34%; }
    td:nth-child(2), th:nth-child(2) { width: 15%; }
    td:nth-child(3), th:nth-child(3) { width: 51%; }

    .notice {
      border: 1px solid var(--warn-line);
      background: var(--warn-soft);
      color: var(--warn);
      border-radius: var(--r-sm);
      padding: var(--sp-2) var(--sp-3);
      margin-bottom: var(--sp-3);
      font-size: var(--fs-13);
      line-height: 1.55;
    }

    .section-title {
      margin: var(--sp-6) 0 var(--sp-2);
      color: var(--text);
      font-size: var(--fs-16);
      font-weight: 620;
      letter-spacing: -.005em;
    }

    .section-title:first-child {
      margin-top: 0;
    }

    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--sp-3);
      margin: var(--sp-6) 0 var(--sp-2);
      flex-wrap: wrap;
    }

    .section-head .section-title {
      margin: 0;
    }

    .settings-extra {
      margin-top: var(--sp-3);
      border: 1px solid var(--line);
      border-radius: var(--r-md);
      background: var(--surface);
      overflow: hidden;
    }

    .settings-extra summary {
      cursor: pointer;
      padding: var(--sp-2) var(--sp-3);
      color: var(--text);
      background: var(--surface-2);
      font-weight: 600;
      font-size: var(--fs-13);
      list-style: none;
      transition: background var(--dur-fast) var(--ease);
    }
    .settings-extra summary:hover { background: var(--surface-3); }

    .settings-extra summary::-webkit-details-marker {
      display: none;
    }

    .settings-extra-body {
      border-top: 1px solid var(--line);
      padding: var(--sp-3);
      background: var(--surface);
    }

    .provider-tools {
      display: flex;
      align-items: center;
      gap: var(--sp-2);
      color: var(--muted);
      font-size: var(--fs-12);
      flex-wrap: wrap;
    }

    .provider-tools button {
      min-height: 32px;
      padding: 0 var(--sp-2);
      font-size: var(--fs-12);
    }

    .provider-summary-actions {
      display: flex;
      align-items: center;
      gap: var(--sp-2);
      flex: 0 0 auto;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .provider-summary-actions button {
      min-height: 32px;
      padding: 0 var(--sp-3);
      font-size: var(--fs-12);
    }

    /* 禁用态：用语义色而非降透明度，保证文字仍然可读 */
    button:disabled {
      cursor: not-allowed;
      background: var(--surface-disabled);
      border-color: var(--line);
      color: var(--text-disabled);
      box-shadow: none;
    }
    button:disabled:hover { background: var(--surface-disabled); border-color: var(--line); }
    button.primary:disabled {
      background: var(--surface-disabled);
      border-color: var(--line);
      color: var(--text-disabled);
    }

    .provider-groups {
      display: grid;
      gap: var(--sp-3);
    }

    .provider-group {
      border: 1px solid var(--line);
      border-radius: var(--r-md);
      background: var(--surface);
      overflow: hidden;
    }

    .provider-group-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--sp-3);
      padding: var(--sp-2) var(--sp-3);
      background: var(--surface-2);
      border-bottom: 1px solid var(--line);
      font-weight: 600;
      font-size: var(--fs-13);
      color: var(--text);
    }

    .provider-count {
      color: var(--muted);
      font-weight: 500;
      font-size: var(--fs-12);
    }

    .provider-list {
      display: grid;
      gap: var(--sp-2);
      padding: var(--sp-3);
      background: var(--surface-2);
    }

    .provider-card {
      border: 1px solid var(--line);
      border-radius: var(--r-md);
      background: var(--surface);
      overflow: hidden;
      transition: border-color var(--dur) var(--ease),
                  box-shadow var(--dur) var(--ease);
    }
    .provider-card:hover { border-color: var(--line-strong); }
    .provider-card[open] { box-shadow: var(--shadow-sm); }

    .provider-card.current {
      border-color: var(--accent-line);
      box-shadow: 0 0 0 1px var(--accent-line);
    }

    .provider-card summary {
      list-style: none;
      cursor: pointer;
      padding: var(--sp-3);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--sp-3);
      transition: background var(--dur-fast) var(--ease);
    }
    .provider-card summary:hover { background: var(--surface-2); }

    .provider-card summary::-webkit-details-marker {
      display: none;
    }

    .provider-main {
      display: flex;
      align-items: center;
      gap: var(--sp-3);
      min-width: 0;
      flex: 1;
    }

    .provider-avatar {
      width: 36px;
      height: 36px;
      border-radius: var(--r-sm);
      display: flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      background: color-mix(in srgb, var(--provider-color, #5aa69e) 14%, var(--surface));
      border: 1px solid color-mix(in srgb, var(--provider-color, #5aa69e) 38%, var(--line));
      color: var(--provider-color, #337f78);
      font-weight: 700;
      font-size: var(--fs-16);
    }

    .provider-text {
      min-width: 0;
      flex: 1;
      display: grid;
      gap: 5px;
    }

    .provider-title-row,
    .provider-meta-row {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      min-width: 0;
    }

    .provider-title-row h3 {
      margin: 0;
      font-size: var(--fs-14);
      font-weight: 600;
      line-height: 1.3;
      overflow-wrap: anywhere;
    }

    .provider-url-row {
      color: var(--muted);
      font-size: var(--fs-12);
      line-height: 1.4;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--font-mono);
    }

    .provider-meta-row {
      color: var(--muted);
      font-size: var(--fs-12);
      line-height: 1.4;
    }

    /* ---- 徽章：全部走语义色，明暗模式自动适配 ---- */
    .badge {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--info-line);
      border-radius: var(--r-pill);
      padding: 1px 8px;
      background: var(--info-soft);
      color: var(--info-text);
      font-size: var(--fs-11);
      font-weight: 550;
      line-height: 1.5;
      max-width: 100%;
      overflow-wrap: anywhere;
    }

    .badge.current {
      border-color: var(--accent-line);
      background: var(--accent-soft);
      color: var(--accent-dark);
      font-weight: 650;
    }

    .badge.key {
      border-color: var(--line-strong);
      background: var(--surface-3);
      color: var(--text-2);
    }

    .badge.error {
      border-color: var(--danger-line);
      background: var(--danger-soft);
      color: var(--danger);
    }

    .badge.testing,
    .badge.degraded {
      border-color: var(--warn-line);
      background: var(--warn-soft);
      color: var(--warn);
    }

    .badge.success {
      border-color: var(--ok-line);
      background: var(--ok-soft);
      color: var(--ok);
    }

    .provider-chevron {
      color: var(--muted);
      transition: transform var(--dur) var(--ease);
      flex: 0 0 auto;
      font-size: var(--fs-18);
      line-height: 1;
    }

    .provider-card[open] .provider-chevron {
      transform: rotate(180deg);
    }

    .provider-details {
      border-top: 1px solid var(--line);
      background: var(--surface-2);
      padding: var(--sp-3);
    }

    .provider-detail-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--sp-2);
    }

    .provider-detail-item {
      border: 1px solid var(--line);
      border-radius: var(--r-sm);
      background: var(--surface);
      padding: var(--sp-2) var(--sp-3);
      min-width: 0;
    }

    .provider-detail-item.full {
      grid-column: 1 / -1;
    }

    .provider-detail-label {
      color: var(--muted);
      font-size: var(--fs-12);
      margin-bottom: 3px;
    }

    .provider-detail-value {
      color: var(--text);
      font-size: var(--fs-13);
      line-height: 1.5;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }

    .provider-detail-value a {
      color: var(--accent-dark);
      text-decoration: none;
    }

    .provider-detail-value a:hover {
      text-decoration: underline;
    }

    .error,
    .notice.error {
      border-color: var(--danger-line);
      background: var(--danger-soft);
      color: var(--danger);
    }

    pre {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-family: var(--font-mono);
      font-size: var(--fs-13);
      line-height: 1.6;
      padding: var(--sp-3);
    }

    .raw-switch {
      display: flex;
      gap: var(--sp-2);
      margin-bottom: var(--sp-3);
      flex-wrap: wrap;
    }

    .hidden { display: none; }

    /* ---- 滚动条：细窄、无按钮，避免抢占注意力 ---- */
    * { scrollbar-width: thin; scrollbar-color: var(--line-strong) transparent; }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb {
      background: var(--line-strong);
      border-radius: var(--r-pill);
      border: 3px solid transparent;
      background-clip: content-box;
    }
    ::-webkit-scrollbar-thumb:hover { background: var(--muted); background-clip: content-box; }
    ::-webkit-scrollbar-corner { background: transparent; }

    /* ---- 响应式 ---- */
    @media (max-width: 1040px) {
      .layout { grid-template-columns: 260px minmax(0, 1fr); }
      .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 900px) {
      .shell { padding: var(--sp-4) var(--sp-4) var(--sp-6); }
      header { align-items: flex-start; flex-direction: column; gap: var(--sp-3); }
      .actions { justify-content: flex-start; }
      .layout { grid-template-columns: 1fr; }
      .sidebar { position: static; max-height: none; }
      .summary { grid-template-columns: 1fr; }
      .provider-detail-grid { grid-template-columns: 1fr; }
      .provider-card summary { align-items: flex-start; }
      .provider-url-row { white-space: normal; }
      .content { padding: var(--sp-4); }
      h1 { font-size: var(--fs-18); }
    }

    /* ---- 尊重系统的“减弱动态效果”设置 ---- */
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: .001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: .001ms !important;
        scroll-behavior: auto !important;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>Codex Helper</h1>
        <p class="subtitle">本机系统信息、Codex 配置和 CC Switch 文件夹查看器</p>
      </div>
      <div class="actions">
        <button class="primary" id="refreshBtn">刷新</button>
        <button id="repairBtn">一键修复</button>
        <button id="shutdownBtn">关闭程序</button>
      </div>
    </header>

    <main class="layout">
      <aside class="panel sidebar">
        <div class="field">
          <label for="codexPath">自定义 .codex 路径</label>
          <input id="codexPath" type="text" placeholder="留空则自动检测">
        </div>
        <div class="field">
          <label for="ccPath">自定义 .cc-switch 路径</label>
          <input id="ccPath" type="text" placeholder="留空则自动检测">
        </div>
        <div class="field">
          <label for="codexPlusPath">自定义 Codex++ 路径</label>
          <input id="codexPlusPath" type="text" placeholder="留空则自动检测">
        </div>
        <label class="toggle">
          <input id="sensitiveToggle" type="checkbox">
          <span>显示敏感值</span>
        </label>
        <button id="applyPathBtn">应用路径</button>

        <div class="path-block">
          <label>当前 .codex</label>
          <div class="path-line" id="codexCurrent">-</div>
          <label>当前 .cc-switch</label>
          <div class="path-line" id="ccCurrent">-</div>
          <label>当前 Codex++</label>
          <div class="path-line" id="codexPlusCurrent">-</div>
          <label>Codex Helper 日志</label>
          <div class="path-line" id="logCurrent">-</div>
        </div>
        <div class="status" id="statusText">正在读取...</div>
      </aside>

      <section class="panel">
        <nav class="tabs" id="tabs" role="tablist" aria-label="配置分区">
          <button class="tab active" data-tab="system" role="tab" aria-selected="true" aria-controls="tab-system">系统信息</button>
          <button class="tab" data-tab="config" role="tab" aria-selected="false" aria-controls="tab-config">config.toml</button>
          <button class="tab" data-tab="auth" role="tab" aria-selected="false" aria-controls="tab-auth">auth.json</button>
          <button class="tab" data-tab="cc" role="tab" aria-selected="false" aria-controls="tab-cc">.cc-switch</button>
          <button class="tab" data-tab="codexplus" role="tab" aria-selected="false" aria-controls="tab-codexplus">Codex++</button>
          <button class="tab" data-tab="raw" role="tab" aria-selected="false" aria-controls="tab-raw">原始文件</button>
        </nav>
        <div class="content">
          <section id="tab-system" role="tabpanel" aria-label="系统信息"></section>
          <section id="tab-config" class="hidden" role="tabpanel" aria-label="config.toml"></section>
          <section id="tab-auth" class="hidden" role="tabpanel" aria-label="auth.json"></section>
          <section id="tab-cc" class="hidden" role="tabpanel" aria-label=".cc-switch"></section>
          <section id="tab-codexplus" class="hidden" role="tabpanel" aria-label="Codex++"></section>
          <section id="tab-raw" class="hidden" role="tabpanel" aria-label="原始文件"></section>
        </div>
      </section>
    </main>
  </div>

  <script>
    const state = {
      data: null,
      activeTab: "system",
      rawMode: "config",
      testResults: {},
      v1Notices: {}
    };

    const $ = (selector) => document.querySelector(selector);

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function rowsTable(rows, emptyText = "没有可显示的数据") {
      if (!rows || rows.length === 0) {
        return `<div class="notice">${escapeHtml(emptyText)}</div>`;
      }
      const body = rows.map(row => `
        <tr>
          <td>${escapeHtml(row.name)}</td>
          <td>${escapeHtml(row.type)}</td>
          <td>${escapeHtml(row.value)}</td>
        </tr>`).join("");
      return `
        <div class="table-wrap">
          <table>
            <thead><tr><th>项目</th><th>类型</th><th>内容</th></tr></thead>
            <tbody>${body}</tbody>
          </table>
        </div>`;
    }

    function renderSummary(systemRows) {
      const wanted = ["系统名称", "CPU", "GPU", "运行内存", "系统盘总容量", "系统盘可用容量"];
      const metrics = wanted.map(name => systemRows.find(row => row.name === name)).filter(Boolean);
      return `<div class="summary">${metrics.map(row => `
        <div class="metric">
          <div class="name">${escapeHtml(row.name)}</div>
          <div class="value">${escapeHtml(row.value)}</div>
        </div>`).join("")}</div>`;
    }

    function renderMetrics(rows, wanted) {
      const source = Array.isArray(rows) ? rows : [];
      const metrics = wanted
        .map(name => source.find(row => row.name === name))
        .filter(Boolean);
      if (metrics.length === 0) return "";
      return `<div class="summary">${metrics.map(row => `
        <div class="metric">
          <div class="name">${escapeHtml(row.name)}</div>
          <div class="value">${escapeHtml(row.value)}</div>
        </div>`).join("")}</div>`;
    }

    function renderSection(title, rows, emptyText) {
      return `<h2 class="section-title">${escapeHtml(title)}</h2>${rowsTable(rows, emptyText)}`;
    }

    function renderFocusedSettingsSection(title, rows, importantNames, emptyText) {
      const source = Array.isArray(rows) ? rows : [];
      if (source.length === 0) {
        return renderSection(title, source, emptyText);
      }
      const wanted = new Set(importantNames || []);
      let primary = source.filter(row => wanted.has(row.name));
      if (primary.length === 0) primary = source.slice(0, Math.min(6, source.length));
      const primaryKeys = new Set(primary.map(row => `${row.name}\u0000${row.type}\u0000${row.value}`));
      const secondary = source.filter(row => !primaryKeys.has(`${row.name}\u0000${row.type}\u0000${row.value}`));
      const extra = secondary.length
        ? `<details class="settings-extra">
            <summary>更多设置（${secondary.length} 项）</summary>
            <div class="settings-extra-body">${rowsTable(secondary)}</div>
          </details>`
        : "";
      return `<h2 class="section-title">${escapeHtml(title)}</h2>${rowsTable(primary, emptyText)}${extra}`;
    }

    function isWebUrl(value) {
      return /^https?:\/\//i.test(String(value || "").trim());
    }

    function cssColor(value) {
      const text = String(value || "").trim();
      return /^#[0-9a-f]{3,8}$/i.test(text) ? text : "#5aa69e";
    }

    function providerInitial(card) {
      const text = String(card?.name || card?.appLabel || "?").trim();
      return Array.from(text)[0] || "?";
    }

    function providerKeySummary(value) {
      const text = String(value || "").trim();
      if (!text || text === "未配置") return "未配置";
      if (text === "已配置") return "已配置";
      return "已显示";
    }

    function providerDetailItem(label, value, full = false, valueType = "text") {
      const text = String(value ?? "").trim();
      if (!text) return "";
      const valueHtml = valueType === "url" && isWebUrl(text)
        ? `<a href="${escapeHtml(text)}" target="_blank" rel="noreferrer">${escapeHtml(text)}</a>`
        : escapeHtml(text);
      return `
        <div class="provider-detail-item ${full ? "full" : ""}">
          <div class="provider-detail-label">${escapeHtml(label)}</div>
          <div class="provider-detail-value">${valueHtml}</div>
        </div>`;
    }

    function providerTestKey(sourceOrCard, appType, id) {
      if (typeof sourceOrCard === "object") {
        const card = sourceOrCard || {};
        return `${card.source || "ccSwitch"}:${card.appType || ""}:${card.id || ""}`;
      }
      return `${sourceOrCard || "ccSwitch"}:${appType || ""}:${id || ""}`;
    }

    function providerTestLabel(result) {
      if (!result) return { text: "未测试", klass: "" };
      if (result.pending) return { text: "测试中", klass: "testing" };
      if (result.status === "operational") return { text: "正常", klass: "success" };
      if (result.status === "degraded") return { text: "较慢", klass: "degraded" };
      return { text: "失败", klass: "error" };
    }

    function providerTestBadge(card) {
      const result = state.testResults[providerTestKey(card)];
      const label = providerTestLabel(result);
      return `<span class="badge ${label.klass}">测试：${escapeHtml(label.text)}</span>`;
    }

    function providerTestDetail(card) {
      if (!card.testable) return card.testUnavailableReason || "当前配置无法测试";
      const result = state.testResults[providerTestKey(card)];
      if (!result) return "未测试";
      if (result.pending) return "正在测试...";
      const parts = [
        providerTestLabel(result).text,
        result.message || "",
        result.responseTimeMs != null ? `耗时：${result.responseTimeMs} ms` : "",
        result.httpStatus != null ? `HTTP：${result.httpStatus}` : "",
        result.retryCount ? `重试：${result.retryCount}` : "",
        result.modelUsed ? `模型：${result.modelUsed}` : "",
        result.modelsCount != null ? `模型列表：${result.modelsCount} 个` : "",
        result.modelsEndpoint ? `模型列表端点：${result.modelsEndpoint}` : "",
        result.v1Added ? "已自动补充 /v1 后测试通过" : "",
        result.endpoint ? `端点：${result.endpoint}` : "",
        result.responsePreview ? `响应预览：${result.responsePreview}` : "",
        result.testedAt ? `时间：${result.testedAt}` : ""
      ].filter(Boolean);
      return parts.join("；");
    }

    function currentPathPayload() {
      return {
        codexPath: $("#codexPath").value.trim(),
        ccPath: $("#ccPath").value.trim(),
        codexPlusPath: $("#codexPlusPath").value.trim()
      };
    }

    async function postJson(url, payload) {
      // X-CH-Token：本地服务的写操作令牌，由 page.py 渲染页面时注入到
      // window.CH_TOKEN。端口写在 port.txt，本机任何进程都能直达这些端点，
      // 少了这个头服务端会回 401。
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CH-Token": window.CH_TOKEN || ""
        },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error((data.errors || []).join("；") || `请求失败：${response.status}`);
      }
      return data;
    }

    function rememberTestResult(result) {
      if (!result) return;
      state.testResults[providerTestKey(result.source, result.appType, result.id)] = result;
      notifyV1Added(result);
    }

    function notifyV1Added(result) {
      if (!result?.v1Added) return;
      const key = providerTestKey(result.source, result.appType, result.id);
      if (state.v1Notices[key]) return;
      state.v1Notices[key] = true;
      alert(`「${result.name || result.id}」已自动补充 /v1 后测试通过。建议把该供应商 Base URL 调整为包含 /v1 的地址。`);
    }

    function providerCardsForSource(source) {
      if (!state.data) return [];
      if (source === "codexPlus") return state.data.codexPlus?.relayProfileCards || [];
      return state.data.ccSwitch?.database?.providerCards || [];
    }

    async function runProviderTest(source, appType, id) {
      const key = providerTestKey(source, appType, id);
      state.testResults[key] = { pending: true, source, appType, id };
      render();
      try {
        const data = await postJson("/api/test-provider", { ...currentPathPayload(), source, appType, id });
        rememberTestResult(data.result);
      } catch (error) {
        state.testResults[key] = {
          source,
          appType,
          id,
          success: false,
          status: "failed",
          message: String(error.message || error),
          testedAt: new Date().toLocaleString()
        };
      }
      render();
    }

    async function runProviderTestAll(source) {
      providerCardsForSource(source).forEach(card => {
        state.testResults[providerTestKey(card)] = {
          pending: true,
          source: card.source || source,
          appType: card.appType || "",
          id: card.id || ""
        };
      });
      render();
      try {
        const data = await postJson("/api/test-all-providers", { ...currentPathPayload(), source });
        (data.results || []).forEach(rememberTestResult);
      } catch (error) {
        providerCardsForSource(source).forEach(card => {
          state.testResults[providerTestKey(card)] = {
            source: card.source || source,
            appType: card.appType || "",
            id: card.id || "",
            success: false,
            status: "failed",
            message: String(error.message || error),
            testedAt: new Date().toLocaleString()
          };
        });
      }
      render();
    }

    function renderProviderCard(card) {
      const baseUrl = card.baseUrl || "未配置";
      const keyState = providerKeySummary(card.apiKey);
      const healthClass = card.healthState === "error" ? "badge error" : "badge";
      const statusClass = card.isCurrent ? "badge current" : "badge";
      const source = card.source || "ccSwitch";
      const canTest = card.testable !== false;
      const disabledReason = card.testUnavailableReason || "当前配置无法测试";
      const detailRows = [
        providerDetailItem("供应商 ID", card.id, true),
        providerDetailItem("分类", card.category),
        providerDetailItem("Base URL", baseUrl, true),
        providerDetailItem("API Key/Token", card.apiKey || "未配置", true),
        providerDetailItem("官网链接", card.websiteUrl || "未配置", true, card.websiteUrl ? "url" : "text"),
        providerDetailItem("模型", card.model || "未配置"),
        providerDetailItem("API 格式", card.apiFormat || "未指定"),
        providerDetailItem("自定义端点数量", card.endpointCount ?? "0"),
        providerDetailItem("健康状态", card.health || "默认健康（无记录）", true),
        providerDetailItem("排序", card.sortIndex || "未设置"),
        providerDetailItem("图标", card.icon || "未设置"),
        providerDetailItem("其他", card.extra || "无", true),
        providerDetailItem("测试结果", providerTestDetail(card), true),
        providerDetailItem("添加时间", card.createdAt || ""),
        providerDetailItem("备注", card.notes || "", true),
        providerDetailItem("故障转移", card.inFailoverQueue ? "已加入队列" : "", true)
      ].filter(Boolean).join("");

      return `
        <details class="provider-card ${card.isCurrent ? "current" : ""}">
          <summary>
            <div class="provider-main">
              <div class="provider-avatar" style="--provider-color: ${cssColor(card.iconColor)}">${escapeHtml(providerInitial(card))}</div>
              <div class="provider-text">
                <div class="provider-title-row">
                  <h3>${escapeHtml(card.name || card.id)}</h3>
                  <span class="${statusClass}">${escapeHtml(card.status || "备用")}</span>
                  <span class="badge">${escapeHtml(card.category || "未分类")}</span>
                  ${providerTestBadge(card)}
                </div>
                <div class="provider-url-row" title="${escapeHtml(baseUrl)}">${escapeHtml(baseUrl)}</div>
                <div class="provider-meta-row">
                  <span>模型：${escapeHtml(card.model || "未配置")}</span>
                  <span class="badge key">Key：${escapeHtml(keyState)}</span>
                  <span class="${healthClass}">健康：${escapeHtml(card.healthState === "error" ? "异常" : "正常")}</span>
                </div>
              </div>
            </div>
            <div class="provider-summary-actions">
              <button
                type="button"
                data-test-provider="1"
                data-source="${escapeHtml(source)}"
                data-app-type="${escapeHtml(card.appType || "")}"
                data-provider-id="${escapeHtml(card.id || "")}"
                ${canTest ? "" : "disabled"}
                title="${escapeHtml(canTest ? "测试供应商" : disabledReason)}"
              >测试</button>
              <span class="provider-chevron">⌄</span>
            </div>
          </summary>
          <div class="provider-details">
            <div class="provider-detail-grid">${detailRows}</div>
          </div>
        </details>`;
    }

    function renderProviderCards(cards, fallbackRows, emptyText, options = {}) {
      const source = Array.isArray(cards) ? cards : [];
      const title = options.title || "供应商详情";
      const sourceType = options.source || "ccSwitch";
      const scope = options.scope || (sourceType === "codexPlus" ? "codexplus" : "cc");
      if (source.length === 0) {
        return renderSection(title, fallbackRows || [], emptyText);
      }

      const groups = [];
      const byApp = new Map();
      source.forEach(card => {
        const app = card.appLabel || card.appType || "其他";
        if (!byApp.has(app)) {
          const group = { app, cards: [] };
          byApp.set(app, group);
          groups.push(group);
        }
        byApp.get(app).cards.push(card);
      });

      const groupHtml = groups.map(group => `
        <div class="provider-group">
          <div class="provider-group-title">
            <span>${escapeHtml(group.app)}</span>
            <span class="provider-count">${group.cards.length} 个供应商</span>
          </div>
          <div class="provider-list">
            ${group.cards.map(card => renderProviderCard({ ...card, source: card.source || sourceType })).join("")}
          </div>
        </div>`).join("");

      return `
        <div class="section-head">
          <h2 class="section-title">${escapeHtml(title)}</h2>
          <div class="provider-tools">
            <span>共 ${source.length} 个</span>
            <button data-test-all="1" data-source="${escapeHtml(sourceType)}" type="button">一键测试</button>
            <button data-provider-action="expand" data-provider-scope="${escapeHtml(scope)}" type="button">全部展开</button>
            <button data-provider-action="collapse" data-provider-scope="${escapeHtml(scope)}" type="button">全部收起</button>
          </div>
        </div>
        <div class="provider-groups">${groupHtml}</div>`;
    }

    function renderCcSwitch(cc) {
      if (!cc || !cc.found) {
        return rowsTable(cc?.rows || [], ".cc-switch 文件夹为空或未找到");
      }
      const db = cc.database || {};
      const settings = cc.settings || {};
      const ccImportantSettings = [
        "界面语言",
        "主页面可见应用",
        "主页面本地代理功能",
        "切换时保留 Codex 官方登录",
        "统一 Codex 会话历史",
        "开机自启",
        "自动备份间隔小时",
        "备份保留数量"
      ];
      const errors = [...(db.errors || [])];
      if (settings.error) errors.push(settings.error);
      const errorBlock = errors.length
        ? errors.map(error => `<div class="notice error">${escapeHtml(error)}</div>`).join("")
        : "";
      return `
        ${errorBlock}
        ${renderMetrics(db.overview || [], ["数据库版本", "供应商数量", "MCP 数量", "Skills 数量", "请求日志数量", "备份文件数量"])}
        ${renderSection("当前供应商", db.currentProviders || [], "没有当前供应商信息")}
        ${renderFocusedSettingsSection("CC Switch 设置", settings.rows || [], ccImportantSettings, "settings.json 没有可显示内容")}
        ${renderSection("本地代理与接管", db.proxy || [], "没有代理配置")}
        ${renderProviderCards(db.providerCards || [], db.providers || [], "没有供应商配置", { source: "ccSwitch", title: "供应商详情", scope: "cc" })}
        ${renderSection("MCP 服务器", db.mcp || [], "没有 MCP 服务器")}
        ${renderSection("Skills", db.skills || [], "没有安装的 Skills")}
        ${renderSection("Skill 仓库", db.skillRepos || [], "没有 Skill 仓库")}
        ${renderSection("数据库设置表", db.settingsTable || [], "settings 表为空")}
        ${renderSection("目录文件", cc.rows || [], ".cc-switch 文件夹为空")}
      `;
    }

    function renderCodexPlus(codexPlus) {
      if (!codexPlus || !codexPlus.found) {
        return rowsTable(codexPlus?.rows || [], "未找到 Codex++ 状态目录 .codex-session-delete");
      }
      const codexPlusImportantSettings = [
        "启动模式",
        "增强注入",
        "供应商配置总开关",
        "Provider 同步",
        "当前中转 ID",
        "当前聚合中转 ID",
        "中转测试模型",
        "Codex App 路径",
        "强制中文界面"
      ];
      const errors = codexPlus.errors || [];
      const errorBlock = errors.length
        ? errors.map(error => `<div class="notice error">${escapeHtml(error)}</div>`).join("")
        : "";
      return `
        ${errorBlock}
        ${renderMetrics(codexPlus.overview || [], ["日志大小", "Provider 备份数量"])}
        ${renderSection("配置位置", codexPlus.overview || [], "没有配置位置")}
        ${renderSection("运行状态", codexPlus.status || [], "没有运行状态")}
        ${renderSection("Codex 注入状态", codexPlus.codexInjection || [], "没有 Codex 注入信息")}
        ${renderProviderCards(codexPlus.relayProfileCards || [], codexPlus.relayProfiles || [], "没有中转配置", { source: "codexPlus", title: "中转配置", scope: "codexplus" })}
        ${renderSection("聚合中转", codexPlus.aggregateProfiles || [], "没有聚合中转配置")}
        ${renderFocusedSettingsSection("增强与同步设置", codexPlus.settings || [], codexPlusImportantSettings, "settings.json 没有可显示内容")}
        ${renderSection("目录文件", codexPlus.files || [], "Codex++ 状态目录为空")}
      `;
    }

    function notice(error) {
      if (!error) return "";
      const klass = error.includes("未找到") ? "notice" : "notice error";
      return `<div class="${klass}">${escapeHtml(error)}</div>`;
    }

    function render() {
      const data = state.data;
      if (!data) return;
      $("#codexCurrent").textContent = data.paths.codex || "未找到";
      $("#ccCurrent").textContent = data.paths.ccSwitch || "未找到";
      $("#codexPlusCurrent").textContent = data.paths.codexPlus || "未找到";
      $("#logCurrent").textContent = data.paths.log || "未设置";
      $("#statusText").textContent = `更新时间：${data.generatedAt}；config.toml ${data.config.found ? "已找到" : "未找到"}；auth.json ${data.auth.found ? "已找到" : "未找到"}；cc-switch.db ${data.ccSwitch?.database?.found ? "已找到" : "未找到"}；Codex++ ${data.codexPlus?.found ? "已找到" : "未找到"}`;

      $("#tab-system").innerHTML = renderSummary(data.system) + rowsTable(data.system) + renderSection("用户变量", data.userEnvironment || [], "没有读取到用户变量");
      $("#tab-config").innerHTML = notice(data.config.error) + rowsTable(data.config.rows, "config.toml 没有解析出参数");
      $("#tab-auth").innerHTML = notice(data.auth.error) + rowsTable(data.auth.rows, "auth.json 没有解析出参数");
      $("#tab-cc").innerHTML = renderCcSwitch(data.ccSwitch);
      $("#tab-codexplus").innerHTML = renderCodexPlus(data.codexPlus);
      renderRaw();
      showTab(state.activeTab);
    }

    function renderRaw() {
      const data = state.data;
      const raw = state.rawMode === "config" ? data.config.raw : data.auth.raw;
      const label = state.rawMode === "config" ? "config.toml" : "auth.json";
      $("#tab-raw").innerHTML = `
        <div class="raw-switch">
          <button class="${state.rawMode === "config" ? "primary" : ""}" data-raw="config">config.toml</button>
          <button class="${state.rawMode === "auth" ? "primary" : ""}" data-raw="auth">auth.json</button>
        </div>
        <div class="table-wrap"><pre>${escapeHtml(raw || `${label} 没有可显示内容`)}</pre></div>`;
      document.querySelectorAll("[data-raw]").forEach(button => {
        button.addEventListener("click", () => {
          state.rawMode = button.dataset.raw;
          renderRaw();
        });
      });
    }

    async function loadSnapshot() {
      $("#statusText").textContent = "正在读取...";
      const params = new URLSearchParams();
      const codex = $("#codexPath").value.trim();
      const cc = $("#ccPath").value.trim();
      const codexPlus = $("#codexPlusPath").value.trim();
      if (codex) params.set("codex", codex);
      if (cc) params.set("cc", cc);
      if (codexPlus) params.set("codexPlus", codexPlus);
      params.set("sensitive", $("#sensitiveToggle").checked ? "1" : "0");
      const response = await fetch(`/api/snapshot?${params.toString()}`, {
        headers: { "X-CH-Token": window.CH_TOKEN || "" }
      });
      state.data = await response.json();
      render();
    }

    function showTab(name) {
      state.activeTab = name;
      document.querySelectorAll(".tab").forEach(tab => {
        const active = tab.dataset.tab === name;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
        tab.tabIndex = active ? 0 : -1;
      });
      ["system", "config", "auth", "cc", "codexplus", "raw"].forEach(tab => {
        $(`#tab-${tab}`).classList.toggle("hidden", tab !== name);
      });
    }

    /* 标签栏键盘导航：← → Home End（遵循 WAI-ARIA Tabs 模式） */
    $("#tabs").addEventListener("keydown", (event) => {
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

    $("#tabs").addEventListener("click", (event) => {
      const button = event.target.closest("[data-tab]");
      if (button) showTab(button.dataset.tab);
    });

    document.addEventListener("click", async (event) => {
      const testButton = event.target.closest("[data-test-provider]");
      if (testButton) {
        event.preventDefault();
        event.stopPropagation();
        await runProviderTest(testButton.dataset.source, testButton.dataset.appType, testButton.dataset.providerId);
        return;
      }

      const testAllButton = event.target.closest("[data-test-all]");
      if (testAllButton) {
        event.preventDefault();
        event.stopPropagation();
        await runProviderTestAll(testAllButton.dataset.source);
        return;
      }

      const button = event.target.closest("[data-provider-action]");
      if (!button) return;
      const open = button.dataset.providerAction === "expand";
      const scope = button.dataset.providerScope || state.activeTab;
      document.querySelectorAll(`#tab-${scope} .provider-card`).forEach(card => {
        card.open = open;
      });
    });

    $("#refreshBtn").addEventListener("click", loadSnapshot);
    $("#applyPathBtn").addEventListener("click", loadSnapshot);
    $("#sensitiveToggle").addEventListener("change", loadSnapshot);
    $("#repairBtn").addEventListener("click", async () => {
      const ok = confirm("一键修复会先备份 config.toml 和 auth.json，然后把当前 .codex 文件夹移入回收站。是否继续？");
      if (!ok) return;
      try {
        const result = await postJson("/api/repair-codex", currentPathPayload());
        alert(`${result.message || "一键修复已完成"}\n备份位置：${result.backupDir || "未生成"}\n已备份：${(result.backedUp || []).join("、") || "无"}`);
        await loadSnapshot();
      } catch (error) {
        alert(`一键修复失败：${error.message || error}`);
      }
    });
    $("#shutdownBtn").addEventListener("click", async () => {
      await fetch("/api/shutdown", {
        method: "POST",
        headers: { "X-CH-Token": window.CH_TOKEN || "" }
      });
      document.body.innerHTML = '<div class="shell"><div class="panel content"><h1>Codex Helper 已关闭</h1><p class="subtitle">可以关闭这个窗口了。</p></div></div>';
    });

    loadSnapshot().catch(error => {
      $("#statusText").textContent = `读取失败：${error}`;
    });
    setInterval(() => fetch("/api/ping").catch(() => {}), 10000);
  </script>
</body>
</html>
"""
