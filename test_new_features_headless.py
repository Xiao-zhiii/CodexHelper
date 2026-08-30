# -*- coding: utf-8 -*-
"""v1.5.0 新后端无头测试：Codex 环境扫描 + 桌面端镜像（轻量网络请求）。"""
import importlib.util
import os
import tempfile
import threading

spec = importlib.util.spec_from_file_location(
    "nci", "F:/vibe code/src/node_codex_installer.py")
nci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nci)

from codexhelper import mirror, netenv  # noqa: E402
from codexhelper.constants import APPX_ARCH  # noqa: E402

_results = []


def ok(name, cond):
    _results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def section(title):
    print(f"== {title} ==")


tmp_root = tempfile.mkdtemp(prefix="nci_new_")

# ---- 1. netenv：.env 解析与打码 ----
section("1. netenv：.env / 环境变量扫描（临时 HOME）")
home = os.path.join(tmp_root, "home")
os.makedirs(os.path.join(home, ".codex"), exist_ok=True)
with open(os.path.join(home, ".codex", ".env"), "w", encoding="utf-8") as f:
    f.write('# comment\n'
            'OPENAI_API_KEY="sk-test1234567890abcdef"\n'
            "HTTP_PROXY=http://127.0.0.1:7890\n"
            'NO_PROXY="localhost,127.0.0.1,::1"\n'
            "BAD LINE WITHOUT EQUALS\n")
rep = netenv.scan_codex_env(home=home)
ok(".env 检测为存在", rep["env_file"]["exists"])
ok(".env 解析出 3 项", rep["env_file"]["count"] == 3)
ok("密钥值已打码（不包含完整明文）",
   all("sk-test1234567890abcdef" != e["masked"] for e in rep["env_file"]["entries"]
       if e["name"] == "OPENAI_API_KEY"))
ok("打码保留首尾",
   any(e["masked"].startswith("sk-tes") and "…cdef" in e["masked"]
       for e in rep["env_file"]["entries"] if e["name"] == "OPENAI_API_KEY"))
ok("代理地址明文显示",
   any(e["value"] == "http://127.0.0.1:7890" for e in rep["env_file"]["entries"]
       if e["name"] == "HTTP_PROXY"))
ok("scan 不异常（真实注册表环境）", isinstance(rep["vars"], list))
ok("CODEX_CLI_PATH 字段存在", "cli_path" in rep)

# ---- 2. netenv：代理检测 ----
section("2. netenv：代理检测结构")
proxy = netenv.detect_proxy()
ok("返回四字段", set(proxy) == {"enabled", "server", "url", "source"})
ok("启用时代理地址合法",
   (not proxy["enabled"]) or "://" in proxy["url"])
opener = netenv.build_opener(proxy["url"] if proxy["enabled"] else None)
ok("build_opener 返回 opener 或 None", opener is None or hasattr(opener, "open"))

# ---- 3. mirror：版本列表（真实网络，轻量）----
section("3. mirror：获取镜像版本列表（真实网络）")
_releases = []


def fetch():
    try:
        _releases.extend(mirror.fetch_releases(log=lambda *a, **k: None))
    except Exception as e:
        print("  [WARN] 网络不可用，跳过在线项：", e)


th = threading.Thread(target=fetch)
th.start()
th.join(timeout=90)
if _releases:
    r0 = _releases[0]
    ok("至少 1 个版本", len(_releases) >= 1)
    ok("按用户要求抓取了更多版本（>12，最多 50）", 12 < len(_releases) <= 50)
    ok("tag 形如 codex-app-*", r0["tag"].startswith("codex-app-"))
    ok("新版本在前（tag 递减）",
       len(_releases) < 2 or mirror.version_tuple(
           _releases[0]["tag"].replace("codex-app-", ""))
       >= mirror.version_tuple(_releases[1]["tag"].replace("codex-app-", "")))
    msix = r0.get("msix")
    if msix:
        ok(f"解析出 {APPX_ARCH} MSIX：{msix['name'][:50]}",
           msix["arch"] == APPX_ARCH and msix["url"].startswith("https://"))
        ok("SHA256SUMS 资产在列", bool(r0.get("sha_url")))
        ok("版本号 4 段", len(mirror.version_tuple(msix["version"])) == 4)

    # ---- 4. mirror：ghproxylist 通道下载小文件（236B 的 SHA256SUMS）----
    if r0.get("sha_url"):
        section("4. mirror：ghproxylist 优先通道下载 SHA256SUMS-windows.txt")
        dest = os.path.join(tmp_root, "SHA256SUMS-windows.txt")
        try:
            mirror.download_to(r0["sha_url"], dest, log=lambda *a, **k: None)
            data = open(dest, "rb").read()
            ok(f"下载成功（{len(data)} 字节）", 100 < len(data) < 10240)
            ok("内容为哈希清单", b".Msix" in data or b".delta" in data)
            fname, expected, _ = mirror.resolve_asset_from_sha(
                None, r0["sha_url"], r0["tag"], log=lambda *a, **k: None)
            ok(f"解析到目标架构 MSIX 文件名：{fname[:52]}",
               f"_{APPX_ARCH}" in fname and fname.lower().endswith(".msix"))
            ok("解析到 64 位哈希", len(expected) == 64)
        except Exception as e:
            ok(f"ghproxylist 通道下载失败（记录）：{e}", False)
else:
    print("  [SKIP] 在线项全部跳过（当前网络无法访问 api.github.com）")

# ---- 4.5 mirror：降级卸载判定（纯逻辑）----
section("4.5 mirror：needs_uninstall 降级判定")
ok("低于当前 → 需卸载", mirror.needs_uninstall("26.820.9563.0", "26.825.5331.0"))
ok("高于当前 → 不卸载", not mirror.needs_uninstall("26.825.5331.0", "26.820.9563.0"))
ok("相同版本 → 不卸载", not mirror.needs_uninstall("26.820.9563.0", "26.820.9563.0"))
ok("未安装 → 不卸载", not mirror.needs_uninstall("26.820.9563.0", None))

# ---- 5. mirror：候选 URL 顺序 ----
section("5. mirror：下载候选通道顺序")
cands = mirror.candidate_urls("https://github.com/a/b")
ok("直连排最后", cands[-1] == "https://github.com/a/b")
ok("不含 ghproxylist 前缀（其前缀返回 HTML 页，已改用聚合发现）",
   all(not c.startswith("https://ghproxylist.com/") for c in cands))
ok("无重复", len(cands) == len(set(cands)))
ok("discover_links 可调用（无网返回空表）",
   isinstance(mirror.discover_links("https://example.com/x"), list))

print()
if all(_results):
    print(f"全部 {len(_results)} 项测试通过 ✅")
else:
    raise SystemExit(f"有 { _results.count(False)} 项失败 ❌")
