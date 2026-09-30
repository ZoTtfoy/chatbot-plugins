"""收到的图片 / 文件自动归档 —— 按日期分目录存起来。

为什么有用：QQ 和微信的图片会过期、会被清理，重要的（合同、截图、
发票、孩子的照片）想留个底。这个插件收到就顺手存一份。

用到的能力：
  ctx.on("message")       ... 看不到媒体文件；见下面说明
  ctx.fs.copy_into(...)   复制到归档目录 —— 需要 filesystem 权限
  ctx.fs.mkdir / write_text

★ 关于「怎么拿到收到的图片」：
  插件收到的 session 里只有**文本**，图片在宿主那边已经处理成
  「[图片]」占位了（而且图片内容不落库，避免把数据库撑爆）。
  所以这个插件做的是**消息留档**：把每条消息按会话 + 日期写成
  markdown 文件，图片消息记一行「[图片]」（媒体本体由宿主另行处理）。

  真正的媒体归档需要宿主把媒体文件路径也交给插件 —— 目前只有
  QQ/微信通道内部有。如果你的需求是「把图片文件本体存下来」，
  告诉我，我把「媒体文件路径」也暴露到 session 上（那会多一个权限）。

  下面同时演示了 fs 能力的正确用法：**只往允许的目录里写**。
"""

NAME = "消息留档 / 归档"
VERSION = "1.0.0"
DESCRIPTION = "把每个会话的消息按日期归档成 markdown 到本地目录，方便检索和备份（图片/语音记为占位）。"
AUTHOR = "ChatBot 内置示例"

PERMISSIONS = ["filesystem"]

DEFAULT_CONFIG = {
    "dir": "archive",
    "group_by": "date",
    "only_group": "",
    "skip_commands": True,
    "max_file_kb": 512,
}

CONFIG_SCHEMA = [
    {"key": "dir", "type": "string", "label": "归档目录", "default": "archive",
     "help": "相对路径会放在「数据目录」下；想放到别的盘，先到配置里把目录加进 plugins.fs_roots"},
    {"key": "group_by", "type": "select", "label": "怎么分文件", "default": "date",
     "options": [
         {"value": "date", "label": "按日期一个文件（推荐）"},
         {"value": "session", "label": "按会话一个文件"},
     ]},
    {"key": "only_group", "type": "string", "label": "只归档哪个会话（可留空）",
     "default": "", "placeholder": "留空 = 全部",
     "help": "填群名或好友名，只归档这一个；留空则全部归档"},
    {"key": "skip_commands", "type": "bool", "label": "不归档以 / 开头的指令", "default": True},
    {"key": "max_file_kb", "type": "int", "label": "单个归档文件上限（KB）", "default": 512,
     "min": 16, "max": 8192,
     "help": "超过就自动换一个新文件，避免一个文件涨到几十兆打不开"},
]


async def apply(ctx, config):
    import time
    from pathlib import Path

    base = str(config.get("dir") or "archive")

    async def archive(session):
        text = (session.text or "").strip()
        if not text:
            return
        if bool(config.get("skip_commands")) and text.startswith("/"):
            return
        only = str(config.get("only_group") or "").strip()
        if only and only not in (session.who, session.sender):
            return

        day = time.strftime("%Y-%m-%d")
        hour = time.strftime("%H:%M:%S")
        if str(config.get("group_by")) == "session":
            name = f"{_safe(session.who)}.md"
        else:
            name = f"{day}.md"

        rel = f"{base}/{name}"
        line = f"- `{hour}` **{session.sender or session.who}**（{session.channel}）：{text[:500]}\n"

        try:
            # ★ 用 fs 能力而不是裸 open()：路径会被限制在允许的目录里，
            #   写错目录会立刻报错，而不是悄悄写到系统盘某个角落。
            current = ctx.fs.read_text(rel) if ctx.fs.exists(rel) else ""
            limit = max(16, int(config.get("max_file_kb") or 512)) * 1024
            if len(current.encode("utf-8", errors="ignore")) > limit:
                rel = f"{base}/{name[:-3]}-{int(time.time())}.md"
                current = ""
            header = f"# 归档 {session.who}（{session.channel}）\n\n" if not current else ""
            ctx.fs.write_text(rel, header + current + line)
        except Exception as exc:  # noqa: BLE001
            ctx.log.warn(f"归档失败：{exc}")

    @ctx.on("message")
    async def on_message(session):
        await archive(session)

    @ctx.command("archive-here", help="把当前会话此前的记录归档一次（测试用）", admin_only=True)
    async def cmd_here(session, args):
        await archive(session)
        target = ctx.fs.resolve(base, "查看归档目录")
        return f"已归档到 {target}"

    @ctx.command("archive-dir", help="看看归档目录在哪")
    async def cmd_dir(session, args):
        try:
            target = ctx.fs.resolve(base, "查看归档目录")
        except Exception as exc:  # noqa: BLE001
            return f"归档目录不可用：{exc}"
        return f"归档目录：{target}"

    ctx.log.info(f"消息归档已开启（目录：{base}）")


def _safe(name):
    text = "".join(
        ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(name or "session")
    )
    return text.strip("._-")[:40] or "session"
