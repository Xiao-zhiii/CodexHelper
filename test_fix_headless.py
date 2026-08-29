# -*- coding: utf-8 -*-
"""v1.2.0 新增“Codex 插件修复”功能的无 GUI 测试。

覆盖：skill 检测(未装/已装)、zip 下载安装、config.toml Full Access 写入
（含 [table] 段保留与备份）、goal.md 写入、真实环境幂等性。
"""
import os
import sys
import tempfile

import importlib.util

spec = importlib.util.spec_from_file_location(
    "nci", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "node_codex_installer.py"))
nci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nci)

PASS = 0


def ok(name, cond, extra=""):
    global PASS
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("  " + extra if extra else ""))
    if not cond:
        sys.exit("测试失败：" + name)
    PASS += 1


tmp = tempfile.mkdtemp(prefix="nci_test_")

print("== 1. 临时环境：skill 未安装检测 ==")
ok("find_patch_skill(空环境) 返回 None", nci.find_patch_skill(tmp) is None)

print("== 2. 临时环境：从 GitHub 真实下载并安装 skill ==")
dest = nci.install_patch_skill(log=lambda *a, **k: None, home=tmp)
ok("安装目录存在 SKILL.md", os.path.isfile(os.path.join(dest, "SKILL.md")), dest)
ok("安装目录存在 references/",
   os.path.isdir(os.path.join(dest, "references")))
ok("安装后 find_patch_skill 能找到", os.path.normpath(nci.find_patch_skill(tmp)) ==
   os.path.normpath(dest))

print("== 3. 临时环境：config.toml Full Access 写入（含 [table] 保留） ==")
cfg_dir = os.path.join(tmp, ".codex")
cfg = os.path.join(cfg_dir, "config.toml")
with open(cfg, "w", encoding="utf-8") as f:
    f.write('model = "gpt-5"\napproval_policy = "on-request"\n'
            'sandbox_mode = "workspace-write"\n\n[windows]\nsandbox = "elevated"\n')
nci.ensure_full_access(log=lambda *a, **k: None, home=tmp)
with open(cfg, "r", encoding="utf-8") as f:
    new_cfg = f.read()
ok("approval_policy = never 已写入", 'approval_policy = "never"' in new_cfg)
ok("sandbox_mode = danger-full-access 已写入",
   'sandbox_mode = "danger-full-access"' in new_cfg)
ok("原 [windows] 段保留", '[windows]\nsandbox = "elevated"' in new_cfg)
ok("model 保留", 'model = "gpt-5"' in new_cfg)
ok("重复旧键已清除", new_cfg.count("approval_policy") == 1 and
   new_cfg.count("sandbox_mode") == 1)
idx_key = new_cfg.index("approval_policy")
idx_tbl = new_cfg.index("[windows]")
ok("顶层键位于 [table] 段之前", idx_key < idx_tbl)
ok("备份文件已生成", os.path.isfile(cfg + ".nodecodexsetup.bak"))
ok("备份内容与原文件一致",
   open(cfg + ".nodecodexsetup.bak", encoding="utf-8").read() ==
   'model = "gpt-5"\napproval_policy = "on-request"\n'
   'sandbox_mode = "workspace-write"\n\n[windows]\nsandbox = "elevated"\n')

print("== 4. 临时环境：goal.md 写入 ==")
gp = nci.ensure_goal_prompt(log=lambda *a, **k: None, home=tmp)
body = open(gp, encoding="utf-8").read()
ok("goal.md 已写入", os.path.isfile(gp), gp)
ok("goal.md 引用 skill 路径", "codex-windows-fast-patch-skill/SKILL.md" in body)
ok("goal.md 含修复提示词", "排查并修复本机codex桌面端" in body)

print("== 5. 真实环境：幂等性验证 ==")
real_skill = nci.find_patch_skill()
print("    本机 skill:", real_skill)
if real_skill:
    ok("真实环境检测到已安装 skill", True)
real_cfg_bak = None
rc = nci.ensure_full_access(log=lambda *a, **k: None)
with open(rc, encoding="utf-8") as f:
    real_cfg = f.read()
ok("真实 config.toml 顶层键正确",
   'approval_policy = "never"' in real_cfg and
   'sandbox_mode = "danger-full-access"' in real_cfg)
first_tbl = min([real_cfg.index("[" + s + "]") for s in
                 ["marketplaces.openai-bundled", "desktop", "windows"]
                 if "[" + s + "]" in real_cfg] or [len(real_cfg)])
ok("真实 config.toml 键在首个 [table] 之前", real_cfg.index("approval_policy") < first_tbl)
ok("真实 config.toml 备份存在", os.path.isfile(rc + ".nodecodexsetup.bak"))
real_gp = nci.ensure_goal_prompt(log=lambda *a, **k: None)
ok("真实 prompts/goal.md 已写入", os.path.isfile(real_gp))

print(f"\n全部 {PASS} 项测试通过 ✅")
