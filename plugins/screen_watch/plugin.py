"""屏幕监控告警 —— 定时截屏，让模型判断屏幕上有没有你要盯的东西。

真正「不局限于文字」的例子：插件去看你的屏幕，命中了才通知你。

典型用途：
  · 挂机跑的程序弹了报错窗口 → 立刻通知你
  · 长任务进度条卡住了 → 通知（判断「进度条超过 N 分钟没动」）
  · 网页在等验证码 / 排队到号了 → 通知
  · 某个页面出现了「有货」「已发布」字样 → 通知

用到的能力：
  ctx.desktop.screenshot()  —— 需要 desktop 权限（只是「看」，不需要动手）
  ctx.image_block(png)      把截图转成模型能看的内容块（复用宿主那套压缩）
  ctx.ask_model(...)        问模型「图里有这个吗」
  ctx.send(target, 文本)    通知你 —— 需要 send_message 权限

★ 这个插件**只声明 desktop，不声明 input** —— 它只看，不动你的鼠标键盘。
  这是权限分级的意义：监控类需求不需要把「动手」的能力也交出去。
"""

NAME = "屏幕监控告警"
VERSION = "1.1.0"
DESCRIPTION = "定时截屏交给模型判断，屏幕上出现你指定的内容就通知你。只读屏幕，不动鼠标键盘。"
AUTHOR = "ChatBot 内置示例"

PERMISSIONS = ["desktop", "send_message"]

DEFAULT_CONFIG = {
    "interval_seconds": 120,
    "question": "屏幕上是否出现了错误提示弹窗、或者写着「失败」「异常」的窗口？",
    "cooldown_minutes": 10,
    "region": "",
    "notify_message": "⚠️ 屏幕监控命中：{reason}",
    "only_when_idle": False,
}

CONFIG_SCHEMA = [
    {"key": "interval_seconds", "type": "int", "label": "多久看一次（秒）",
     "default": 120, "min": 20, "max": 3600,
     "help": "太短会一直消耗模型额度，建议 60 秒以上"},
    {"key": "question", "type": "text", "label": "要判断什么", "rows": 3,
     "default": "屏幕上是否出现了错误提示弹窗、或者写着「失败」「异常」的窗口？",
     "help": "用一句大白话描述你想被提醒的情况"},
    {"key": "cooldown_minutes", "type": "int", "label": "命中后的静默期（分钟）",
     "default": 10, "min": 1, "max": 1440,
     "help": "同一个问题持续存在时，别一直通知你"},
    {"key": "region", "type": "string", "label": "只看屏幕的某块区域（可留空）",
     "default": "", "placeholder": "留空 = 整屏；否则填 左,上,右,下 例如 0,0,1920,600",
     "help": "只看一小块能省很多 token"},
    {"key": "notify_message", "type": "text", "label": "通知文案", "rows": 2,
     "default": "⚠️ 屏幕监控命中：{reason}", "help": "可用占位符 {reason}"},
    {"key": "only_when_idle", "type": "bool", "label": "只在你不用电脑时检查",
     "default": False, "help": "打开后鼠标 60 秒没动才截屏，免得打扰你"},
]


def _parse_region(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parts = [int(x) for x in text.replace("，", ",").split(",")]
        if len(parts) == 4:
            return tuple(parts)  # type: ignore[return-value]
    except ValueError:
        pass
    return None


async def apply(ctx, config):
    import json
    import re
    import time

    def current_region():
        # 每次现读：改完区域不用重载插件（配置是就地更新的）
        return _parse_region(config.get("region"))

    async def check(say=None):
        """看一次屏幕。``say`` 传了函数就把结论回给调用方（手动触发时用）。"""
        question = str(config.get("question") or "").strip()
        if not question:
            if say:
                say("还没填「要判断什么」，没法看。去面板里写一句大白话。")
            return

        if bool(config.get("only_when_idle")):
            try:
                idle = await ctx.to_thread(_idle_seconds)
            except Exception:  # noqa: BLE001
                idle = 999
            if idle < 60:
                if say:
                    say(f"你正在用电脑（{idle:.0f} 秒前还在动鼠标），按配置这次跳过。")
                return

        # ★ 截图是阻塞操作，必须丢线程池 —— 否则整个消息通道跟着卡住
        try:
            png = await ctx.to_thread(ctx.desktop.screenshot, current_region())
        except Exception as exc:  # noqa: BLE001
            ctx.log.warn(f"截屏失败：{exc}")
            if say:
                say(f"截屏失败：{exc}")
            return

        block = await ctx.image_block(png)
        if block is None:
            ctx.log.warn("截图无法转成模型能看的内容块，本轮跳过")
            if say:
                say("截图转不出模型能看的内容块（图片处理组件可能没装好），这次跳过。")
            return

        prompt = (
            "这是一张电脑屏幕截图。请回答下面这个问题，并且只输出一行 JSON：\n"
            f"{question}\n\n"
            '{"hit": true/false, "reason": "如果命中，用一句话说明你看到了什么"}'
        )
        try:
            raw = await ctx.ask_model(
                [{"type": "text", "text": prompt}, block],
                system="你是一个屏幕监控助手，只看事实，不猜测。",
            )
        except Exception as exc:  # noqa: BLE001
            ctx.log.warn(f"模型判断失败：{exc}")
            if say:
                say(f"模型判断失败：{exc}")
            return
        if not raw:
            if say:
                say("模型没返回内容，这次跳过（看运行日志）。")
            return

        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            ctx.log.warn(f"模型输出无法解析，跳过：{raw[:80]}")
            if say:
                say(f"模型输出解析不了，这次跳过：{raw[:80]}")
            return
        try:
            data = json.loads(match.group(0))
        except Exception:  # noqa: BLE001
            ctx.log.warn(f"模型输出不是合法 JSON，跳过：{raw[:80]}")
            if say:
                say(f"模型输出不是合法 JSON，这次跳过：{raw[:80]}")
            return

        reason = str(data.get("reason") or "屏幕出现你关注的内容")
        if not data.get("hit"):
            ctx.log.info(f"看了一眼，没命中（{reason[:40]}）")
            if say:
                say(f"没命中。模型的判断：{reason}")
            return

        # 静默期：同一个问题持续存在时别一直通知
        cooldown = max(1, int(config.get("cooldown_minutes") or 10)) * 60
        last = float(ctx.store_get("last_hit", 0) or 0)
        if time.time() - last < cooldown:
            ctx.log.info("命中但还在静默期内，跳过通知")
            if say:
                say(f"命中了（{reason}），但还在静默期里，这次不重复通知。")
            return
        ctx.store_set("last_hit", time.time())

        template = str(config.get("notify_message") or "⚠️ 屏幕监控命中：{reason}")
        target = _pick_target(ctx)
        if target is None:
            ctx.log.info(f"命中（{reason}）但还没有可通知的会话")
            if say:
                say(f"命中了（{reason}），但还没有任何会话跟机器人说过话，没地方通知。")
            return
        text = template.replace("{reason}", reason)
        if await ctx.send(target, text):
            ctx.log.info(f"已发出屏幕告警：{reason}")
            if say:
                say(f"命中并已通知：{reason}")
        elif say:
            say(f"命中（{reason}）但发送失败，看运行日志。")

    interval = max(20, int(config.get("interval_seconds") or 120))

    @ctx.every(interval)
    async def _tick():
        await check()

    @ctx.command("screen-now", help="立刻看一次屏幕并给出判断结论", admin_only=True)
    async def cmd_now(session, args):
        holder = []
        # ★ 以前这里只截了张图就回「判断结果见运行日志」，但根本没跑判断 ——
        #   用户点完以为查过了，其实什么都没发生。现在真的走一遍完整流程。
        await check(say=holder.append)
        return holder[0] if holder else "这次没有产生结论（看运行日志）。"

    @ctx.command("screen-size", help="看看屏幕分辨率")
    async def cmd_size(session, args):
        try:
            w, h = await ctx.to_thread(ctx.desktop.screen_size)
        except Exception as exc:  # noqa: BLE001
            return f"读取失败：{exc}"
        region = current_region()
        return (f"屏幕分辨率：{w} x {h}"
                + (f"；当前只看区域 {region}" if region else "；当前看整屏"))

    ctx.log.info(
        f"屏幕监控已开启，每 {interval} 秒看一眼"
        f"（只读屏幕，不动鼠标键盘；只看 {current_region() or '整屏'}）"
    )


def _idle_seconds():
    """鼠标多久没动过（秒）。用 GetLastInputInfo。"""
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 999.0
    millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
    return max(0.0, millis / 1000.0)


def _pick_target(ctx):
    candidates = ctx.recent_sessions(limit=30)
    for item in candidates:
        if not item.get("is_group"):
            return item
    return candidates[0] if candidates else None
