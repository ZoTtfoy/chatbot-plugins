"""网页监控推送 —— 盯页面，变了就通知你。

典型用途：商品价格降了、公告栏出新通知、分数线公布了、某个页面挂没挂。

用到的能力：
  ctx.net.get(url)          抓页面 —— 需要 net 权限
  ctx.ask_model(...)        让模型判断「这次变化是不是你要的那种」
  ctx.every(秒)             定时取一次（不是死循环轮询，有间隔）
  ctx.send(target, 文本)    推给你 —— 需要 send_message 权限
  ctx.to_thread(...)        抓页面这种阻塞活丢线程池，别卡住消息通道

★ 设计上的三个克制（不然这类插件很容易变成「刷屏 + 被封 IP」）：
  1. **默认 10 分钟**才看一次，间隔可调但下限 60 秒
  2. 只在「内容真的变了」时通知，且同一变化**只通知一次**
  3. 连续失败不刷屏：失败只记日志，连续失败 5 次才提醒你一次「这个页面一直抓不到」
"""

NAME = "网页监控推送"
VERSION = "1.1.0"
DESCRIPTION = "定时盯一个网页，内容有变化就通知你。可选让模型判断「这次变化值不值得通知」。"
AUTHOR = "ChatBot 内置示例"

PERMISSIONS = ["net", "send_message"]

DEFAULT_CONFIG = {
    "urls": "",
    "interval_minutes": 10,
    "change_mode": "any",
    "keywords": "",
    "ask_model": False,
    "notify_message": "你盯的页面有变化了：{url}\n变化摘要：{summary}",
}

CONFIG_SCHEMA = [
    {"key": "urls", "type": "text", "label": "要盯的网址", "rows": 3,
     "default": "", "placeholder": "https://example.com/price\nhttps://example.com/notice",
     "help": "一行一个，最多 5 个"},
    {"key": "interval_minutes", "type": "int", "label": "多久看一次（分钟）",
     "default": 10, "min": 1, "max": 1440,
     "help": "别设太短，很多站点会封频繁访问的 IP"},
    {"key": "change_mode", "type": "select", "label": "什么算「变化」", "default": "any",
     "options": [
         {"value": "any", "label": "内容变了就通知"},
         {"value": "keyword", "label": "出现指定关键词才通知"},
         {"value": "model", "label": "让模型判断值不值得通知"},
     ]},
    {"key": "keywords", "type": "text", "label": "关键词（change_mode 选关键词时用）",
     "rows": 3, "default": "", "placeholder": "降价\n有货\n已发布",
     "help": "一行一个，出现任意一个就通知"},
    {"key": "notify_message", "type": "text", "label": "通知文案", "rows": 3,
     "default": "你盯的页面有变化了：{url}\n变化摘要：{summary}",
     "help": "可用占位符：{url} 网址、{summary} 变化摘要、{old} 旧内容片段、{new} 新内容片段"},
]


def _parse_list(raw, limit=5):
    out = []
    for line in str(raw or "").splitlines():
        text = line.strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _clean(html):
    """把 HTML 压成纯文本，去掉无关噪声 —— 不然「随机广告位变了」也会触发通知。"""
    import re

    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def apply(ctx, config):
    interval = max(60, int(config.get("interval_minutes") or 10) * 60)

    def current_urls():
        # 每次都重新读配置：用户改完网址不用重载插件就能生效
        return _parse_list(config.get("urls"))

    async def check_all():
        for url in current_urls():
            await _check_one(ctx, config, url)

    # ★ 指令要**先注册**，再判断有没有配置 —— 否则用户刚启用、还没填网址时
    #   连"看看状态"的指令都不存在，会以为插件坏了。
    @ctx.command("watch-now", help="立刻检查一次", admin_only=True)
    async def cmd_now(session, args):
        urls = current_urls()
        if not urls:
            return "还没配置网址。去面板「插件」页填上要盯的页面。"
        await check_all()
        return f"已检查 {len(urls)} 个页面（结果见运行日志）。"

    @ctx.command("watch-list", help="看看盯了哪些页面")
    async def cmd_list(session, args):
        urls = current_urls()
        if not urls:
            return "还没配置网址。去面板「插件」页填上要盯的页面（一行一个）。"
        lines = []
        for url in urls:
            recorded = bool(ctx.store_get(f"hash:{url}"))
            lines.append(f"· {url}（{'已记录基线' if recorded else '等第一次抓取'}）")
        return "\n".join(lines)

    urls = current_urls()
    if not urls:
        ctx.log.warn(
            "还没有配置网址，暂时不会监控任何页面。"
            "去面板「插件」页填上要盯的页面即可生效（不用重载插件）。"
        )
        return

    @ctx.every(interval)
    async def _tick():
        await check_all()

    ctx.log.info(f"开始盯 {len(urls)} 个页面，每 {interval // 60} 分钟一次")


async def _check_one(ctx, config, url):
    """抓一个页面并判断要不要通知。整个函数不抛异常 —— 一个网址出问题不影响别的。"""
    try:
        resp = await ctx.net.get(url, timeout=20.0)
    except Exception as exc:  # noqa: BLE001
        await _note_failure(ctx, url, f"{type(exc).__name__}: {exc}")
        return

    if not resp.ok:
        await _note_failure(ctx, url, f"HTTP {resp.status}")
        return
    ctx.store_set(f"fail:{url}", 0)

    text = _clean(resp.text)
    if not text:
        return

    import hashlib

    digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
    old_digest = ctx.store_get(f"hash:{url}")
    old_text = str(ctx.store_get(f"text:{url}") or "")
    ctx.store_set(f"text:{url}", text[:8000])

    if old_digest is None:
        ctx.store_set(f"hash:{url}", digest)
        ctx.log.info(f"已记录 {url} 的基线（第一次抓取，不通知）")
        return
    if old_digest == digest:
        return

    ctx.store_set(f"hash:{url}", digest)

    summary = _diff_summary(old_text, text)
    mode = str(config.get("change_mode") or "any")

    if mode == "keyword":
        keywords = _parse_list(config.get("keywords"), limit=50)
        hit = [k for k in keywords if k and k in text]
        if not hit:
            ctx.log.info(f"{url} 有变化但没命中关键词，跳过")
            return
        summary = f"命中关键词：{'、'.join(hit)}；{summary}"
    elif mode == "model":
        verdict = await _ask_worth(ctx, url, old_text, text)
        if not verdict["worth"]:
            ctx.log.info(f"{url} 有变化，模型判断不值得通知：{verdict['reason'][:40]}")
            return
        summary = verdict["summary"] or summary

    template = str(config.get("notify_message") or "{url} 有变化")
    message = (
        template.replace("{url}", url)
        .replace("{summary}", summary)
        .replace("{old}", old_text[:120])
        .replace("{new}", text[:120])
    )
    target = _pick_target(ctx)
    if target is None:
        ctx.log.info("还没有任何会话跟机器人说过话，这次变化没法通知")
        return
    if await ctx.send(target, message):
        ctx.log.info(f"已推送 {url} 的变化 -> {target.get('who')}")


async def _ask_worth(ctx, url, old_text, new_text):
    """让模型判断这次变化值不值得通知。

    返回 {"worth": bool, "summary": str, "reason": str}。
    ★ 模型不可用/解析失败时**默认认为值得通知** —— 宁可多推一次，
      也不要因为模型抽风把该知道的事漏掉。
    """
    prompt = (
        "我在监控一个网页，它刚刚变化了。请判断这次变化是否值得提醒我。\n\n"
        f"网址：{url}\n\n"
        f"【之前的内容片段】\n{old_text[:800]}\n\n"
        f"【现在的内容片段】\n{new_text[:800]}\n\n"
        "只输出一行 JSON，不要任何其它文字：\n"
        '{"worth": true/false, "summary": "一句话说清变化了什么", '
        '"reason": "为什么值得/不值得"}'
    )
    try:
        raw = await ctx.ask_model(prompt, system="你是一个精准的信息筛选助手。")
    except Exception:  # noqa: BLE001
        return {"worth": True, "summary": "", "reason": "模型调用失败，默认通知"}
    if not raw:
        return {"worth": True, "summary": "", "reason": "模型没返回内容，默认通知"}

    import json
    import re

    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return {"worth": True, "summary": raw[:80], "reason": "模型输出无法解析，默认通知"}
    try:
        data = json.loads(match.group(0))
    except Exception:  # noqa: BLE001
        return {"worth": True, "summary": raw[:80], "reason": "模型输出不是合法 JSON，默认通知"}
    return {
        "worth": bool(data.get("worth", True)),
        "summary": str(data.get("summary") or ""),
        "reason": str(data.get("reason") or ""),
    }


async def _note_failure(ctx, url, reason):
    """连续失败才提醒，避免站点挂了一天给你刷几百条。"""
    count = int(ctx.store_get(f"fail:{url}", 0) or 0) + 1
    ctx.store_set(f"fail:{url}", count)
    ctx.log.warn(f"抓取 {url} 失败（第 {count} 次）：{reason}")
    if count == 5:
        target = _pick_target(ctx)
        if target is not None:
            await ctx.send(target, f"⚠️ 这个页面连续 5 次抓不到了：{url}\n原因：{reason}")


def _diff_summary(old_text, new_text):
    """给出一句人话的变化摘要（不追求精确 diff，够看懂就行）。"""
    if not old_text:
        return "首次记录后的第一次变化"
    old_len, new_len = len(old_text), len(new_text)
    if new_len > old_len:
        return f"内容变长了（{old_len} → {new_len} 字）"
    if new_len < old_len:
        return f"内容变短了（{old_len} → {new_len} 字）"
    return "内容有改动（长度没变）"


def _pick_target(ctx):
    candidates = ctx.recent_sessions(limit=30)
    for item in candidates:
        if not item.get("is_group"):
            return item
    return candidates[0] if candidates else None
