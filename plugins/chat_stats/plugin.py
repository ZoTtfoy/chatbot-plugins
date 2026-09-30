"""发言统计 —— 演示「插件私有存储 + 调模型」。

用到的东西：

  ctx.store_get / ctx.store_set / ctx.store_all   插件自己的小仓库（JSON 落盘）
  ctx.on("message")                                旁听每条消息
  ctx.ask_model(...)                               让模型帮忙说句人话

★ 为什么用 store 而不是直接读机器人的数据库：插件的存储是**独立文件**，
  插件被卸载时一起带走，不会污染主库；插件也读不到别人的数据。
"""

NAME = "发言统计"
VERSION = "1.0.0"
DESCRIPTION = "统计每个会话里谁说了多少话，用 /stats 查看；可选让模型对榜单点评一句。"
AUTHOR = "ChatBot 内置示例"

DEFAULT_CONFIG = {
    "comment": False,
    "top": 5,
}

CONFIG_SCHEMA = [
    {"key": "comment", "type": "bool", "label": "让模型点评一句", "default": False,
     "help": "打开后每次查榜会多调一次模型（会产生费用）"},
    {"key": "top", "type": "int", "label": "榜单显示前几名", "default": 5, "min": 1, "max": 20},
]


async def apply(ctx, config):
    @ctx.on("message")
    async def count(session):
        """旁听钩子：只看不改。注意它**没有返回值**语义，改不了消息内容。"""
        if not session.sender:
            return
        key = f"count:{session.session_key}"
        data = ctx.store_get(key) or {}
        if not isinstance(data, dict):
            data = {}
        data[session.sender] = int(data.get(session.sender, 0)) + 1
        ctx.store_set(key, data)

    @ctx.command("stats", aliases=("排行",), help="看看谁最能聊")
    async def cmd_stats(session, args):
        data = ctx.store_get(f"count:{session.session_key}") or {}
        if not isinstance(data, dict) or not data:
            return "这个会话我还没统计到发言呢，大家多说几句再来看看～"

        limit = max(1, int(config.get("top") or 5))
        ranked = sorted(data.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        total = sum(int(v) for v in data.values())

        lines = [f"本会话共 {total} 条发言，前 {len(ranked)} 名："]
        for index, (name, count) in enumerate(ranked, 1):
            lines.append(f"{index}. {name} —— {count} 条")
        board = "\n".join(lines)

        if not bool(config.get("comment")):
            return board
        # 让模型点评一句；失败也不影响榜单本身（ask_model 出错返回空串）
        comment = await ctx.ask_model(
            f"这是一个聊天群里的发言排行榜：\n{board}\n"
            f"请用一句轻松俏皮的中文点评一下（不超过 30 字，不要用 Markdown）。",
            system="你是一个活泼的聊天机器人，说话简短有趣。",
        )
        return f"{board}\n\n{comment}" if comment else board

    @ctx.command("stats-reset", help="清空本会话的统计", admin_only=True)
    async def cmd_reset(session, args):
        ctx.store_delete(f"count:{session.session_key}")
        return "本会话的发言统计已清空。"
