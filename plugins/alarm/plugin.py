"""定时提醒 / 闹钟 —— 最实用的一个插件。

每天（或只在工作日）在指定时刻私聊提醒你。支持多个时间点。

用到的能力：
  ctx.at("HH:MM")          每天固定时刻
  ctx.store_*              记住「今天提醒过没有」，避免一小时内连发
  ctx.send(target, 文本)   往你自己私聊发 —— 需要 send_message 权限
"""

NAME = "定时提醒"
VERSION = "1.2.0"
DESCRIPTION = "每天固定时间私聊提醒你（可设多个时间点、可只工作日提醒）。适合吃药、喝水、开会、打卡。"
AUTHOR = "ChatBot 内置示例"

# 这个插件要主动发消息，所以必须声明 —— 面板上你要点一下授权它才能跑
PERMISSIONS = ["send_message"]

DEFAULT_CONFIG = {
    "times": "09:30\n14:30\n21:00",
    "message": "该喝水啦，起来动一动～",
    "weekdays_only": True,
    "channel": "all",
    "only_group_sender": "",
}

CONFIG_SCHEMA = [
    {"key": "times", "type": "text", "label": "提醒时间", "rows": 4,
     "default": "09:30\n14:30\n21:00",
     "help": "一行一个，24 小时制 HH:MM。想只留一个就删掉其它行。"},
    {"key": "message", "type": "text", "label": "提醒内容", "rows": 2,
     "default": "该喝水啦，起来动一动～"},
    {"key": "weekdays_only", "type": "bool", "label": "只在周一到周五提醒", "default": True},
    {"key": "channel", "type": "select", "label": "从哪个渠道找你", "default": "all",
     "options": [
         {"value": "all", "label": "都行（最近说过话的优先）"},
         {"value": "qq", "label": "只走 QQ"},
         {"value": "wechat", "label": "只走微信"},
     ]},
    {"key": "only_group_sender", "type": "string", "label": "只提醒某人（可留空）",
     "default": "", "placeholder": "留空 = 提醒最近说过话的会话",
     "help": "填了之后只往这个人的私聊发（填发送者显示名）"},
]


def _parse_times(raw):
    out = []
    for line in str(raw or "").splitlines():
        text = line.strip()
        if not text:
            continue
        # 容错：允许「9:5」这种不规范写法，补齐成 09:05
        try:
            hour, _, minute = text.partition(":")
            out.append(f"{int(hour):02d}:{int(minute or 0):02d}")
        except ValueError:
            continue
    return out


def permissions(config):
    # 这个插件只做「主动发消息」一件事，固定只要这一个权限
    return ["send_message"]


async def apply(ctx, config):
    import time

    times = _parse_times(config.get("times"))
    if not times:
        ctx.log.warn("没有解析出任何提醒时间，插件不会做任何事（请在面板里填写）")

    async def remind(label):
        if bool(config.get("weekdays_only")) and time.localtime().tm_wday >= 5:
            return
        # ★ 幂等保护：ctx.at 是「每天到点跑一次」，但改配置/重载插件会让
        #   定时器重算，极端情况下同一分钟内可能跑两次。用落盘的日期记一笔，
        #   同一天同一个时间点只提醒一次。
        stamp_key = f"sent:{label}"
        today = time.strftime("%Y-%m-%d")
        if ctx.store_get(stamp_key) == today:
            return
        ctx.store_set(stamp_key, today)

        text = str(config.get("message") or "").strip()
        if not text:
            return

        target = _pick_target(ctx, config)
        if target is None:
            ctx.log.info("还没有任何会话跟机器人说过话，这次提醒跳过")
            return
        if await ctx.send(target, text):
            ctx.log.info(f"已提醒（{label}）-> {target.get('who') or target.get('channel')}")

    # 给每个时间点挂一个定时任务
    for one in times:
        # 闭包捕获：用默认参数把 one 固定住，否则所有任务都会用最后一个值
        @ctx.at(one)
        async def _tick(_label=one):
            await remind(_label)

    @ctx.command("alarm-test", help="立刻试一次提醒", admin_only=True)
    async def cmd_test(session, args):
        target = _pick_target(ctx, config)
        if target is None:
            return "还没有任何会话跟机器人说过话，没法试。"
        ok = await ctx.send(target, str(config.get("message") or "提醒测试"))
        return "测试提醒已发出。" if ok else "发送失败，去看看运行日志。"

    @ctx.command("alarm-times", help="看看设了哪几个时间点")
    async def cmd_times(session, args):
        if not times:
            return "还没设置提醒时间，去面板「插件」页填一下。"
        return "提醒时间：" + "、".join(times) + (
            "（只在工作日）" if config.get("weekdays_only") else "（每天）"
        )

    ctx.log.info(f"已挂载 {len(times)} 个提醒时间点：{'、'.join(times) or '（无）'}")


def _pick_target(ctx, config):
    """挑一个发送目标：优先「用户指定的那个人」，否则最近活跃的会话。"""
    want_channel = str(config.get("channel") or "all")
    who = str(config.get("only_group_sender") or "").strip()
    candidates = ctx.recent_sessions(limit=30)

    if who:
        for item in candidates:
            if item.get("sender") == who or item.get("who") == who:
                return item
    for item in candidates:
        if not item.get("is_group") and (want_channel == "all" or item.get("channel") == want_channel):
            return item
    for item in candidates:
        if want_channel == "all" or item.get("channel") == want_channel:
            return item
    return candidates[0] if candidates else None
