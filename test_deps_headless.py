# -*- coding: utf-8 -*-
"""deps.py（运行时依赖检测）与前端导航结构的回归测试。

覆盖：
1. 依赖定义表结构完整（每个依赖都有检测函数、文件名、安装参数）
2. scan() 返回结构正确、缓存生效、force 能强制刷新
3. 安装命令构造：内置文件优先 → PowerShell(MSIX) → 在线兜底
4. 缺失项计算（只算必需项）
5. 未知依赖的容错
6. 前端导航：TAB_GROUPS 与 CH_TABS / section 一一对应（防止加了页签忘了加 section）
7. 默认页签的 section 必须可见（否则开屏空白）
8. 页面 JS 语法（node --check）
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codexhelper import deps  # noqa: E402
from codexhelper.webui import page  # noqa: E402

_results = []
_bad = []


def ok(name, cond, extra=""):
    cond = bool(cond)
    _results.append(cond)
    if not cond:
        _bad.append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f"  {extra}" if extra else ""))


def section(t):
    print(f"== {t} ==")


try:
    # ================================================== 依赖定义表 ======
    section("1. 依赖定义表结构")
    ok("定义了 DEPS", bool(deps.DEPS), f"{len(deps.DEPS)} 项")
    ids = [d["id"] for d in deps.DEPS]
    ok("id 唯一", len(ids) == len(set(ids)), str(ids))
    for d in deps.DEPS:
        ok(f"{d['id']} 有 name", bool(d.get("name")))
        ok(f"{d['id']} 有 detect 函数", callable(d.get("detect")))
        ok(f"{d['id']} 有文件名", bool(d.get("file")))
        ok(f"{d['id']} 有 required 标记", isinstance(d.get("required"), bool))
    ok("含 webview2", "webview2" in ids)
    ok("含 vc_redist", "vc_redist" in ids)
    ok("含 python_manager", "python_manager" in ids)

    # ======================================================== scan ======
    section("2. scan() 返回结构")
    r = deps.scan(force=True)
    ok("scan 返回 ok", r.get("ok"))
    ok("含 items 列表", isinstance(r.get("items"), list), f"{len(r['items'])} 项")
    ok("含 missing 列表", isinstance(r.get("missing"), list))
    ok("含 all_ok", isinstance(r.get("all_ok"), bool))
    ok("含 deps_dir", bool(r.get("deps_dir")))
    for it in r["items"]:
        for k in ("id", "name", "desc", "required", "installed",
                  "has_local", "size", "url"):
            ok(f"item[{it['id']}] 含 {k}", k in it)

    section("3. 缓存与强制刷新")
    r1 = deps.scan()
    ok("二次 scan 走缓存（同一对象）", r1 is r or r1 == r)
    r2 = deps.scan(force=True)
    ok("force=True 仍能返回", r2.get("ok"))
    deps.invalidate_cache()
    r3 = deps.scan()
    ok("清缓存后可重新扫描", r3.get("ok"))

    section("4. 缺失项只算必需项")
    # all_ok 应只受 required 影响
    required_missing = [i["id"] for i in r["items"]
                        if i["required"] and not i["installed"]]
    ok("all_ok 与必需项状态一致", r["all_ok"] == (not required_missing),
       f"all_ok={r['all_ok']} required_missing={required_missing}")
    mr = deps.missing_required()
    ok("missing_required 只含必需项",
       all(i["required"] for i in r["items"] if i["id"] in mr), str(mr))

    # ================================================== 安装命令 ========
    section("5. 安装命令构造")
    for d in deps.DEPS:
        cmd = deps.build_install_cmd(d["id"])
        ok(f"{d['id']} 能构造命令", isinstance(cmd, dict))
        if cmd.get("ok"):
            ok(f"{d['id']} 有 kind", cmd.get("kind") in
               ("local", "online", "powershell"))
            ok(f"{d['id']} 有 argv", isinstance(cmd.get("argv"), list)
               and len(cmd["argv"]) > 0)
        else:
            # 没内置包且没 URL 时报错是正确行为
            ok(f"{d['id']} 无包时给出 error", bool(cmd.get("error")),
               cmd.get("error", ""))

    ok("未知依赖返回 error",
       not deps.build_install_cmd("__nope__").get("ok"))
    ok("未知依赖 install 返回失败",
       not deps.install_dep("__nope__").get("ok"))

    section("6. MSIX 走 PowerShell")
    pm = next((d for d in deps.DEPS if d["id"] == "python_manager"), None)
    if pm:
        ok("python_manager 标记为 msix", bool(pm.get("msix")))
        cmd = deps.build_install_cmd("python_manager")
        if cmd.get("ok"):
            ok("MSIX 用 Add-AppxPackage",
               any("Add-AppxPackage" in str(a) for a in cmd["argv"]),
               str(cmd["argv"])[:80])

    section("7. deps_dir 路径解析")
    d = deps.deps_dir()
    ok("deps_dir 是 Path", isinstance(d, Path), str(d))
    ok("deps_dir 目录名是 deps", d.name == "deps", str(d))

    # ================================================== 前端导航 ========
    section("8. 前端导航结构")
    ok("定义了 TAB_GROUPS", bool(page.TAB_GROUPS), f"{len(page.TAB_GROUPS)} 组")
    all_tabs = page._all_tabs()
    ok("_all_tabs 非空", bool(all_tabs), str(all_tabs))
    ok("页签 id 唯一", len(all_tabs) == len(set(all_tabs)))
    ok("_js_tabs 含原生页签",
       all(t in page._js_tabs() for t in page._NATIVE_TABS))
    ok("默认页签在页签列表里", page._tab_active() in all_tabs,
       page._tab_active())

    section("9. 导航与 section 一一对应（防漏）")
    html = page.get_page("1.8.0", "test", "https://x", False)
    # 每个分组页签都必须有对应 section，否则点了没反应
    for tid in all_tabs:
        ok(f"页签 {tid} 有对应 section", f'id="tab-{tid}"' in html)
    # 导航按钮必须存在
    for tid in all_tabs:
        ok(f"页签 {tid} 有导航按钮", f'data-tab="{tid}"' in html)

    section("10. 默认页签的 section 必须可见")
    default = page._tab_active()
    m = re.search(r'<section id="tab-' + re.escape(default) + r'"([^>]*)>',
                  html)
    ok(f"默认页签 {default} 的 section 存在", m is not None)
    if m:
        ok(f"默认页签 {default} 的 section 未隐藏", "hidden" not in m.group(1))
    # 其它页签必须隐藏（否则开屏堆叠）
    visible = []
    for mm in re.finditer(r'<section id="(tab-[a-z]+)"([^>]*)>', html):
        if "hidden" not in mm.group(2):
            visible.append(mm.group(1))
    ok("可见 section 只有默认那一个", visible == [f"tab-{default}"],
       str(visible))

    section("11. 依赖页元素")
    for key in ("depsList", "depsAlert", "depsRescanBtn",
                "depsInstallMissingBtn", "depsStatus"):
        ok(f"含 {key}", key in html)
    ok("含 tabgroup 分组样式类", "tabgroup" in html)

    section("12. 模板替换无残留")
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", html)
    ok("无未替换的模板占位", not leftover, str(leftover))
    ok("CH_TABS 已注入",
       bool(re.search(r"const CH_TABS = \[", html)))
    ok("CH_DEFAULT_TAB 已注入",
       bool(re.search(r'const CH_DEFAULT_TAB = "', html)))

    section("13. 页面 JS 语法")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                         html, re.S)
    ok("提取到内联 script", len(scripts) > 0, f"{len(scripts)} 个")
    node = shutil.which("node")
    for cand in (Path(r"E:\NODE\node.EXE"),
                 Path(r"C:\Program Files\nodejs\node.exe")):
        if not node and cand.exists():
            node = str(cand)
    if node:
        tmpdir = Path(tempfile.gettempdir())
        tmp = tmpdir / "_ch_jscheck.js"
        for i, s in enumerate(scripts, 1):
            tmp.write_text(s, encoding="utf-8")
            p = subprocess.run([node, "--check", str(tmp)],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            ok(f"script#{i} 语法", p.returncode == 0,
               (p.stderr or "")[:200])
        tmp.unlink(missing_ok=True)
    else:
        print("  [SKIP] 未找到 node")

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
