# telegram-bot-autotest-skill

[English](README_en.md) | 中文

一个 Claude Code 插件/技能，以 Telegram 个人账号登录，自动化深度测试指定的 Telegram Bot。支持三种测试模式：全量结构蓝图（用于 1:1 复刻）、自动化 Bug 检测、以及定向路径测试。

## 三种测试模式

### Blueprint 模式（蓝图）
递归探索 Bot 全部功能结构（命令、Inline 按钮树、Reply 键盘），生成可用于 1:1 复刻的完整结构化 JSON 报告。

> "测试一下 @BotFather 这个 Bot"
> "克隆/复刻这个 Bot 的结构"

### Debug 模式（调试）
在全量探索的基础上，额外执行异常输入测试和按钮幂等性测试，自动检测 10 种 Bug 类型并生成健康评分。

> "帮我找一下 @MyBot 的 Bug"
> "检查这个 Bot 有没有问题"

### Targeted 模式（定向）
只测试指定路径，快速查看某个按钮点击后显示什么。

> "测试 @MyBot 发送 /start 后显示什么"
> "点击 /start 后再点一键发币，看看显示什么"

## 功能特性

- 深度递归 BFS 探索 Inline 按钮树（最大深度 5 层，最多 100 个按钮）
- 7 阶段探索流程：`/start` → `/help` → Inline 按钮递归点击 → Reply 键盘 → 注册命令 → 从 /help 发现的命令 → 常见命令探测
- Debug 模式额外 2 阶段：异常输入测试 → 按钮重复点击测试
- 10 种 Bug 自动检测（无响应、死按钮、错误响应、缺少 fallback 等）
- 健康评分（0-100）
- 定向路径测试，支持模糊按钮匹配（精确 → 忽略大小写 → 子串）
- 完整保留按钮布局（行列关系、文本含 emoji、callback_data）
- 导航路径追踪（如 `/start > [🔥 Trending] > [💰 ZEN]`）
- 结构化 JSON 报告输出
- Session 持久化（登录一次，后续复用）
- 安全限制：交互间隔 1 秒、不点击 URL/电话/位置类按钮

## 安装

```
/plugin install telegram-bot-autotest@telegram-bot-autotest
```

或从 marketplace 安装：

```
/plugin marketplace add wenyaohuicom/telegram-bot-autotest-skill
/plugin install telegram-bot-autotest@telegram-bot-autotest
```

## 使用方法

安装后，直接对 Claude 说：

> "测试一下 @BotFather 这个 Bot" — 全量蓝图模式
> "帮我找一下 @MyBot 的 Bug" — 自动 Bug 检测
> "测试 @MyBot 发送 /start 后点击一键发币显示什么" — 定向测试

Claude 会自动识别意图、选择模式，并执行：

1. 检查环境与依赖
2. 检查 Telegram API 凭证（缺少则向你询问）
3. 处理登录流程（发送验证码 → 输入验证码）
4. 根据意图选择模式（blueprint / debug / targeted）
5. 运行测试并生成对应报告

## 报告内容

### Blueprint 报告

- **Bot 身份** — 名称、用户名、描述、注册命令列表
- **/start 响应** — 完整文本、Inline 按钮布局、Reply 键盘
- **/help 响应** — 完整文本、从中发现的命令
- **按钮导航树** — 每个按钮递归点击的路径、callback_data、返回文本、子按钮
- **Reply 键盘** — 每个按钮及其响应
- **命令** — 注册命令、/help 中发现的命令、常见命令探测结果
- **统计** — 总交互数、按钮探索数、最大深度、超时数、错误数

### Debug 报告

- **健康评分** — 0-100 分
- **Bug 列表** — 按严重程度分级（high / medium / low）
- **测试覆盖** — 命令、按钮、异常输入、幂等性测试
- **统计** — 同上

### Targeted 报告

- **逐步结果** — 每一步的响应文本、按钮布局、可用按钮列表
- 简洁直接，只展示用户关心的路径

## 环境要求

- Python 3.8+
- Telegram API 凭证（从 https://my.telegram.org 获取）

## 许可证

MIT
