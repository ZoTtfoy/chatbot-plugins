"""红包助手 —— 默认只是「提醒你」，自动抢需要你明确打开并单独授权。

════════════════════════════════════════════════════════════════════════
★★★  必读  ★★★
════════════════════════════════════════════════════════════════════════

1. **自动抢红包违反腾讯的用户协议**，属于外挂行为。一旦被风控命中，
   你的账号可能被限制或冻结 —— 这是真实的、已经发生过很多次的风险。
   群里用还容易被骂。默认模式是「提醒」，抢不抢你自己决定。

2. **技术上它也不可靠**。「自动抢」是模拟鼠标去点屏幕上的红包气泡，
   能不能点中取决于：窗口位置、有没有被别的窗口挡住、微信/QQ 的界面版本、
   消息有没有被刷上去。没有任何纯 UI 方案能保证 100%。
   本插件用的是**模板匹配**（你自己截一张红包气泡的小图给它认），
   这是目前最稳的做法；认不出就会跳过并记日志，不会乱点。

3. **它在你的屏幕上真的会动鼠标**。所以：
   · 默认 `dry_run = true`：只检测、只打日志，**不点击**。
     你先开一两天，确认检测准不准、日志对不对，再考虑关掉它。
   · 群里默认**不放行**（群白名单是空的），要抢必须在白名单里明确列出群名。
   · 有每小时 / 每天的次数上限，有静默期，防止跑飞。
   · 每次动作都写日志和审计，事后能查它点了哪里。

════════════════════════════════════════════════════════════════════════

模式说明：

  notify（默认）  检测到红包就在**当前会话**回一句提醒你。
                  不需要任何权限，也不会碰你的鼠标。
  grab            切到聊天窗口 → 模板匹配找到红包气泡 → 点击 →
                  再找「開」按钮点击。需要 desktop + input 权限。

权限是**按模式动态要的**：只提醒时一个权限都不要；切到 grab 才会要
「读取屏幕」和「模拟鼠标键盘」。这也是为什么这个插件用的是
`def permissions(config)` 而不是写死的 PERMISSIONS。
"""

NAME = "红包助手"
VERSION = "1.0.0"
DESCRIPTION = ("默认只提醒你「有红包来了」，不会碰你的鼠标。"
               "自动抢需要你显式开启并单独授权 —— 它违反腾讯用户协议、有封号风险，"
               "而且纯 UI 方案不可能 100% 点中，请先开 dry_run 观察。")
AUTHOR = "ChatBot 内置示例"

DEFAULT_CONFIG = {
    "mode": "notify",
    "dry_run": True,
    "notify_message": "🧧 {who} 有红包，快去看！",
    "window_keyword": "微信",
    "bubble_template": "bubble.png",
    "open_template": "open.png",
    "match_confidence": 0.88,
    "fallback_click": "",
    "fallback_open_click": "",
    "group_whitelist": "",
    "max_per_hour": 5,
    "max_per_day": 30,
    "cooldown_seconds": 3,
}

CONFIG_SCHEMA = [
    {"key": "mode", "type": "select", "label": "模式", "default": "notify",
     "options": [
         {"value": "notify", "label": "只提醒（不碰鼠标，安全）"},
         {"value": "grab", "label": "自动抢（需要授权，风险自负）"},
     ],
     "help": "改完保存后若切到「自动抢」，插件会自动停用并提示你重新授权"},
    {"key": "dry_run", "type": "bool", "label": "只演练不点击（强烈建议先开着）",
     "default": True,
     "help": "打开时只检测 + 打日志，绝不点击。观察一两天确认检测准确后再关。"},
    {"key": "notify_message", "type": "text", "label": "提醒文案", "rows": 2,
     "default": "🧧 {who} 有红包，快去看！", "help": "可用占位符 {who} 会话名"},
    {"key": "window_keyword", "type": "string", "label": "聊天窗口标题包含",
     "default": "微信", "help": "抢红包时要切到这个窗口。QQ 就填「QQ」。"},
    {"key": "bubble_template", "type": "string", "label": "红包气泡模板图文件名",
     "default": "bubble.png",
     "help": "把一张红包气泡的小截图（约 200x80）放进插件目录，填文件名。"
             "这是能不能点中的关键 —— 截得越干净越准。"},
    {"key": "open_template", "type": "string", "label": "「開」按钮模板图文件名",
     "default": "open.png", "help": "点开红包后那个「開」字按钮的小截图"},
    {"key": "match_confidence", "type": "float", "label": "模板匹配相似度阈值",
     "default": 0.88, "min": 0.5, "max": 1.0, "step": 0.01,
     "help": "调低更容易命中但可能点错地方；建议 0.85~0.92"},
    {"key": "fallback_click", "type": "string", "label": "兜底点击位置（可留空）",
     "default": "", "placeholder": "例如 1200,860",
     "help": "模板匹配失败时点这里。留空 = 失败就放弃（推荐）"},
    {"key": "fallback_open_click", "type": "string", "label": "兜底「開」位置（可留空）",
     "default": "", "placeholder": "例如 960,540"},
    {"key": "group_whitelist", "type": "text", "label": "允许自动抢的群（必须显式列出）",
     "rows": 3, "default": "",
     "placeholder": "家人群\n同事群",
     "help": "留空 = 群里一律不抢，只在私聊里抢。这是防止它在所有群里乱抢的闸门。"},
    {"key": "max_per_hour", "type": "int", "label": "每小时上限", "default": 5, "min": 1, "max": 100},
    {"key": "max_per_day", "type": "int", "label": "每天上限", "default": 30, "min": 1, "max": 1000},
    {"key": "cooldown_seconds", "type": "int", "label": "两次抢之间的间隔（秒）",
     "default": 3, "min": 1, "max": 600,
     "help": "太密集的点击很容易被判定为外挂，建议别低于 3 秒"},
]


def permissions(config):
    """按模式要权限 —— 只提醒时一个都不要。"""
    perms = []
    if str(config.get("mode") or "notify") == "grab":
        perms += ["desktop", "input"]
    return perms


# ----------------------------------------------------------------------
# 红包识别
# ----------------------------------------------------------------------


def _is_red_packet(session):
    """这条消息是不是红包？尽量宽地认，认得越准「漏红包」越少。

    · 微信 4.x：红包消息的 content 是一段 XML，里面有 <wcpayinfo>
    · QQ（NapCat）：红包是 json 段，里面带 redpackage
    · 兜底：文本里出现红包标记字样
    """
    text = str(getattr(session, "text", "") or "")
    low = text.lower()
    if "<wcpayinfo" in low or "<msg><appmsg" in low and "红包" in text:
        return True
    if "微信红包" in text or "[微信红包]" in text:
        return True

    raw = getattr(session, "raw", None)
    if isinstance(raw, dict):
        for seg in (raw.get("message") or []):
            if not isinstance(seg, dict):
                continue
            if str(seg.get("type")) != "json":
                continue
            payload = str((seg.get("data") or {}).get("data") or "")
            if "redpackage" in payload.lower() or "红包" in payload:
                return True

    for marker in ("[QQ红包]", "QQ红包", "收到红包", "领取红包", "发了一个红包"):
        if marker in text:
            return True
    return False


def _parse_point(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        x, _, y = text.replace("，", ",").partition(",")
        return int(x.strip()), int(y.strip())
    except ValueError:
        return None


def _whitelist(config):
    return [
        line.strip()
        for line in str(config.get("group_whitelist") or "").splitlines()
        if line.strip()
    ]


# ----------------------------------------------------------------------


async def apply(ctx, config):
    import asyncio
    import time

    mode = str(config.get("mode") or "notify")
    dry_run = bool(config.get("dry_run", True))

    async def on_message(session):
        if not _is_red_packet(session):
            return
        ctx.log.info(f"检测到红包（{session.where}，模式={mode}{'，演练' if dry_run else ''}）")

        # ---- 只提醒：不需要任何权限 ----
        if mode != "grab":
            text = str(config.get("notify_message") or "🧧 有红包！").replace(
                "{who}", session.who or "这里"
            )
            await ctx.reply(session, text)
            return

        # ---- 自动抢：先过闸门 ----
        if session.is_group:
            allowed = _whitelist(config)
            if not allowed:
                ctx.log.info("群红包：白名单是空的，按设计不抢（想抢请在配置里列出群名）")
                return
            if session.who not in allowed and session.sender not in allowed:
                ctx.log.info(f"群「{session.who}」不在白名单里，不抢")
                return

        if not _quota_ok(ctx, config):
            return

        if dry_run:
            ctx.log.info("演练模式：这里本该去点红包，已跳过（关掉 dry_run 才会真点）")
            return

        await _grab(ctx, config, session)

    @ctx.on("message")
    async def watch(session):
        # 识别/配额这类纯计算不该抛异常影响别的插件
        try:
            await on_message(session)
        except Exception as exc:  # noqa: BLE001
            ctx.log.error(f"处理红包消息出错：{exc!r}")

    @ctx.command("rp-status", help="看看红包助手现在的状态")
    async def cmd_status(session, args):
        used_hour = int(ctx.store_get(_hour_key(), 0) or 0)
        used_day = int(ctx.store_get(_day_key(), 0) or 0)
        lines = [
            f"模式：{mode}",
            f"演练：{'是（不会真点）' if dry_run else '否（会真的点鼠标）'}",
            f"本小时已抢 {used_hour}/{config.get('max_per_hour')}",
            f"今天已抢 {used_day}/{config.get('max_per_day')}",
            f"群白名单：{'、'.join(_whitelist(config)) or '（空，群里不抢）'}",
        ]
        if mode == "grab":
            lines.append("已授权权限：" + ("、".join(ctx.granted) or "（无）"))
        else:
            lines.append("当前模式不需要任何权限")
        return "\n".join(lines)

    @ctx.command("rp-test", help="模拟一条红包消息，走一遍检测流程", admin_only=True)
    async def cmd_test(session, args):
        await on_message(session)
        return "已按当前配置走了一遍流程，结果见运行日志。"

    ctx.log.info(
        f"红包助手已启用：模式={mode}，演练={'开' if dry_run else '关'}"
        + ("；⚠️ 已开启自动抢，风险自负" if mode == "grab" and not dry_run else "")
    )


# ----------------------------------------------------------------------
# 配额：防止跑飞
# ----------------------------------------------------------------------


def _hour_key():
    import time

    return "quota:hour:" + time.strftime("%Y-%m-%d %H")


def _day_key():
    import time

    return "quota:day:" + time.strftime("%Y-%m-%d")


def _quota_ok(ctx, config):
    import time

    if int(ctx.store_get(_hour_key(), 0) or 0) >= int(config.get("max_per_hour") or 5):
        ctx.log.info("已达每小时上限，本次不抢")
        return False
    if int(ctx.store_get(_day_key(), 0) or 0) >= int(config.get("max_per_day") or 30):
        ctx.log.info("已达每天上限，本次不抢")
        return False
    last = float(ctx.store_get("last_grab", 0) or 0)
    gap = max(1, int(config.get("cooldown_seconds") or 3))
    if time.time() - last < gap:
        ctx.log.info("还在两次抢之间的间隔里，本次不抢")
        return False
    return True


def _bump(ctx):
    ctx.store_set(_hour_key(), int(ctx.store_get(_hour_key(), 0) or 0) + 1)
    ctx.store_set(_day_key(), int(ctx.store_get(_day_key(), 0) or 0) + 1)
    import time

    ctx.store_set("last_grab", time.time())


# ----------------------------------------------------------------------
# 抢（模板匹配 + 兜底坐标）
# ----------------------------------------------------------------------


async def _grab(ctx, config, session):
    """尽力去点。**任何一步不确定就放弃** —— 宁可漏一个红包，
    也不要在你屏幕上乱点（可能点开别的窗口、发错消息）。"""
    import asyncio

    keyword = str(config.get("window_keyword") or "微信")
    confidence = float(config.get("match_confidence") or 0.88)

    win = await ctx.to_thread(ctx.desktop.find_window, keyword)
    if not win:
        ctx.log.warn(f"找不到标题包含「{keyword}」的窗口，放弃（把 window_keyword 改对）")
        return
    await ctx.to_thread(ctx.desktop.activate_window, win["hwnd"])
    await asyncio.sleep(0.6)

    # ---- 第一步：找红包气泡 ----
    clicked = await _click_template(ctx, config, "bubble_template",
                                    "fallback_click", confidence, "红包气泡")
    if not clicked:
        ctx.log.warn("没找到红包气泡（模板图不合适，或红包已经被刷上去了），放弃")
        return

    # ---- 第二步：等红包详情弹出来，点「開」----
    await asyncio.sleep(0.9)
    opened = await _click_template(ctx, config, "open_template",
                                   "fallback_open_click", confidence, "開按钮")
    if not opened:
        ctx.log.warn("红包面板里没找到「開」按钮，放弃（可能红包已被领完）")
        return

    _bump(ctx)
    ctx.log.info("已尝试抢一个红包（是否抢到看微信/QQ 自己）")


async def _click_template(ctx, config, tpl_key, fallback_key, confidence, label):
    from pathlib import Path

    name = str(config.get(tpl_key) or "").strip()
    template = Path(ctx.dir) / name if name else None
    if template is not None and template.is_file():
        try:
            pos = await ctx.to_thread(
                ctx.desktop.find_template, template.read_bytes(), confidence
            )
        except Exception as exc:  # noqa: BLE001
            ctx.log.warn(f"模板匹配「{label}」出错：{exc}")
            pos = None
        if pos:
            await ctx.to_thread(ctx.desktop.click, pos[0], pos[1])
            ctx.log.info(f"模板命中「{label}」，已点击 {pos}")
            return True
        ctx.log.info(f"模板没匹配到「{label}」（相似度低于 {confidence}）")
    else:
        ctx.log.info(f"没提供「{label}」的模板图（{name or '空'}），改用兜底坐标")

    point = _parse_point(config.get(fallback_key))
    if point:
        await ctx.to_thread(ctx.desktop.click, point[0], point[1])
        ctx.log.info(f"按兜底坐标点击「{label}」{point}")
        return True
    return False
