# telegram-bot-autotest

A Claude Code plugin/skill that automatically tests Telegram bots by logging in as a personal account and deeply exploring all bot features — commands, inline buttons (recursive BFS), reply keyboards — producing a complete structural blueprint in JSON.

## Features

- Deep recursive BFS exploration of inline button trees (up to depth 5, 100 buttons)
- 7-phase exploration: `/start` → `/help` → inline buttons (recursive) → reply keyboard → registered commands → discovered commands → common commands
- Full button layout preservation (rows, text with emoji, callback_data)
- Navigation path tracking (e.g., `/start > [🔥 Trending] > [💰 ZEN]`)
- Structured JSON report — detailed enough to replicate the bot 1:1
- Session persistence (login once, reuse session)
- Safety limits: 1s delay between interactions, no URL/phone/geo clicks

## Install

```
/plugin install telegram-bot-autotest@telegram-bot-autotest
```

Or from marketplace:

```
/plugin marketplace add wenyaohuicom/telegram-bot-autotest
/plugin install telegram-bot-autotest@telegram-bot-autotest
```

## Usage

After installation, simply tell Claude:

> "Test the Telegram bot @BotFather"

Claude will automatically:

1. Check environment and dependencies
2. Verify Telegram credentials (ask if missing)
3. Handle login flow (send code → verify)
4. Run the deep bot exploration
5. Generate a complete bot blueprint report

## Report Output

The JSON report includes:

- **Bot Identity** — name, username, description, registered commands
- **/start Response** — exact text, full inline button layout, reply keyboard
- **/help Response** — exact text, discovered commands
- **Button Navigation Tree** — every button clicked recursively with path, callback_data, result text, and sub-buttons
- **Reply Keyboard** — each button and its response
- **Commands** — registered, discovered from /help, and common command probing
- **Statistics** — total interactions, buttons explored, max depth, timeouts, errors

## Requirements

- Python 3.8+
- Telegram API credentials from https://my.telegram.org

## License

MIT
