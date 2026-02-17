---
name: telegram-bot-autotest
description: >
  This skill should be used when the user asks to "test a telegram bot",
  "explore a bot's functionality", "autotest a Telegram bot",
  "check what a bot does", "clone a bot", "reverse engineer a bot",
  "find bugs in a bot", "debug a bot", "check for errors",
  "test bot for issues", "check bot health",
  "test a specific button", "what happens when I click...",
  "test the /start flow", or "check what a button shows".
  It logs into Telegram as a personal account and supports three modes:
  blueprint (full structure for cloning), debug (bug finding),
  and targeted (test a specific path like /start > [Button]).
---

# Telegram Bot Autotest Skill

You are executing the telegram-bot-autotest skill. Follow these steps precisely.

All scripts are located at: `{{SKILL_DIR}}/scripts/`
Runtime data is stored at: `~/.telegram-bot-autotest/`

## Step 1: Environment Setup

```bash
bash {{SKILL_DIR}}/scripts/setup.sh
```

Parse the JSON output. If `ok` is false, show the error to the user and stop.

## Step 2: Check Configuration

```bash
python3 {{SKILL_DIR}}/scripts/config.py --check
```

If configuration is missing (`ok` is false), ask the user for the missing values:

- **TG_API_ID**: Telegram API ID (integer, from https://my.telegram.org)
- **TG_API_HASH**: Telegram API Hash (string, from https://my.telegram.org)
- **TG_PHONE**: Phone number with country code (e.g., +1234567890)

Then save them:

```bash
python3 {{SKILL_DIR}}/scripts/config.py --set --api-id=XXXX --api-hash=XXXX --phone=+XXXX
```

## Step 3: Check Login Status

```bash
python3 {{SKILL_DIR}}/scripts/tg_login.py --check
```

If not authorized (`authorized` is false), execute the login flow:

### 3a. Send verification code

```bash
python3 {{SKILL_DIR}}/scripts/tg_login.py --login
```

Tell the user a verification code has been sent to their Telegram app, and ask them to provide it.

### 3b. Verify the code

```bash
python3 {{SKILL_DIR}}/scripts/tg_login.py --verify --code=XXXXX
```

If the response contains `needs_2fa: true`, ask the user for their 2FA password and run:

```bash
python3 {{SKILL_DIR}}/scripts/tg_login.py --verify --password=XXXXX
```

If `PhoneCodeInvalidError`, ask the user to re-enter the code.

## Step 3.5: Determine Test Mode

Before running the test, determine the mode based on the user's intent:

- **Targeted mode** — if the user asks about a specific button, a specific flow, or what happens at a particular step. Look for: a specific button name mentioned, "click", "what happens when", "what does X show", "test the X button", "after /start click Y". The user typically describes a path like "send /start then click 一键发币".
- **Debug mode** — if the user's request contains words like: "bug", "debug", "error", "issue", "problem", "test for", "check for", "health", "broken", "fix", "diagnose"
- **Blueprint mode** — if the user's request contains words like: "clone", "replicate", "copy", "1:1", "blueprint", "reverse engineer", "explore structure", "map out"
- **Default** — if ambiguous, use **blueprint** mode

Set the mode variable for Step 4:
- Targeted mode: `MODE=targeted` — also construct the `PATH` string (see Step 4)
- Debug mode: `MODE=debug`
- Blueprint mode: `MODE=blueprint`

## Step 4: Run Bot Test

Once logged in, run the bot tester. The command depends on the mode:

**Blueprint or Debug mode:**

```bash
python3 {{SKILL_DIR}}/scripts/tg_bot_tester.py @TARGET_BOT --mode=MODE --save
```

**Targeted mode:**

```bash
python3 {{SKILL_DIR}}/scripts/tg_bot_tester.py @TARGET_BOT --mode=targeted --path="/start > [Button Text] > [Next Button]" --save
```

Construct the `--path` value from the user's description:
- First element is the command to send (e.g., `/start`, `/help`, `/menu`)
- Subsequent elements are button texts wrapped in `[...]`, separated by ` > `
- Example: user says "send /start then click 一键发币" → `--path="/start > [一键发币]"`
- Example: user says "click 一键发币 then 确认" → `--path="/start > [一键发币] > [确认]"`
- Button matching is flexible: exact match first, then case-insensitive, then substring

Replace `@TARGET_BOT` with the bot username the user wants to test.
Replace `MODE` with `blueprint`, `debug`, or `targeted` based on Step 3.5.

Options:
- `--max-depth=5` — Max inline button recursion depth (default 5)
- `--max-buttons=100` — Max total buttons to click (default 100)
- `--timeout=10` — Response timeout in seconds (default 10)
- `--mode=blueprint|debug|targeted` — Test mode (default: blueprint)
- `--path="..."` — Required for targeted mode. The navigation path to test.
- `--save` — Save report to `~/.telegram-bot-autotest/reports/`

## Step 5: Generate Report

Parse the JSON output and present a report based on the mode used.

---

### Step 5A: Blueprint Report (mode=blueprint)

Present a **complete bot blueprint** to the user. The report should be detailed enough to replicate the bot.

#### Report Structure

##### 1. Bot Identity
- Bot name, username, description
- Registered commands list (from BotFather)

##### 2. /start Response Blueprint
- Exact response text (preserve emoji and formatting)
- Full inline button layout: show rows and columns with exact button text
- Reply keyboard layout if any

##### 3. /help Response Blueprint
- Exact response text
- All commands discovered from help text

##### 4. Button Navigation Tree
This is the most important section. For each entry in `button_tree`, present:
- **Path**: shows the navigation chain (e.g., `/start > [Trending] > [ZEN]`)
- **Depth**: how deep in the tree
- **Button text**: exact text with emoji
- **Callback data**: the callback_data string
- **Result**: what happened when clicked:
  - Response text (preserve emoji and formatting)
  - Any new inline buttons that appeared (full layout with rows)
  - Callback answer (toast/alert) if any
  - Whether it was a new message or edited the existing one

Present the tree in a hierarchical format so the user can see the full navigation structure.

##### 5. Reply Keyboard
- Each button text and what response it produced

##### 6. Commands
- Each registered command, its description, and its response
- Each discovered command from /help and its response
- Common commands that were recognized

##### 7. Statistics
- Total interactions, successful responses, timeouts, errors
- Buttons explored, max depth reached

#### Presentation Guidelines

- Preserve ALL emoji in button text and response text exactly as-is
- Show inline button layouts as visual grids, e.g.:
  ```
  [ Launch Token ] [ Trending ]
  [ My Wallet    ] [ Portfolio ]
  [ Leaderboard  ] [ Invite   ]
  [ How to Earn                ]
  ```
- For the button tree, use indentation to show depth
- Include callback_data values (needed for replication)
- Note which buttons produce new messages vs edit existing ones

---

### Step 5B: Debug Report (mode=debug)

Present a **bug report** focused on issues found during testing. Structure the report as follows:

#### 1. Summary
- **Health Score**: display the `health_score` value (0-100) with a visual indicator:
  - 90-100: Healthy
  - 70-89: Minor issues
  - 50-69: Needs attention
  - 0-49: Critical issues
- **Total bugs found**: count by severity (high / medium / low)

#### 2. Critical Issues (high severity)
For each high-severity bug from the `bugs` list:
- Type and location
- Detailed description
- Relevant details (button data, error messages, etc.)

#### 3. Warnings (medium severity)
For each medium-severity bug:
- Type and location
- Description and details

#### 4. Info (low severity)
For each low-severity bug:
- Type and location
- Description

#### 5. Test Coverage
Summarize what was tested:
- Commands tested (list them)
- Buttons explored (count and max depth)
- Unexpected inputs tested (if debug mode ran Phase 8)
- Button repeat tests (if debug mode ran Phase 9)

#### 6. Statistics
- Total interactions, successful responses, timeouts, errors
- Buttons explored, max depth reached

#### Presentation Guidelines

- Group bugs by severity, with high severity first
- Use clear labels for bug types:
  - `no_start_response` → "/start has no response"
  - `dead_button` → "Dead button (no response)"
  - `broken_button` → "Broken button (error)"
  - `command_timeout` → "Command timeout"
  - `empty_response` → "Empty response"
  - `error_in_response` → "Error in response text"
  - `no_help` → "No /help response"
  - `no_fallback` → "No fallback handler"
  - `inconsistent_button` → "Inconsistent button behavior"
  - `flood_triggered` → "Rate limit hit"
- If no bugs are found, congratulate the user — the bot is healthy

---

### Step 5C: Targeted Report (mode=targeted)

Present the **step-by-step result** of the specific path the user requested. This should be concise and direct — the user wants to know exactly what happens at each step.

#### Report Structure

For each entry in the `steps` list:

**Step 1 — Command sent** (e.g., "/start"):
- Show the response text (preserve emoji and formatting)
- Show the inline button layout as a visual grid
- Note which buttons are available to click next

**Step 2+ — Button clicked** (e.g., "[一键发币]"):
- Show matched button text and callback_data
- Show the callback answer (toast/alert) if any
- Show the new message or edited message:
  - Full response text (preserve emoji and formatting)
  - Any new inline buttons that appeared (visual grid)
  - Whether it was a new message or edited the existing one
- If more buttons are available, list them

**If a button was not found:**
- Show the error clearly
- List all available buttons so the user can correct the path

#### Presentation Guidelines

- Be concise — the user asked about a specific flow, give them exactly that
- Preserve ALL emoji in text and buttons
- Show button layouts as visual grids
- If the path completed successfully, summarize what the final screen shows
- If the path broke at some step, explain where and why, and show available options

## Error Handling

- If any script returns exit code 2, an unexpected error occurred. Show the error JSON to the user.
- If the bot test encounters a `FloodWaitError`, inform the user they need to wait before retrying.
- If a specific command times out, note it in the report but continue testing.

## Important Notes

- Never share or display the user's API credentials in the output.
- The test does not share phone, location, or click URL buttons (URL buttons are recorded but not followed).
- BFS exploration with visited tracking prevents infinite loops.
- There is a 1-second delay between interactions to avoid rate limiting.
