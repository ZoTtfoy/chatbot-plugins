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
VERSION = "1.1.0"
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

    base = str(config.get("dir") or "archive")

    def size_of(rel):
        """当前文件多少字节（不存在就是 0）。

        ★ 这里直接对 ``ctx.fs.resolve()`` 出来的 Path 做 stat：它已经过
          越界校验，是插件自己写得进去的文件，读一下大小不算越权。
        """
        try:
            target = ctx.fs.resolve(rel, "查看归档文件")
            return target.stat().st_size if target.is_file() else 0
        except Exception:  # noqa: BLE001
            return 0

    def overflow_name(name):
        """超过大小上限时的下一个文件名。

        ★ 必须带序号：原来用 ``int(time.time())`` 拼后缀，同一秒内来的第二条
          消息会算出**同一个名字**，把刚写进去的那份直接覆盖掉 ——
          刷屏的时候恰好是最需要留档的时候。
        """
        stem = name[:-3] if name.endswith(".md") else name
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for seq in range(1, 1000):
            candidate = f"{stem}-{stamp}-{seq}.md"
            if size_of(f"{base}/{candidate}") == 0:
                return candidate
        return f"{stem}-{stamp}-{time.time_ns()}.md"

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
            #
            # ★ 追加写（append）而不是「读全文 → 拼一行 → 写回全文」。
            #   这个插件挂在**每条消息**上，原来那种写法在一个热闹的群里
            #   就是每条消息两次全量磁盘 IO，而且文件越大越慢（总量是平方级）。
            #   追加是 O(1)，代价只是要在换文件时 stat 一下大小。
            limit = max(16, int(config.get("max_file_kb") or 512)) * 1024
            if size_of(rel) > limit:
                rel = f"{base}/{overflow_name(name)}"

            header = f"# 归档 {session.who}（{session.channel}）\n\n"
            chunk = (header if size_of(rel) == 0 else "") + line
            ctx.fs.write_text(rel, chunk, append=True)
        except Exception as exc:  # noqa: BLE001
            ctx.log.warn(f"归档失败：{exc}")

    @ctx.on("message")
    async def on_message(session):
        await archive(session)

    @ctx.command("archive-here", help="把当前这条消息再归档一次（测试用）", admin_only=True)
    async def cmd_here(session, args):
        await archive(session)
        target = ctx.fs.resolve(base, "查看归档目录")
        return f"已按当前配置归档。目录：{target}"

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
