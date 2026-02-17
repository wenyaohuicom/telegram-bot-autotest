# telegram-bot-autotest

A Claude Code plugin/skill that automatically tests Telegram bots by logging in as a personal account. Supports three test modes: full structure blueprint (for 1:1 cloning), automated bug detection, and targeted path testing.

## Three Test Modes

### Blueprint Mode
Deeply explores all bot features — commands, inline buttons (recursive BFS), reply keyboards — producing a complete structural blueprint in JSON for 1:1 replication.

> "Test the Telegram bot @BotFather"
> "Clone/replicate this bot's structure"

### Debug Mode
Runs full exploration plus additional input handling tests and button idempotency checks. Automatically detects 10 bug types and generates a health score (0-100).

> "Find bugs in @MyBot"
> "Check this bot for errors"

### Targeted Mode
Tests only a specific navigation path — quickly see what a particular button shows.

> "Test @MyBot, what does /start show?"
> "After /start, click 'Launch Token' — what happens?"

## Features

- Deep recursive BFS exploration of inline button trees (up to depth 5, 100 buttons)
- 7-phase exploration: `/start` → `/help` → inline buttons (recursive) → reply keyboard → registered commands → discovered commands → common commands
- Debug mode adds 2 phases: unexpected input testing → button repeat testing
- 10 automatic bug detections (no response, dead buttons, error responses, missing fallback, etc.)
- Health score (0-100)
- Targeted path testing with flexible button matching (exact → case-insensitive → substring)
- Full button layout preservation (rows, text with emoji, callback_data)
- Navigation path tracking (e.g., `/start > [🔥 Trending] > [💰 ZEN]`)
- Structured JSON report output
- Session persistence (login once, reuse session)
- Safety limits: 1s delay between interactions, no URL/phone/geo clicks

## Install

```
/plugin install telegram-bot-autotest@telegram-bot-autotest
```

Or from marketplace:

```
/plugin marketplace add wenyaohuicom/telegram-bot-autotest-skill
/plugin install telegram-bot-autotest@telegram-bot-autotest
```

## Usage

After installation, simply tell Claude:

> "Test the Telegram bot @BotFather" — full blueprint mode
> "Find bugs in @MyBot" — automated bug detection
> "Test @MyBot, what does /start show after clicking Launch Token?" — targeted test

Claude will automatically detect intent, select the mode, and:

1. Check environment and dependencies
2. Verify Telegram credentials (ask if missing)
3. Handle login flow (send code → verify)
4. Select mode based on intent (blueprint / debug / targeted)
5. Run the test and generate the corresponding report

## Report Output

### Blueprint Report

- **Bot Identity** — name, username, description, registered commands
- **/start Response** — exact text, full inline button layout, reply keyboard
- **/help Response** — exact text, discovered commands
- **Button Navigation Tree** — every button clicked recursively with path, callback_data, result text, and sub-buttons
- **Reply Keyboard** — each button and its response
- **Commands** — registered, discovered from /help, and common command probing
- **Statistics** — total interactions, buttons explored, max depth, timeouts, errors

### Debug Report

- **Health Score** — 0-100
- **Bug List** — grouped by severity (high / medium / low)
- **Test Coverage** — commands, buttons, unexpected inputs, idempotency tests
- **Statistics** — same as above

### Targeted Report

- **Step-by-step results** — response text, button layout, available buttons at each step
- Concise and direct — only shows the path the user asked about

## Requirements

- Python 3.8+
- Telegram API credentials from https://my.telegram.org

## License

MIT
