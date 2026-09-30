"""定时播报 —— 演示「定时任务 + 主动发消息」。

两个能力在这一个插件里都用到了：

  ctx.at("08:30")        每天固定时刻跑一次（还有 ctx.every(秒) 是隔多久跑一次）
  ctx.recent_sessions()  最近活跃过的会话
  ctx.send(target, 文本) 主动往某个会话发消息（不是回复）

★ 定时任务是**跟着插件生命周期走**的：插件一停用，任务自动取消，
  不会出现「插件关了它还在后台刷消息」的幽灵。

★ 往哪儿播报：用的是「最近说过话的会话」。这样你不需要去记群号 / wxid，
  机器人见过谁就能发给谁。想固定发给某几个会话，把 broadcast_all 关掉、
  看下面 allowed 的说明。
"""

NAME = "定时播报"
VERSION = "1.0.0"
DESCRIPTION = "每天固定时刻，往最近活跃的会话发一条消息（早安、值班表、每日一句等都行）。"
AUTHOR = "ChatBot 内置示例"

# ★ ctx.send（往别的会话主动发消息）需要这个权限；
#   ctx.reply（回当前会话）不需要。定时播报是典型的「主动发」，所以要声明。
PERMISSIONS = ["send_message"]

DEFAULT_CONFIG = {
    "time": "08:30",
    "message": "早上好呀，新的一天也要好好的～",
    "limit": 3,
    "channels": "all",
    "weekdays_only": False,
}

CONFIG_SCHEMA = [
    {"key": "time", "type": "string", "label": "每天几点发", "default": "08:30",
     "placeholder": "08:30", "help": "24 小时制，格式 HH:MM"},
    {"key": "message", "type": "text", "label": "播报内容", "default": "早上好呀，新的一天也要好好的～",
     "rows": 4},
    {"key": "limit", "type": "int", "label": "最多发给几个会话", "default": 3,
     "min": 1, "max": 20, "help": "取最近聊过天的会话，最新的优先"},
    {"key": "channels", "type": "select", "label": "发到哪个渠道", "default": "all",
     "options": [
         {"value": "all", "label": "QQ 和微信都发"},
         {"value": "qq", "label": "只发 QQ"},
         {"value": "wechat", "label": "只发微信"},
     ]},
    {"key": "weekdays_only", "type": "bool", "label": "只在周一到周五发", "default": False},
]


async def apply(ctx, config):
    import time

    async def broadcast():
        if bool(config.get("weekdays_only")) and time.localtime().tm_wday >= 5:
            ctx.log.info("今天是周末，按配置跳过播报")
            return

        want = str(config.get("channels") or "all")
        limit = max(1, int(config.get("limit") or 1))
        targets = [
            item for item in ctx.recent_sessions(limit=20)
            if want == "all" or item.get("channel") == want
        ][:limit]
        if not targets:
            ctx.log.info("还没有任何会话跟机器人说过话，今天不播报")
            return

        sent = 0
        for target in targets:
            if await ctx.send(target, str(config.get("message") or "")):
                sent += 1
        ctx.log.info(f"已播报给 {sent}/{len(targets)} 个会话")

    @ctx.at(str(config.get("time") or "08:30"))
    async def _daily():
        await broadcast()

    @ctx.command("broadcast", help="立刻播报一次（测试用）", admin_only=True)
    async def cmd_broadcast(session, args):
        await broadcast()
        return "播报已发出，去看最近的会话吧。"
