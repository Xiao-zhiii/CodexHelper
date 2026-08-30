# -*- coding: utf-8 -*-
"""Codex 桌面端（OpenAI.Codex MSIX）镜像下载/安装后端（v1.5.0）。

镜像源：github.com/Wangnov/codex-app-mirror（releases 以 codex-app-<build> 为 tag，
Windows 资产为 OpenAI.Codex_<版本>_<arch>__2p2nqsd0c76g0.Msix，附 SHA256SUMS-windows.txt）。

下载通道（按用户要求）：
① 先尝试 ghproxylist.com 前缀加速（国内友好）
② 同时检测本机代理（系统代理/环境变量），有代理则所有通道都走代理
③ 兜底直连；另附带 ghproxy.net / gh-proxy.com 两个历史可用前缀提高成功率
"""
import hashlib
import json
import os
import re
import subprocess
import time

from .constants import (APPX_ARCH, APPX_DL_TIMEOUT_SEC, APPX_INSTALL_TIMEOUT_SEC,
                        APPX_MIRROR_REPO, APPX_PKG_NAME, CREATE_NO_WINDOW,
                        GHPROXYLIST)
from .util import decode_bytes, kill_tree, run_quiet

UA = {"User-Agent": "Mozilla/5.0"}

# 额外的历史可用加速前缀（ghproxylist 之后依次尝试）
EXTRA_PROXY_PREFIXES = [
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
]

_MSIX_RE = re.compile(
    re.escape(APPX_PKG_NAME) + r"_([\d.]+)_(x64|arm64)__[^/]*\.Msix$", re.IGNORECASE)


def version_tuple(v):
    """'26.820.9563.0' → (26, 820, 9563, 0)；解析失败返回 (0,)。"""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return (0,)


def needs_uninstall(target, installed):
    """降级判定：目标版本低于已装版本时，Add-AppxPackage 无法直接覆盖，
    需要先卸载当前包再装（~/.codex 等用户数据不受卸载影响）。"""
    if not installed or not target:
        return False
    return version_tuple(target) < version_tuple(installed)


# ------------------------------------------------------------ 下载通道 ----

def candidate_urls(url):
    """返回同一资源的多个候选下载地址：历史可用前缀 + 直连兜底。
    （ghproxylist 聚合页的动态链接由 discover_links() 单独解析）"""
    seen, out = set(), []
    for prefix in EXTRA_PROXY_PREFIXES + [""]:
        cand = prefix + url
        if cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def _looks_like_html(head: bytes) -> bool:
    head = head.lstrip()[:256].lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def discover_links(url, opener=None, timeout=30):
    """从 ghproxylist.com 聚合页解析出该文件当前可用的代理下载链接（国内友好）。
    返回链接列表（可能为空）。页面是服务端渲染，urllib 可直接解析。"""
    import urllib.parse
    try:
        html = http_get_bytes(opener, GHPROXYLIST + url, timeout=timeout,
                              max_bytes=1024 * 1024).decode("utf-8", "replace")
    except Exception:
        return []
    raw = urllib.parse.quote(url, safe="")
    links, seen = [], set()
    for m in re.finditer(r'https?://[^\s"\'<>\\]+', html):
        link = m.group(0).rstrip("\\").rstrip(",")
        if link.startswith(GHPROXYLIST) or link == url:
            continue
        if url in link or raw in link:
            if link not in seen:
                seen.add(link)
                links.append(link)
    return links


def open_url(opener, url, timeout=60):
    """用指定 opener（可为 None=默认）打开 URL，返回响应对象。"""
    import urllib.request
    req = urllib.request.Request(url, headers=UA)
    if opener is not None:
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def http_get_bytes(opener, url, timeout=60, max_bytes=2 * 1024 * 1024,
                   allow_html=False):
    """小文件整体读取（用于列表/SHA256SUMS）。返回 bytes。"""
    with open_url(opener, url, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read(max_bytes)
    if not allow_html and ("text/html" in ctype or _looks_like_html(data[:512])):
        raise IOError("通道返回网页而非文件")
    return data


def download_to(url, dest, opener=None, log=print, progress=None, cancel=None,
                timeout=60, max_seconds=APPX_DL_TIMEOUT_SEC):
    """多通道下载：ghproxylist 聚合链接优先 → 历史可用前缀 → 直连兜底。
    所有通道都会做“网页内容嗅探”，防止把 HTML 页当文件存下来。
    progress(got, total) 回调；cancel 为 threading.Event。返回 dest。"""
    # ① ghproxylist 聚合发现的实时可用链接（按用户要求的优先通道）
    discovered = []
    try:
        discovered = discover_links(url, opener=opener, timeout=45)
        if discovered:
            log(f"ghproxylist 聚合到 {len(discovered)} 个可用代理链接。", "dim")
        else:
            log("ghproxylist 未聚合到可用链接，转用内置通道。", "dim")
    except Exception:
        pass
    candidates = discovered + candidate_urls(url)

    last_err = None
    for cand in candidates:
        if cancel is not None and cancel.is_set():
            raise KeyboardInterrupt
        label = cand if len(cand) <= 90 else cand[:87] + "..."
        log("尝试下载：" + label)
        try:
            got, total = 0, 0
            t0 = time.time()
            with open_url(opener, cand, timeout=timeout) as resp, open(dest, "wb") as f:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                cl = resp.headers.get("Content-Length")
                total = int(cl) if cl else 0
                first = resp.read(512)
                if not first:
                    raise IOError("下载内容为空")
                if "text/html" in ctype or _looks_like_html(first):
                    raise IOError("通道返回网页而非文件（已跳过）")
                f.write(first)
                got += len(first)
                if progress:
                    progress(got, total)
                while True:
                    if cancel is not None and cancel.is_set():
                        raise KeyboardInterrupt
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, total)
                    if time.time() - t0 > max_seconds:
                        raise TimeoutError(f"下载超过 {max_seconds} 秒未完成")
            if total and got < total:
                raise IOError(f"下载不完整（{got}/{total} 字节）")
            return dest
        except KeyboardInterrupt:
            raise
        except Exception as e:
            last_err = e
            log(f"该通道失败：{e}", "warn")
    raise RuntimeError(f"所有下载通道均失败（{last_err}）。"
                       "建议：① 在【Codex 环境检测】页确认代理设置；"
                       "② 或手动下载后重试。")


# ------------------------------------------------------------ 版本列表 ----

def _msix_asset(asset):
    """从 asset 名解析 MSIX 信息；非 Windows MSIX 返回 None。"""
    m = _MSIX_RE.search(asset.get("name", ""))
    if not m:
        return None
    ver, arch = m.group(1), m.group(2).lower()
    return {"name": asset["name"], "version": ver, "arch": arch,
            "size": int(asset.get("size") or 0),
            "url": asset.get("browser_download_url", "")}


def fetch_releases_atom(log=print, opener=None, per_page=12):
    """GitHub API 不可达时的兜底：解析 releases.atom（只有 tag 与日期；
    MSIX 文件名/大小留空，安装时经 SHA256SUMS-windows.txt 再解析）。
    解析失败返回 None。"""
    url = f"https://github.com/{APPX_MIRROR_REPO}/releases.atom"
    channels = []
    try:
        channels += discover_links(url, opener=opener)
    except Exception:
        pass
    channels += candidate_urls(url)
    text = None
    for cand in channels:
        try:
            log("尝试版本源：" + cand[:90])
            text = http_get_bytes(opener, cand, timeout=45).decode("utf-8", "replace")
            if "<feed" not in text:
                raise IOError("返回内容不是 atom feed")
            break
        except Exception as e:
            log(f"该版本源失败：{e}", "warn")
            text = None
    if not text:
        return None
    releases = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, re.S)[:per_page]:
        mid = re.search(r"<id>[^<]*/tag/([^<]+)</id>", entry)
        mupd = re.search(r"<updated>([^<]+)</updated>", entry)
        if not mid:
            continue
        tag = mid.group(1).strip()
        releases.append({
            "tag": tag, "name": tag,
            "published": (mupd.group(1)[:10] if mupd else ""),
            "msix": None,
            "sha_url": (f"https://github.com/{APPX_MIRROR_REPO}"
                        f"/releases/download/{tag}/SHA256SUMS-windows.txt"),
        })
    return releases or None


def fetch_releases(log=print, opener=None, per_page=50, api_fallback_via=None):
    """拉取镜像版本列表（新→旧）。优先 GitHub API；失败可再换 opener 重试。
    返回 [{tag, name, published, msix|None, sha_url}]。msix 为 None 时
    （降级解析路径），安装时会从 SHA256SUMS-windows.txt 解析文件名。"""
    api = f"https://api.github.com/repos/{APPX_MIRROR_REPO}/releases?per_page={per_page}"
    data = None
    for label, op in (("直连", opener),):
        try:
            log(f"正在获取镜像版本列表（{label}" +
                ("，经系统代理）" if op else "）"))
            data = json.loads(http_get_bytes(op, api, timeout=45).decode("utf-8", "replace"))
            break
        except Exception as e:
            log(f"GitHub API 获取失败（{label}）：{e}", "warn")
    if data is None and api_fallback_via is not None:
        try:
            log("正在经系统代理重试 GitHub API …")
            data = json.loads(http_get_bytes(
                api_fallback_via, api, timeout=45).decode("utf-8", "replace"))
        except Exception as e:
            log(f"GitHub API 经代理仍失败：{e}", "warn")
    if data is None:
        # API 全挂（国内常见）：退回 releases.atom（可经加速通道获取）
        atom = fetch_releases_atom(log=log, opener=opener, per_page=per_page)
        if atom:
            log("GitHub API 不可达，已从 releases.atom 解析版本列表"
                "（文件大小将在安装时解析）。", "warn")
            return atom
        raise RuntimeError(
            "无法获取镜像版本列表（api.github.com 与 releases.atom 均不可达）。\n"
            "建议：开启系统代理或设置 HTTP_PROXY/HTTPS_PROXY 环境变量后重试。")

    releases = []
    for rel in data:
        tag = rel.get("tag_name", "")
        assets = rel.get("assets", []) or []
        sha_url = next((a["browser_download_url"] for a in assets
                        if a.get("name") == "SHA256SUMS-windows.txt"), "")
        msix = next((_msix_asset(a) for a in _arch_sorted(assets)), None)
        releases.append({"tag": tag, "name": rel.get("name") or tag,
                         "published": (rel.get("published_at") or "")[:10],
                         "msix": msix, "sha_url": sha_url})
    return releases


def _arch_sorted(assets):
    """把目标架构的 MSIX 资产排到最前（x64 优先于 arm64 之外的匹配）。"""
    hits = [a for a in assets if _msix_asset(a)]
    hits.sort(key=lambda a: 0 if _msix_asset(a)["arch"] == APPX_ARCH else 1)
    return hits


def resolve_asset_from_sha(opener, sha_url, tag, log=print):
    """API 不可用时的兜底：从 SHA256SUMS-windows.txt 解析目标架构 MSIX 文件名与哈希。
    返回 (filename, expected_sha256, size|None)。"""
    text = None
    last = None
    for cand in candidate_urls(sha_url):
        try:
            log("解析版本文件：" + cand[:90])
            text = http_get_bytes(opener, cand, timeout=45).decode("utf-8", "replace")
            break
        except Exception as e:
            last = e
    if not text:
        raise RuntimeError(f"无法获取 SHA256SUMS-windows.txt（{last}）")
    pat = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+\.Msix)$", re.IGNORECASE)
    fallback = None
    for line in text.splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        sha, fname = m.group(1).lower(), m.group(2).strip()
        if f"_{APPX_ARCH}__" in fname or f"_{APPX_ARCH}_" in fname:
            return fname, sha, None
        fallback = (fname, sha, None)
    if fallback:
        return fallback
    raise RuntimeError("SHA256SUMS-windows.txt 中未找到 Windows MSIX 条目")


# ------------------------------------------------------------ 校验/安装 ----

def sha256_of(path, log=None, progress=None, cancel=None):
    h = hashlib.sha256()
    got = 0
    total = os.path.getsize(path)
    with open(path, "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise KeyboardInterrupt
            chunk = f.read(1048576)
            if not chunk:
                break
            h.update(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    return h.hexdigest()


def close_desktop_app(log=print):
    """安装前关闭正在运行的 ChatGPT 桌面端（否则 Add-AppxPackage 会失败）。"""
    rc, _ = run_quiet(["taskkill", "/IM", "ChatGPT.exe", "/T", "/F"], timeout=20)
    if rc == 0:
        log("已关闭正在运行的 ChatGPT 应用。")
        time.sleep(2)
        return True
    return False


def _ps_wait(ps_cmd, log=print, progress=None, cancel=None, timeout=300):
    """静默执行 PowerShell 命令并等待结束（秒级心跳、软取消）。返回 (ok, 输出末尾)。"""
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW)
    t0, last_sec = time.time(), -1
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        if cancel is not None and cancel.is_set():
            # 软取消：应用包操作中途硬杀可能留下半安装状态，只提示并继续等待
            log("已请求取消：当前系统操作无法安全中断，将等待其结束后停止。", "warn")
            cancel = None
        sec = int(time.time() - t0)
        if sec != last_sec:
            last_sec = sec
            if progress:
                progress(sec, 0)     # 0 表示走秒显示而非百分比
        if sec > timeout:
            kill_tree(proc.pid)
            proc.wait(timeout=30)
            return False, f"超时（>{timeout}s）"
        time.sleep(0.3)
    text = decode_bytes(proc.stdout.read()).strip()
    return rc == 0, text[-1500:] or f"退出码 {rc}"


def uninstall_desktop(log=print, progress=None, cancel=None, timeout=300):
    """卸载 OpenAI.Codex 桌面应用（降级安装的前置步骤）。
    只移除应用包与其本地缓存；~/.codex（技能/配置/密钥）不在卸载范围，
    不受影响。返回 (ok, 输出末尾)。"""
    ps_cmd = (f"Get-AppxPackage -Name '{APPX_PKG_NAME}' | Remove-AppxPackage; "
              "if($?){'UNINS_OK'}else{'UNINS_FAIL'}")
    ok, out = _ps_wait(ps_cmd, log=log, progress=progress, cancel=cancel,
                       timeout=timeout)
    return ok and "UNINS_FAIL" not in out, out


def install_msix(path, log=print, progress=None, cancel=None,
                 timeout=APPX_INSTALL_TIMEOUT_SEC, allow_downgrade=True):
    """安装 MSIX 包。allow_downgrade=True 时加 -ForceUpdateFromAnyVersion
    （这是 Add-AppxPackage 允许降级安装的开关）。
    返回 (ok, 输出文本)。安装期间 cancel 仅作“软取消”提示，不会硬杀安装进程。"""
    ps_exe = subprocess.list2cmdline(
        [os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell"
         r"\v1.0\powershell.exe"])
    flag = " -ForceUpdateFromAnyVersion" if allow_downgrade else ""
    ps_cmd = (f"& {ps_exe} -NoProfile -ExecutionPolicy Bypass -Command "
              f"'Add-AppxPackage -Path \"{path}\"{flag}; "
              f"if($?){{'APPX_OK'}}else{{'APPX_FAIL'}}'")
    ok, out = _ps_wait(ps_cmd, log=log, progress=progress, cancel=cancel,
                       timeout=timeout)
    if ok and "APPX_FAIL" in out:
        ok = False
    return ok, out
