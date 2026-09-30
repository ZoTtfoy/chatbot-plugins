# ChatBot 插件库

给 [ChatBot](https://github.com/) 用的插件仓库。里面的插件可以直接被机器人下载安装。

## 怎么用

**方式一：在机器人面板里装（推荐）**

1. 打开面板 →「插件」页 →「从插件市场安装」
2. 填入本仓库 `index.json` 的地址：

   ```
   https://cdn.jsdelivr.net/gh/ZoTtfoy/chatbot-plugins@main/index.json
   ```

   > ⚠️ **别用 `raw.githubusercontent.com`** —— 实测在国内网络下直接连接失败
   > （HTTP 000 连不上），jsDelivr 是能通的。想换回 raw 地址的话，先自己 curl 一下确认能通。
   >
   > 用 jsDelivr 还有个好处：它会把文件缓存到 CDN，国内访问快很多；
   > 但代价是**更新有延迟**（通常几分钟，最长约 12 小时）。
   > 你刚改完插件想立刻生效，就在地址后面加个 `?t=<时间戳>` 绕过缓存。

3. 列表里点「安装」即可。装进来的插件**默认是停用状态**，确认没问题再打开开关。

**方式二：手动**

把 `plugins/<插件名>/` 整个目录复制到机器人的 `数据目录/plugins/` 下。

## 目录结构

```
index.json                     插件清单（机器人读这个；由脚本生成，别手改）
plugins/
  hello/plugin.py              一个插件一个目录，入口固定叫 plugin.py
  keyword_reply/plugin.py
  ...
tools/build_index.py           扫描 plugins/ 重新生成 index.json
```

## 索引为什么要自动生成

`index.json` 里的名称、版本、说明、权限**全部从插件源码里解析出来**，不要手写 ——
手写迟早会和代码不一致，用户看到的就是错的版本号和错的权限清单。

改了插件之后跑一次：

```bash
python tools/build_index.py
```

`tools/build_index.py` 用的是 **ast 解析**而不是 `import`：
生成索引时**绝不执行插件代码**。否则任何人提一个 PR，维护者机器上跑一次脚本
就等于执行了陌生人的代码 —— 这是这类仓库最容易被忽略的供应链漏洞。

如果你在 GitHub 上，`.github/workflows/rebuild-index.yml` 会在每次改动
`plugins/` 时自动重跑这个脚本并提交索引，你不用手动管。

## 贡献插件

1. 在 `plugins/` 下新建一个目录，名字就是插件 id（只能有字母数字 `-` `_`）
2. 写 `plugin.py`，至少要有 `apply(ctx, config)`
3. 建议在文件顶部把这几个常量写全（仓库索引要用）：

```python
NAME = "插件名"
VERSION = "1.0.0"
DESCRIPTION = "一句话说明它干什么"
AUTHOR = "你的名字"
PERMISSIONS = ["net", "send_message"]      # 用到什么能力就声明什么，别多也别少
DEFAULT_CONFIG = {...}                     # 可选，默认配置
CONFIG_SCHEMA = [...]                      # 可选，配置项说明（面板据此生成表单）
```

4. 跑一次 `python tools/build_index.py`，确认索引正常
5. 提 PR

### 写插件前请读这一段

插件是**普通 Python 代码**，用户装上就以他的身份运行。所以：

- **只声明真正需要的能力**。申请了不该有的权限，用户看到清单就会拒绝安装，
  而且这是最容易被 review 打回的地方。
- **权限名只有这六个**：`send_message` / `net` / `filesystem` / `desktop` /
  `input` / `shell`。用到 `ctx.net` 之类却不声明，运行时会被门禁拦下并记一条审计。
- **别绕过 ctx 直接 `import os` / `subprocess`**。技术上做得到，
  但那是把「能审计」变成「不能审计」，用户一旦发现就不会再信任这个仓库。
- **阻塞操作要丢线程池**：`await ctx.to_thread(ctx.desktop.screenshot)`。
  同步卡住会连累 QQ 和微信两条消息通道一起卡住。
- **配置写错不能让插件崩**。用户手写的配置一定有格式问题，
  解析不了就跳过那一行并记日志，剩下的照常工作 —— 参考 `keyword_reply` 的做法。

完整的扩展点、权限说明和踩坑清单，见机器人面板「插件」页底部的《怎么写插件》。

## 免责声明

插件按「原样」提供。安装前请自己看一眼 `plugin.py` —— 都只有几十到一两百行，
读完比读任何免责声明都管用。
