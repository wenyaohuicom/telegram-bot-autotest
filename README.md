# telegram-bot-autotest

[English](README_en.md) | 中文

一个 Claude Code 插件/技能，以 Telegram 个人账号登录，自动化深度测试指定的 Telegram Bot，递归探索其全部功能结构（命令、Inline 按钮树、Reply 键盘），生成可用于 1:1 复刻的完整结构化 JSON 报告。

## 功能特性

- 深度递归 BFS 探索 Inline 按钮树（最大深度 5 层，最多 100 个按钮）
- 7 阶段探索流程：`/start` → `/help` → Inline 按钮递归点击 → Reply 键盘 → 注册命令 → 从 /help 发现的命令 → 常见命令探测
- 完整保留按钮布局（行列关系、文本含 emoji、callback_data）
- 导航路径追踪（如 `/start > [🔥 Trending] > [💰 ZEN]`）
- 结构化 JSON 报告输出 — 详细到足以 1:1 复刻整个 Bot
- Session 持久化（登录一次，后续复用）
- 安全限制：交互间隔 1 秒、不点击 URL/电话/位置类按钮

## 安装

```
/plugin install telegram-bot-autotest@telegram-bot-autotest
```

或从 marketplace 安装：

```
/plugin marketplace add wenyaohuicom/telegram-bot-autotest
/plugin install telegram-bot-autotest@telegram-bot-autotest
```

## 使用方法

安装后，直接对 Claude 说：

> "测试一下 @BotFather 这个 Bot"

Claude 会自动执行：

1. 检查环境与依赖
2. 检查 Telegram API 凭证（缺少则向你询问）
3. 处理登录流程（发送验证码 → 输入验证码）
4. 运行 Bot 深度递归探索
5. 生成完整的 Bot 结构蓝图报告

## 报告内容

JSON 报告包含：

- **Bot 身份** — 名称、用户名、描述、注册命令列表
- **/start 响应** — 完整文本、Inline 按钮布局、Reply 键盘
- **/help 响应** — 完整文本、从中发现的命令
- **按钮导航树** — 每个按钮递归点击的路径、callback_data、返回文本、子按钮
- **Reply 键盘** — 每个按钮及其响应
- **命令** — 注册命令、/help 中发现的命令、常见命令探测结果
- **统计** — 总交互数、按钮探索数、最大深度、超时数、错误数

## 环境要求

- Python 3.8+
- Telegram API 凭证（从 https://my.telegram.org 获取）

## 许可证

MIT
