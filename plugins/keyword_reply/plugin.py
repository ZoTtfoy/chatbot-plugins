"""关键词自动回复 —— 演示「消息中间件」怎么用。

中间件（middleware）跑在「消息交给模型之前」，可以做三件事：

    return None     不发表意见，交给下一个中间件（消息照常发给模型）
    return "文本"    把这条消息的正文**改写**掉，再继续往下走
    return ctx.STOP  到此为止：不调模型了（回什么由插件自己决定）

这个插件命中关键词就直接回一句，省掉一次模型调用 —— 常见问题（价格、
地址、群规）用这个最划算，又快又不要钱。
"""

NAME = "关键词自动回复"
VERSION = "1.0.0"
DESCRIPTION = "命中关键词就自动回一句，不再走模型。适合群规、价格、联系方式这类固定问答。"
AUTHOR = "ChatBot 内置示例"

DEFAULT_CONFIG = {
    "rules": "帮助=有问题直接说，我一直在\n公告=本群禁止刷屏和广告",
    "exact": False,
    "cooldown": 5,
}

CONFIG_SCHEMA = [
    {
        "key": "rules",
        "type": "text",
        "label": "回复规则",
        "default": "帮助=有问题直接说，我一直在\n公告=本群禁止刷屏和广告",
        "rows": 8,
        "help": "一行一条，格式：关键词=回复内容。等号前后不要加空格。",
    },
    {
        "key": "exact",
        "type": "bool",
        "label": "必须完全一致",
        "default": False,
        "help": "关掉时只要消息里包含关键词就命中（推荐）",
    },
    {
        "key": "cooldown",
        "type": "int",
        "label": "同一会话冷却（秒）",
        "default": 5,
        "min": 0,
        "max": 600,
        "help": "防止有人连刷同一个关键词把机器人刷屏；0 表示不限制",
    },
]


def _parse_rules(raw):
    """把「关键词=回复」的多行文本解析成字典。

    ★ 这里体现一个原则：**配置写错不能让插件崩**。
      用户手写的东西一定会有格式问题，解析不了的直接跳过、记一行日志，
      剩下的照常工作 —— 比整个插件加载失败友好得多。
    """
    rules = {}
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keyword, _, reply = line.partition("=")
        keyword, reply = keyword.strip(), reply.strip()
        if keyword and reply:
            rules[keyword] = reply
    return rules


async def apply(ctx, config):
    rules = _parse_rules(config.get("rules"))
    exact = bool(config.get("exact"))
    cooldown = max(0, int(config.get("cooldown") or 0))
    ctx.log.info(f"已加载 {len(rules)} 条关键词规则")

    @ctx.middleware(priority=10)
    async def keyword_mw(session, text):
        if not rules or not text:
            return None

        hit = None
        lowered = text.strip().lower()
        for keyword, reply in rules.items():
            if (lowered == keyword.lower()) if exact else (keyword.lower() in lowered):
                hit = (keyword, reply)
                break
        if hit is None:
            return None

        # 冷却：按「会话 + 关键词」记时间戳，避免同一句被反复触发
        if cooldown:
            key = f"cd:{session.session_key}:{hit[0]}"
            last = ctx.store_get(key, 0) or 0
            if __import__("time").time() - float(last) < cooldown:
                return ctx.STOP  # 冷却中：直接吞掉，别让它再去打扰模型
            ctx.store_set(key, __import__("time").time())

        await ctx.reply(session, hit[1])
        return ctx.STOP  # 已经回过了，这条消息到此为止
