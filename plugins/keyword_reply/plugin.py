"""关键词自动回复 —— 演示「消息中间件」怎么用。

中间件（middleware）跑在「消息交给模型之前」，可以做三件事：

    return None     不发表意见，交给下一个中间件（消息照常发给模型）
    return "文本"    把这条消息的正文**改写**掉，再继续往下走
    return ctx.STOP  到此为止：不调模型了（回什么由插件自己决定）

这个插件命中关键词就直接回一句，省掉一次模型调用 —— 常见问题（价格、
地址、群规）用这个最划算，又快又不要钱。
"""

NAME = "关键词自动回复"
VERSION = "1.1.0"
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
    import time

    # ★ 规则「按需解析 + 缓存」：用户在面板改完规则，**下一条消息就生效**，
    #   不用重载插件（apply 只在启用时跑一次，规则若在启用时解析好就冻住了）。
    #   缓存按原文比对，没改就复用上一次的结果，不用每条消息都重新解析。
    cache = {"raw": None, "rules": []}

    def current_rules():
        raw = str(config.get("rules") or "")
        if cache["raw"] != raw:
            cache["raw"] = raw
            # 长的关键词排前面：「帮助中心」必须先于「帮助」命中 ——
            # 否则用户特意加了更具体的关键词，也永远轮不到它。
            cache["rules"] = sorted(
                _parse_rules(raw).items(), key=lambda kv: len(kv[0]), reverse=True
            )
            ctx.log.info(f"关键词规则已生效，共 {len(cache['rules'])} 条")
        return cache["rules"]

    @ctx.middleware(priority=10)
    async def keyword_mw(session, text):
        rules = current_rules()
        if not rules or not text:
            return None

        exact = bool(config.get("exact"))
        cooldown = max(0, int(config.get("cooldown") or 0))
        lowered = text.strip().lower()

        hit = None
        for keyword, reply in rules:
            if (lowered == keyword.lower()) if exact else (keyword.lower() in lowered):
                hit = (keyword, reply)
                break
        if hit is None:
            return None

        # 冷却：按「会话 + 关键词」记时间戳，避免同一句被反复触发。
        # ★ 冷却只决定「要不要自动回」，不决定「这条消息要不要给模型」。
        #   原来这里 return ctx.STOP，等于冷却期内的消息被整个吞掉 ——
        #   用户连问两次「帮助」，第二次既没有自动回复、模型也收不到，
        #   从用户视角看就是"机器人突然不说话了"。宁可让模型多回一次，
        #   也不能静默吞消息。
        if cooldown:
            key = f"cd:{session.session_key}:{hit[0].lower()}"
            now = time.time()
            last = float(ctx.store_get(key, 0) or 0)
            if now - last < cooldown:
                ctx.log.info(f"关键词「{hit[0]}」还在冷却里，这条交给模型处理")
                return None
            ctx.store_set(key, now)

        await ctx.reply(session, hit[1])
        return ctx.STOP  # 已经回过了，这条消息到此为止
