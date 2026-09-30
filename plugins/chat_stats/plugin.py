"""发言统计 —— 演示「插件私有存储 + 调模型」。

用到的东西：

  ctx.store_get / ctx.store_set / ctx.store_all   插件自己的小仓库（JSON 落盘）
  ctx.on("message")                                旁听每条消息
  ctx.ask_model(...)                               让模型帮忙说句人话

★ 为什么用 store 而不是直接读机器人的数据库：插件的存储是**独立文件**，
  插件被卸载时一起带走，不会污染主库；插件也读不到别人的数据。

★ 两个容易踩的工程点，这个插件都示范了怎么处理：
  1. **不要每条消息都读改写整个统计表**。它挂在每条消息上，一个热闹的群
     就是每条消息一次读盘 + 一次全量写盘，而且数据越攒越大。
     正确做法是内存累加 + 定时批量落盘（见下面 counts / flush）。
  2. **身份键要用稳定 id，不能用昵称**。昵称一改，历史计数就断成两个人；
     昵称本身只用来显示，每次更新成最新的。
"""

NAME = "发言统计"
VERSION = "1.1.0"
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

# 攒够多少条 / 最多隔多久落一次盘
_FLUSH_EVERY = 20
_FLUSH_SECONDS = 5.0


def _normalize(raw):
    """把存储里的数据统一成 ``{身份键: {"n": 次数, "name": 显示名}}``。

    兼容老版本留下的 ``{昵称: 次数}`` 格式 —— 用户升级插件不该丢数据。
    """
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        if isinstance(value, dict):
            try:
                out[str(key)] = {"n": int(value.get("n") or 0),
                                 "name": str(value.get("name") or key)}
            except (TypeError, ValueError):
                continue
        else:
            try:
                out[str(key)] = {"n": int(value), "name": str(key)}
            except (TypeError, ValueError):
                continue
    return out


def _ident_of(session):
    """统计用的稳定身份键 + 显示名。

    ★ 优先用 sender_id：昵称随时能改，id 不会。用昵称当键的话，
      同一个人改个群名片就被算成两个人了。
    """
    sender_id = getattr(session, "sender_id", None)
    name = str(session.sender or session.who or "未知").strip() or "未知"
    if sender_id not in (None, ""):
        return f"#{sender_id}", name
    return name, name


async def apply(ctx, config):
    import time

    counts: dict = {}      # session_key -> {ident: {"n": int, "name": str}}
    dirty: set = set()     # 哪些 session 还没落盘
    pending = [0]          # 距离上次落盘攒了多少条

    def board_of(session_key):
        if session_key not in counts:
            counts[session_key] = _normalize(ctx.store_get(f"count:{session_key}"))
        return counts[session_key]

    def flush() -> None:
        """把内存里的计数落盘。

        ★ 现在只在这里写盘，而不是每条消息一次 —— 原来每条消息都要
          「读整个 dict → 改一个数 → 整个写回去」，群一热闹就是纯 IO 瓶颈。
          最坏情况只丢最近几秒的计数，对"谁最能聊"这种统计完全无所谓。
        """
        if not dirty:
            return
        for key in list(dirty):
            ctx.store_set(f"count:{key}", counts.get(key) or {})
            dirty.discard(key)
        pending[0] = 0

    def maybe_flush() -> None:
        """攒够 20 条落一次盘；没攒够就交给定时落盘兜底。"""
        pending[0] += 1
        if pending[0] >= _FLUSH_EVERY:
            flush()

    @ctx.on("message")
    async def count(session):
        """旁听钩子：只看不改。注意它**没有返回值**语义，改不了消息内容。"""
        if not session.sender:
            return
        ident, name = _ident_of(session)
        board = board_of(session.session_key)
        entry = board.setdefault(ident, {"n": 0, "name": name})
        entry["n"] = int(entry.get("n", 0)) + 1
        entry["name"] = name          # 昵称跟着最新的一次走
        dirty.add(session.session_key)
        maybe_flush()

    @ctx.on("stop")
    async def on_stop():
        # 停用/重载前把攒着的一次性写掉，不然这几秒的发言就没了
        flush()

    @ctx.on("bot_stop")
    async def on_bot_stop():
        # 程序关停同理
        flush()

    # 兜底：冷清的时候可能一直是"攒了 3 条但没到 20 条"，
    # 靠这个定时器把它写下去，免得一直挂着不落盘。
    @ctx.every(_FLUSH_SECONDS * 2)
    async def _flush_tick():
        flush()

    @ctx.command("stats", aliases=("排行",), help="看看谁最能聊")
    async def cmd_stats(session, args):
        board = board_of(session.session_key)
        if not board:
            return "这个会话我还没统计到发言呢，大家多说几句再来看看～"

        limit = max(1, int(config.get("top") or 5))
        ranked = sorted(board.items(), key=lambda kv: int(kv[1].get("n") or 0), reverse=True)
        ranked = ranked[:limit]
        total = sum(int(v.get("n") or 0) for v in board.values())

        lines = [f"本会话共 {total} 条发言、{len(board)} 人参与。前 {len(ranked)} 名："]
        for index, (_ident, item) in enumerate(ranked, 1):
            lines.append(f"{index}. {item.get('name') or '?'} —— {item.get('n', 0)} 条")
        board_text = "\n".join(lines)

        if not bool(config.get("comment")):
            return board_text
        # 让模型点评一句；失败也不影响榜单本身（ask_model 出错返回空串）
        comment = await ctx.ask_model(
            f"这是一个聊天群里的发言排行榜：\n{board_text}\n"
            f"请用一句轻松俏皮的中文点评一下（不超过 30 字，不要用 Markdown）。",
            system="你是一个活泼的聊天机器人，说话简短有趣。",
        )
        return f"{board_text}\n\n{comment}" if comment else board_text

    @ctx.command("stats-reset", help="清空本会话的统计", admin_only=True)
    async def cmd_reset(session, args):
        counts.pop(session.session_key, None)
        dirty.discard(session.session_key)
        ctx.store_delete(f"count:{session.session_key}")
        return "本会话的发言统计已清空。"

    @ctx.command("stats-where", help="看看统计存在哪几个会话里", admin_only=True)
    async def cmd_where(session, args):
        keys = sorted(set(counts) | {k[6:] for k in ctx.store_all()
                                     if isinstance(k, str) and k.startswith("count:")})
        if not keys:
            return "还没有任何统计。"
        return "已统计的会话：\n" + "\n".join(f"· {k}" for k in keys)
