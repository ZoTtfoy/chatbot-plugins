"""最小示例插件 —— 照着这个抄就行。

一个插件只需要一个 ``apply(ctx, config)`` 函数。``ctx`` 上挂着所有扩展点，
``config`` 是用户在面板里填的配置（插件声明的默认值 + 用户改过的值）。

文件顶部的常量都是可选的，但写上之后面板里会好看很多：

    NAME / VERSION / DESCRIPTION / AUTHOR    展示信息
    DEFAULT_CONFIG                           默认配置
    CONFIG_SCHEMA                            配置项说明（面板据此自动生成表单）
    SECRET_KEYS                              哪些配置是密钥（面板不回明文）

★ 插件目录里有个 ``chatbot_plugin.py``，用它 import 更顺手：
      from chatbot_plugin import STOP, PluginError
"""

NAME = "示例：打个招呼"
VERSION = "1.0.0"
DESCRIPTION = "演示插件的最小写法：加一个 /hello 指令，回复可以自己配。"
AUTHOR = "ChatBot 内置示例"

DEFAULT_CONFIG = {
    "greeting": "你好呀，我是你的机器人～",
    "admin_only": False,
}

CONFIG_SCHEMA = [
    {
        "key": "greeting",
        "type": "text",
        "label": "回复内容",
        "default": "你好呀，我是你的机器人～",
        "rows": 3,
        "help": "用户发 /hello 时回什么",
    },
    {
        "key": "admin_only",
        "type": "bool",
        "label": "仅管理员可用",
        "default": False,
        "help": "打开后只有管理员名单里的用户能用这个指令",
    },
]


async def apply(ctx, config):
    ctx.log.info("示例插件已加载")

    @ctx.command("hello", aliases=("hi", "你好"), help="打个招呼", admin_only=bool(config["admin_only"]))
    async def cmd_hello(session, args):
        """处理函数签名固定是 (session, args)。

        session 里带 channel / is_group / sender / is_admin 这些身份信息，
        返回值是字符串就自动发给用户（返回 None 则什么都不发）。
        """
        # 参数也可以用起来：/hello 后面的文字都在 args 里
        tail = f"（你说的是「{args}」）" if args else ""
        return f"{config['greeting']}{tail}"

    @ctx.on("start")
    async def on_start():
        # 插件被启用时触发。适合做「连外部服务、预热数据」这类准备。
        ctx.log.info(f"/hello 已就绪（{'仅管理员' if config['admin_only'] else '所有人可用'}）")

    @ctx.on("stop")
    async def on_stop():
        # 插件被停用时触发。这里落一下数据，下次启用还能接着用。
        ctx.store_set("last_stop_at", __import__("time").time())
