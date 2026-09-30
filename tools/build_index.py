# -*- coding: utf-8 -*-
"""扫描 plugins/ 目录，生成 index.json（插件市场的清单）。

用法：
    python tools/build_index.py

★ 为什么索引里只放**相对路径**：
  这样 index.json 与托管位置完全无关 —— 放到 GitHub、Gitee、自建服务器、
  甚至网盘直链，程序都能按「索引 URL + 相对路径」拼出下载地址，
  换地方不用重新生成索引。程序侧见 bot/services/plugins/market.py。

生成的内容完全来自插件源码本身（解析模块顶部的常量），
不手写、不重复维护 —— 插件改了版本号，重跑一次就同步了。
"""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"

# 索引格式版本。程序按 min_format 判断自己能不能读。
FORMAT_VERSION = 1


def read_manifest(path: Path) -> dict:
    """只解析模块顶层的赋值语句，拿到 NAME / VERSION 之类的常量。

    ★ 用 ast 而不是 import：**绝不能为了生成索引去执行插件代码** ——
      那等于让任何提交到仓库的插件在 CI/维护者机器上直接跑起来。
      用 ast 只读字面量，恶意代码一行都不会被执行。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict = {}
    wanted = {"NAME", "VERSION", "DESCRIPTION", "AUTHOR", "PERMISSIONS"}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id not in wanted:
                continue
            try:
                out[target.id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                # 不是字面量（比如拼接出来的），跳过并留空
                pass
    return out


# 已知的权限名。这里**必须硬编码**（而不是 import 机器人那边）——
# 生成索引不该依赖主程序，而且这份清单是插件与宿主之间的公开契约。
KNOWN_PERMISSIONS = (
    "send_message", "net", "filesystem", "desktop", "input", "shell",
)


def read_permissions(path: Path) -> list:
    """权限可能写成 PERMISSIONS 常量，也可能是 permissions(config) 函数。

    函数形式在索引里给出**所有可能的权限并集**（取最坏情况），
    让用户在装之前就能看到"这个插件最多可能用到什么"。

    ★ 函数形式必须按**已知权限名过滤**：函数体里还有配置值、文档字符串等
      一堆字符串常量，不过滤的话它们会被当成权限名混进清单
      （实测把「按模式要权限」这句中文都收进去了）。
      常量形式则是作者显式写的，原样保留（出现未知权限也要让人看见）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "permissions":
            found = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    if sub.value in KNOWN_PERMISSIONS:
                        found.add(sub.value)
            if found:
                return sorted(found)

    perms = read_manifest(path).get("PERMISSIONS") or []
    if isinstance(perms, str):
        perms = [perms]
    return sorted(str(x) for x in perms)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    plugins = []
    for folder in sorted(PLUGINS.iterdir()):
        if not folder.is_dir() or folder.name.startswith((".", "_")):
            continue
        entry_file = folder / "plugin.py"
        if not entry_file.is_file():
            print(f"  跳过 {folder.name}：没有 plugin.py")
            continue

        manifest = read_manifest(entry_file)
        files = []
        total = 0
        for f in sorted(folder.rglob("*")):
            if not f.is_file() or "__pycache__" in f.parts:
                continue
            if f.suffix not in (".py", ".md", ".txt", ".json", ".png", ".jpg", ".ico"):
                continue
            data = f.read_bytes()
            total += len(data)
            files.append({
                "path": f.relative_to(folder).as_posix(),
                "size": len(data),
                "sha256": digest(data),
            })

        plugins.append({
            "id": folder.name,
            "name": manifest.get("NAME") or folder.name,
            "version": str(manifest.get("VERSION") or ""),
            "description": manifest.get("DESCRIPTION") or "",
            "author": manifest.get("AUTHOR") or "",
            # 相对路径：程序拼「索引地址 + root + 文件名」来下载
            "root": f"plugins/{folder.name}",
            "permissions": read_permissions(entry_file),
            "builtin": False,
            "files": files,
            "total_size": total,
        })
        print(f"  {folder.name:22s} v{plugins[-1]['version']:<8s} "
              f"{len(files)} 文件 {total / 1024:.1f}KB  权限={plugins[-1]['permissions']}")

    index = {
        "format": FORMAT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(plugins),
        "plugins": plugins,
    }
    out = ROOT / "index.json"
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已生成 {out}（{len(plugins)} 个插件，{out.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
