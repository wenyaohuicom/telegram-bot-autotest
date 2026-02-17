#!/usr/bin/env python3
"""Core Bot Auto-Exploration Engine — Deep recursive exploration.

Usage: python3 tg_bot_tester.py @BotUsername [--timeout=10] [--max-depth=5] [--max-buttons=100] [--mode=blueprint|debug|targeted]
       python3 tg_bot_tester.py @BotUsername --mode=targeted --path="/start > [Button Text] > [Next Button]"

Explores the COMPLETE bot structure:
  1. Bot info (description, registered commands)
  2. /start — capture response + full button layout
  3. /help — capture response
  4. Recursive inline button exploration (BFS, tracks visited to avoid loops)
  5. Reply keyboard button exploration
  6. All registered commands
  7. All commands discovered from /help text
  8. Common command probing

Debug mode adds:
  8. Input handling test — unexpected inputs to detect missing fallback handlers
  9. Button repeat test — re-click buttons to detect inconsistencies

Targeted mode:
  Only executes a specific path, e.g. /start > [Button A] > [Button B]
  Returns the result of each step along the path.

For each interaction, records:
  - Exact button layout (rows, text with emoji, button type)
  - Click result (callback answer, new/edited message, new buttons)
  - Recursively explores any NEW buttons discovered

Output: Complete bot structure blueprint as JSON.
         In debug mode, also includes bugs list and health_score.
"""

import argparse
import asyncio
import json
import os
import random
import re
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


def load_config():
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None, "python-dotenv not installed"

    env_file = Path.home() / ".telegram-bot-autotest" / ".env"
    if not env_file.exists():
        return None, "Config file not found."

    values = dotenv_values(env_file)
    api_id = values.get("TG_API_ID")
    api_hash = values.get("TG_API_HASH")

    if not all([api_id, api_hash]):
        return None, "Missing TG_API_ID or TG_API_HASH"

    session_path = values.get("TG_SESSION_PATH")
    if not session_path:
        session_path = str(Path.home() / ".telegram-bot-autotest" / "sessions" / "tg_user")

    return {
        "api_id": int(api_id),
        "api_hash": api_hash,
        "session_path": session_path,
    }, None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTERACTION_DELAY = 1.0
UNKNOWN_PATTERNS = [
    "unknown command", "i don't understand", "i don't know that command",
    "unrecognized command", "invalid command", "command not found",
    "не понимаю", "неизвестная команда",
]
COMMON_COMMANDS = [
    "/settings", "/menu", "/info", "/about", "/status",
    "/profile", "/language", "/lang", "/cancel",
]

ERROR_PATTERNS = [
    "traceback", "error", "exception", "internal server error",
    "something went wrong", "unexpected error", "failed",
    "ошибка", "что-то пошло не так",
]

DEBUG_INPUTS = [
    {"label": "random_text", "value": "hello"},
    {"label": "random_text", "value": "asdfgh"},
    {"label": "numbers_only", "value": "12345"},
    {"label": "special_chars", "value": "!@#$%"},
    {"label": "long_text", "value": "A" * 500},
    {"label": "emoji_only", "value": "\U0001f600\U0001f389\U0001f525"},
    {"label": "empty_like", "value": " "},
    {"label": "empty_like", "value": "."},
]


def is_unknown_response(text):
    if not text:
        return False
    t = text.lower()
    return any(p in t for p in UNKNOWN_PATTERNS)


# ---------------------------------------------------------------------------
# Message & button serialization
# ---------------------------------------------------------------------------

def extract_button_layout(reply_markup):
    """Extract the FULL button layout from a reply markup, preserving rows and types."""
    from telethon.tl.types import (
        ReplyInlineMarkup, ReplyKeyboardMarkup,
        KeyboardButtonUrl, KeyboardButtonRequestPhone,
        KeyboardButtonRequestGeoLocation, KeyboardButtonCallback,
        KeyboardButtonSwitchInline,
    )

    if not reply_markup:
        return None, None

    inline_layout = None
    keyboard_layout = None

    if isinstance(reply_markup, ReplyInlineMarkup):
        inline_layout = []
        for row in reply_markup.rows:
            row_btns = []
            for btn in row.buttons:
                b = {"text": btn.text}
                if isinstance(btn, KeyboardButtonCallback):
                    b["type"] = "callback"
                    b["data"] = btn.data.decode("utf-8", errors="replace") if btn.data else ""
                elif isinstance(btn, KeyboardButtonUrl):
                    b["type"] = "url"
                    b["url"] = btn.url
                elif isinstance(btn, KeyboardButtonSwitchInline):
                    b["type"] = "switch_inline"
                    b["query"] = btn.query
                elif isinstance(btn, KeyboardButtonRequestPhone):
                    b["type"] = "share_phone"
                elif isinstance(btn, KeyboardButtonRequestGeoLocation):
                    b["type"] = "share_geo"
                else:
                    b["type"] = type(btn).__name__
                row_btns.append(b)
            inline_layout.append(row_btns)

    if isinstance(reply_markup, ReplyKeyboardMarkup):
        keyboard_layout = []
        for row in reply_markup.rows:
            row_btns = []
            for btn in row.buttons:
                b = {"text": btn.text}
                if isinstance(btn, KeyboardButtonRequestPhone):
                    b["type"] = "share_phone"
                elif isinstance(btn, KeyboardButtonRequestGeoLocation):
                    b["type"] = "share_geo"
                else:
                    b["type"] = "text"
                row_btns.append(b)
            keyboard_layout.append(row_btns)

    return inline_layout, keyboard_layout


def serialize_message(msg):
    """Convert a Telethon message to a full blueprint dict."""
    data = {
        "id": msg.id,
        "text": msg.text or "",
        "date": msg.date.isoformat() if msg.date else None,
    }

    inline_layout, keyboard_layout = extract_button_layout(msg.reply_markup)
    if inline_layout is not None:
        data["inline_buttons"] = inline_layout
    if keyboard_layout is not None:
        data["reply_keyboard"] = keyboard_layout

    if msg.media:
        data["has_media"] = True
        data["media_type"] = type(msg.media).__name__
    else:
        data["has_media"] = False

    return data


# ---------------------------------------------------------------------------
# Interaction helpers
# ---------------------------------------------------------------------------

async def send_and_capture(client, bot_entity, text, timeout=10):
    """Send a text message and capture all bot responses."""
    from telethon.errors import TimeoutError as TelethonTimeout

    record = {
        "action": "send_message",
        "sent": text,
        "responses": [],
        "error": None,
        "timed_out": False,
    }

    try:
        try:
            async with client.conversation(bot_entity, timeout=timeout) as conv:
                await conv.send_message(text)
                await asyncio.sleep(0.5)
                try:
                    while True:
                        resp = await asyncio.wait_for(conv.get_response(), timeout=3)
                        record["responses"].append(serialize_message(resp))
                except (asyncio.TimeoutError, TelethonTimeout):
                    pass
        except Exception:
            await client.send_message(bot_entity, text)
            await asyncio.sleep(min(timeout, 5))
            messages = []
            async for msg in client.iter_messages(bot_entity, limit=5):
                if msg.out:
                    break
                messages.append(msg)
            messages.reverse()
            record["responses"] = [serialize_message(m) for m in messages]
    except asyncio.TimeoutError:
        record["timed_out"] = True
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"

    if not record["responses"] and not record["error"]:
        record["timed_out"] = True

    return record


async def click_button(client, msg_id, bot_entity, button_data_raw):
    """Click an inline callback button, return full result with any new buttons."""
    from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
    from telethon.errors import (
        MessageIdInvalidError, BotResponseTimeoutError,
        DataInvalidError,
    )

    record = {
        "callback_answer": None,
        "new_message": None,
        "edited_message": None,
        "error": None,
    }

    try:
        pre_msgs = []
        async for m in client.iter_messages(bot_entity, limit=3):
            pre_msgs.append(m.id)

        data_bytes = button_data_raw.encode("utf-8") if isinstance(button_data_raw, str) else button_data_raw

        try:
            result = await client(GetBotCallbackAnswerRequest(
                peer=bot_entity,
                msg_id=msg_id,
                data=data_bytes,
            ))
            if result.alert:
                record["callback_answer"] = f"[ALERT] {result.message}"
            elif result.message:
                record["callback_answer"] = result.message
            if result.url:
                record["callback_answer"] = f"[URL] {result.url}"
        except BotResponseTimeoutError:
            record["callback_answer"] = None

        await asyncio.sleep(2)

        # Check for new or edited messages
        async for m in client.iter_messages(bot_entity, limit=5):
            if m.out:
                break
            if m.id not in pre_msgs:
                record["new_message"] = serialize_message(m)
                break

        # Also check if the original message was edited
        try:
            edited_msg = await client.get_messages(bot_entity, ids=msg_id)
            if edited_msg and edited_msg.edit_date:
                record["edited_message"] = serialize_message(edited_msg)
        except Exception:
            pass

    except MessageIdInvalidError:
        record["error"] = "MessageIdInvalidError"
    except DataInvalidError:
        record["error"] = "DataInvalidError"
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"

    return record


def extract_commands_from_help(text):
    """Parse /help response text to discover commands."""
    if not text:
        return []
    # Match patterns like /command or /command — description
    matches = re.findall(r'(/[a-zA-Z_][a-zA-Z0-9_]*)', text)
    return list(dict.fromkeys(matches))  # dedupe, preserve order


def collect_callback_buttons(data):
    """Extract all callback buttons from a serialized message or response list."""
    buttons = []
    if isinstance(data, dict):
        for row in data.get("inline_buttons", []):
            for btn in row:
                if btn.get("type") == "callback" and btn.get("data"):
                    buttons.append((btn["text"], btn["data"]))
    return buttons


# ---------------------------------------------------------------------------
# Bug analysis (debug mode)
# ---------------------------------------------------------------------------

def _response_has_error_text(text):
    """Check if response text contains error-like patterns."""
    if not text:
        return False
    t = text.lower()
    return any(p in t for p in ERROR_PATTERNS)


def analyze_bugs(report):
    """Scan complete report and generate a list of detected bugs with severity."""
    bugs = []
    structure = report.get("structure", {})

    # --- /start checks ---
    start = structure.get("start", {})
    if start.get("timed_out") or not start.get("responses"):
        bugs.append({
            "severity": "high",
            "type": "no_start_response",
            "location": "/start",
            "description": "/start command produced no response or timed out",
            "details": {"timed_out": start.get("timed_out", False), "error": start.get("error")},
        })
    elif start.get("responses"):
        for resp in start["responses"]:
            text = resp.get("text", "")
            if not text and not resp.get("has_media"):
                bugs.append({
                    "severity": "medium",
                    "type": "empty_response",
                    "location": "/start",
                    "description": "/start returned an empty response (no text, no media)",
                    "details": {"message_id": resp.get("id")},
                })
            if _response_has_error_text(text):
                bugs.append({
                    "severity": "medium",
                    "type": "error_in_response",
                    "location": "/start",
                    "description": "Response text contains error-like patterns",
                    "details": {"text_snippet": text[:200]},
                })

    # --- /help checks ---
    help_rec = structure.get("help", {})
    if help_rec.get("timed_out") or not help_rec.get("responses"):
        bugs.append({
            "severity": "low",
            "type": "no_help",
            "location": "/help",
            "description": "/help command produced no response or timed out",
            "details": {"timed_out": help_rec.get("timed_out", False), "error": help_rec.get("error")},
        })

    # --- Button tree checks ---
    for node in structure.get("button_tree", []):
        error = node.get("error")
        path = node.get("path", "unknown")

        if error:
            if "DataInvalidError" in error:
                bugs.append({
                    "severity": "high",
                    "type": "broken_button",
                    "location": path,
                    "description": f"Button click raised DataInvalidError",
                    "details": {"button_text": node.get("button_text"), "button_data": node.get("button_data"), "error": error},
                })
            elif "MessageIdInvalidError" in error:
                bugs.append({
                    "severity": "high",
                    "type": "broken_button",
                    "location": path,
                    "description": f"Button click raised MessageIdInvalidError",
                    "details": {"button_text": node.get("button_text"), "button_data": node.get("button_data"), "error": error},
                })
            elif "FloodWaitError" in error:
                bugs.append({
                    "severity": "low",
                    "type": "flood_triggered",
                    "location": path,
                    "description": "FloodWaitError encountered during button exploration",
                    "details": {"error": error},
                })
            continue

        # Dead button: no callback answer, no new message, no edited message, no error
        has_callback = node.get("callback_answer") is not None
        has_new_msg = node.get("result_message") is not None
        has_edited_msg = node.get("result_edited") is not None
        if not has_callback and not has_new_msg and not has_edited_msg:
            bugs.append({
                "severity": "high",
                "type": "dead_button",
                "location": path,
                "description": "Button click produced no response at all (no callback, no message, no edit)",
                "details": {"button_text": node.get("button_text"), "button_data": node.get("button_data")},
            })

        # Check response text for errors
        for key in ("result_message", "result_edited"):
            msg = node.get(key)
            if msg:
                text = msg.get("text", "")
                if not text and not msg.get("has_media"):
                    bugs.append({
                        "severity": "medium",
                        "type": "empty_response",
                        "location": path,
                        "description": f"Button click returned empty response ({key})",
                        "details": {"button_text": node.get("button_text"), "message_id": msg.get("id")},
                    })
                if _response_has_error_text(text):
                    bugs.append({
                        "severity": "medium",
                        "type": "error_in_response",
                        "location": path,
                        "description": f"Response contains error-like patterns ({key})",
                        "details": {"button_text": node.get("button_text"), "text_snippet": text[:200]},
                    })

    # --- Registered commands checks ---
    for rec in structure.get("registered_commands", []):
        cmd = rec.get("sent", "unknown")
        if rec.get("timed_out") or not rec.get("responses"):
            bugs.append({
                "severity": "medium",
                "type": "command_timeout",
                "location": cmd,
                "description": f"Registered command {cmd} timed out or had no response",
                "details": {"timed_out": rec.get("timed_out", False), "error": rec.get("error")},
            })
        elif rec.get("responses"):
            for resp in rec["responses"]:
                text = resp.get("text", "")
                if not text and not resp.get("has_media"):
                    bugs.append({
                        "severity": "medium",
                        "type": "empty_response",
                        "location": cmd,
                        "description": f"Command {cmd} returned an empty response",
                        "details": {"message_id": resp.get("id")},
                    })
                if _response_has_error_text(text):
                    bugs.append({
                        "severity": "medium",
                        "type": "error_in_response",
                        "location": cmd,
                        "description": f"Command {cmd} response contains error-like patterns",
                        "details": {"text_snippet": text[:200]},
                    })

    # --- Input handling checks (debug-only phase results) ---
    input_results = structure.get("input_handling", [])
    responded_count = 0
    for rec in input_results:
        if rec.get("responses"):
            responded_count += 1
    if input_results and responded_count == 0:
        bugs.append({
            "severity": "low",
            "type": "no_fallback",
            "location": "unexpected_input",
            "description": "Bot ignores all unexpected text input (no fallback handler detected)",
            "details": {"inputs_tested": len(input_results), "responses_received": 0},
        })

    # --- Button repeat checks (debug-only phase results) ---
    for rec in structure.get("button_repeat_test", []):
        if rec.get("inconsistent"):
            bugs.append({
                "severity": "medium",
                "type": "inconsistent_button",
                "location": rec.get("path", "unknown"),
                "description": "Button produced different result on repeat click",
                "details": {
                    "button_text": rec.get("button_text"),
                    "button_data": rec.get("button_data"),
                    "difference": rec.get("difference"),
                },
            })

    return bugs


def compute_health_score(bugs):
    """Compute a health score (0-100) based on weighted bug severity."""
    if not bugs:
        return 100

    weights = {"high": 15, "medium": 5, "low": 2}
    total_penalty = sum(weights.get(b["severity"], 1) for b in bugs)
    score = max(0, 100 - total_penalty)
    return score


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

async def run_test(bot_username, timeout=10, max_depth=5, max_buttons=100, mode="blueprint"):
    from telethon import TelegramClient
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.errors import FloodWaitError

    config, error = load_config()
    if error:
        return {"ok": False, "error": error}

    client = TelegramClient(config["session_path"], config["api_id"], config["api_hash"])
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        return {"ok": False, "error": "Not authorized. Run tg_login.py --login first."}

    stats = {
        "total_interactions": 0,
        "successful_responses": 0,
        "timeouts": 0,
        "errors": 0,
        "buttons_explored": 0,
        "max_depth_reached": 0,
        "commands_tested": 0,
    }

    report = {
        "ok": True,
        "mode": mode,
        "bot_username": bot_username,
        "test_started": datetime.now(timezone.utc).isoformat(),
        "bot_info": {},
        "structure": {},
        "statistics": stats,
    }

    try:
        # Resolve bot
        try:
            bot_entity = await client.get_entity(bot_username)
        except Exception as e:
            await client.disconnect()
            return {"ok": False, "error": f"Cannot find bot '{bot_username}': {e}"}

        # --- Bot info ---
        try:
            full_user = await client(GetFullUserRequest(bot_entity))
            bot_info = {
                "id": bot_entity.id,
                "first_name": getattr(bot_entity, "first_name", ""),
                "username": getattr(bot_entity, "username", ""),
                "is_bot": getattr(bot_entity, "bot", False),
                "description": getattr(full_user.full_user, "about", "") or "",
            }
            if hasattr(full_user.full_user, "bot_info") and full_user.full_user.bot_info:
                bi = full_user.full_user.bot_info
                bot_info["description"] = getattr(bi, "description", "") or bot_info["description"]
                if hasattr(bi, "commands") and bi.commands:
                    bot_info["registered_commands"] = [
                        {"command": f"/{c.command}", "description": c.description}
                        for c in bi.commands
                    ]
                else:
                    bot_info["registered_commands"] = []
            else:
                bot_info["registered_commands"] = []
            report["bot_info"] = bot_info
        except Exception as e:
            report["bot_info"] = {"error": str(e)}

        # =====================================================================
        # Phase 1: /start
        # =====================================================================
        await asyncio.sleep(INTERACTION_DELAY)
        start_rec = await send_and_capture(client, bot_entity, "/start", timeout)
        stats["total_interactions"] += 1
        stats["commands_tested"] += 1
        if start_rec["responses"]:
            stats["successful_responses"] += 1
        elif start_rec["timed_out"]:
            stats["timeouts"] += 1
        report["structure"]["start"] = start_rec

        # =====================================================================
        # Phase 2: /help
        # =====================================================================
        await asyncio.sleep(INTERACTION_DELAY)
        help_rec = await send_and_capture(client, bot_entity, "/help", timeout)
        stats["total_interactions"] += 1
        stats["commands_tested"] += 1
        if help_rec["responses"]:
            stats["successful_responses"] += 1
        elif help_rec["timed_out"]:
            stats["timeouts"] += 1
        report["structure"]["help"] = help_rec

        # =====================================================================
        # Phase 3: BFS recursive inline button exploration
        # =====================================================================
        # Queue items: (msg_id, button_text, button_data, depth, parent_path)
        button_queue = deque()
        visited_data = set()  # track callback data to avoid loops
        button_tree = []      # flat list with path info for tree reconstruction

        def enqueue_buttons_from(source, depth, parent_path):
            """Add all callback buttons from a response to the BFS queue."""
            if isinstance(source, dict):
                items = [source]
            elif isinstance(source, list):
                items = source
            else:
                return

            for resp in items:
                msg_id = resp.get("id")
                if not msg_id:
                    continue
                for row in resp.get("inline_buttons", []):
                    for btn in row:
                        if btn.get("type") == "callback" and btn.get("data"):
                            data_key = btn["data"]
                            if data_key not in visited_data:
                                visited_data.add(data_key)
                                button_queue.append((
                                    msg_id,
                                    btn["text"],
                                    btn["data"],
                                    depth,
                                    parent_path,
                                ))

        # Seed from /start responses
        for resp in start_rec.get("responses", []):
            enqueue_buttons_from(resp, 1, "/start")

        # Seed from /help responses
        for resp in help_rec.get("responses", []):
            enqueue_buttons_from(resp, 1, "/help")

        total_clicked = 0

        while button_queue and total_clicked < max_buttons:
            msg_id, btn_text, btn_data, depth, parent_path = button_queue.popleft()

            if depth > max_depth:
                continue

            await asyncio.sleep(INTERACTION_DELAY)
            stats["total_interactions"] += 1
            stats["buttons_explored"] += 1
            total_clicked += 1

            current_path = f"{parent_path} > [{btn_text}]"

            try:
                result = await click_button(client, msg_id, bot_entity, btn_data)
            except FloodWaitError as e:
                button_tree.append({
                    "path": current_path,
                    "depth": depth,
                    "button_text": btn_text,
                    "button_data": btn_data,
                    "error": f"FloodWaitError: wait {e.seconds}s",
                })
                stats["errors"] += 1
                break
            except Exception as e:
                button_tree.append({
                    "path": current_path,
                    "depth": depth,
                    "button_text": btn_text,
                    "button_data": btn_data,
                    "error": str(e),
                })
                stats["errors"] += 1
                continue

            node = {
                "path": current_path,
                "depth": depth,
                "button_text": btn_text,
                "button_data": btn_data,
                "callback_answer": result.get("callback_answer"),
                "error": result.get("error"),
            }

            if result.get("error"):
                stats["errors"] += 1
            else:
                stats["successful_responses"] += 1

            # Record new message if any
            if result.get("new_message"):
                node["result_message"] = result["new_message"]
                # Enqueue new buttons from this message
                if depth < max_depth:
                    enqueue_buttons_from(result["new_message"], depth + 1, current_path)

            # Record edited message if any
            if result.get("edited_message"):
                node["result_edited"] = result["edited_message"]
                if depth < max_depth:
                    enqueue_buttons_from(result["edited_message"], depth + 1, current_path)

            if depth > stats["max_depth_reached"]:
                stats["max_depth_reached"] = depth

            button_tree.append(node)

        report["structure"]["button_tree"] = button_tree

        # =====================================================================
        # Phase 4: Reply keyboard buttons
        # =====================================================================
        reply_buttons = []
        reply_results = []

        # Collect reply keyboards from all responses so far
        for phase_key in ("start", "help"):
            phase = report["structure"].get(phase_key, {})
            for resp in phase.get("responses", []):
                for row in resp.get("reply_keyboard", []):
                    for btn in row:
                        if btn.get("type") == "text":
                            reply_buttons.append(btn["text"])

        # Also check button_tree results for reply keyboards
        for node in button_tree:
            for key in ("result_message", "result_edited"):
                msg = node.get(key)
                if msg:
                    for row in msg.get("reply_keyboard", []):
                        for btn in row:
                            if btn.get("type") == "text":
                                reply_buttons.append(btn["text"])

        # Dedupe
        seen_reply = set()
        for btn_text in reply_buttons:
            if btn_text in seen_reply:
                continue
            seen_reply.add(btn_text)

            await asyncio.sleep(INTERACTION_DELAY)
            rec = await send_and_capture(client, bot_entity, btn_text, timeout)
            rec["button_label"] = btn_text
            reply_results.append(rec)
            stats["total_interactions"] += 1
            stats["buttons_explored"] += 1
            if rec["responses"]:
                stats["successful_responses"] += 1
            elif rec["timed_out"]:
                stats["timeouts"] += 1

        report["structure"]["reply_keyboard"] = reply_results

        # =====================================================================
        # Phase 5: Registered commands
        # =====================================================================
        already_tested = {"/start", "/help"}
        reg_results = []

        for cmd_info in report["bot_info"].get("registered_commands", []):
            cmd = cmd_info["command"]
            if cmd in already_tested:
                continue
            already_tested.add(cmd)

            await asyncio.sleep(INTERACTION_DELAY)
            rec = await send_and_capture(client, bot_entity, cmd, timeout)
            rec["command_description"] = cmd_info.get("description", "")
            reg_results.append(rec)
            stats["total_interactions"] += 1
            stats["commands_tested"] += 1
            if rec["responses"]:
                stats["successful_responses"] += 1
                # Enqueue new inline buttons from command responses
                for resp in rec["responses"]:
                    enqueue_buttons_from(resp, 1, cmd)
            elif rec["timed_out"]:
                stats["timeouts"] += 1

        report["structure"]["registered_commands"] = reg_results

        # Explore any new buttons discovered from registered commands
        while button_queue and total_clicked < max_buttons:
            msg_id, btn_text, btn_data, depth, parent_path = button_queue.popleft()
            if depth > max_depth:
                continue

            await asyncio.sleep(INTERACTION_DELAY)
            stats["total_interactions"] += 1
            stats["buttons_explored"] += 1
            total_clicked += 1
            current_path = f"{parent_path} > [{btn_text}]"

            try:
                result = await click_button(client, msg_id, bot_entity, btn_data)
            except FloodWaitError as e:
                button_tree.append({
                    "path": current_path, "depth": depth,
                    "button_text": btn_text, "button_data": btn_data,
                    "error": f"FloodWaitError: wait {e.seconds}s",
                })
                stats["errors"] += 1
                break
            except Exception as e:
                button_tree.append({
                    "path": current_path, "depth": depth,
                    "button_text": btn_text, "button_data": btn_data,
                    "error": str(e),
                })
                stats["errors"] += 1
                continue

            node = {
                "path": current_path, "depth": depth,
                "button_text": btn_text, "button_data": btn_data,
                "callback_answer": result.get("callback_answer"),
                "error": result.get("error"),
            }
            if result.get("error"):
                stats["errors"] += 1
            else:
                stats["successful_responses"] += 1

            if result.get("new_message"):
                node["result_message"] = result["new_message"]
                if depth < max_depth:
                    enqueue_buttons_from(result["new_message"], depth + 1, current_path)
            if result.get("edited_message"):
                node["result_edited"] = result["edited_message"]
                if depth < max_depth:
                    enqueue_buttons_from(result["edited_message"], depth + 1, current_path)

            if depth > stats["max_depth_reached"]:
                stats["max_depth_reached"] = depth

            button_tree.append(node)

        # =====================================================================
        # Phase 6: Commands discovered from /help text
        # =====================================================================
        help_text = ""
        for resp in help_rec.get("responses", []):
            help_text += resp.get("text", "") + "\n"

        discovered_cmds = extract_commands_from_help(help_text)
        discovered_results = []

        for cmd in discovered_cmds:
            if cmd in already_tested:
                continue
            already_tested.add(cmd)

            await asyncio.sleep(INTERACTION_DELAY)
            rec = await send_and_capture(client, bot_entity, cmd, timeout)
            stats["total_interactions"] += 1
            stats["commands_tested"] += 1

            first_text = rec["responses"][0].get("text", "") if rec["responses"] else ""
            if rec["responses"] and not is_unknown_response(first_text):
                rec["recognized"] = True
                stats["successful_responses"] += 1
                discovered_results.append(rec)
                # Enqueue buttons
                for resp in rec["responses"]:
                    enqueue_buttons_from(resp, 1, cmd)
            else:
                rec["recognized"] = False
                if rec["timed_out"]:
                    stats["timeouts"] += 1
                discovered_results.append(rec)

        report["structure"]["discovered_commands"] = discovered_results

        # Explore buttons from discovered commands
        while button_queue and total_clicked < max_buttons:
            msg_id, btn_text, btn_data, depth, parent_path = button_queue.popleft()
            if depth > max_depth:
                continue

            await asyncio.sleep(INTERACTION_DELAY)
            stats["total_interactions"] += 1
            stats["buttons_explored"] += 1
            total_clicked += 1
            current_path = f"{parent_path} > [{btn_text}]"

            try:
                result = await click_button(client, msg_id, bot_entity, btn_data)
            except FloodWaitError as e:
                button_tree.append({
                    "path": current_path, "depth": depth,
                    "button_text": btn_text, "button_data": btn_data,
                    "error": f"FloodWaitError: wait {e.seconds}s",
                })
                stats["errors"] += 1
                break
            except Exception as e:
                button_tree.append({
                    "path": current_path, "depth": depth,
                    "button_text": btn_text, "button_data": btn_data,
                    "error": str(e),
                })
                stats["errors"] += 1
                continue

            node = {
                "path": current_path, "depth": depth,
                "button_text": btn_text, "button_data": btn_data,
                "callback_answer": result.get("callback_answer"),
                "error": result.get("error"),
            }
            if result.get("error"):
                stats["errors"] += 1
            else:
                stats["successful_responses"] += 1
            if result.get("new_message"):
                node["result_message"] = result["new_message"]
                if depth < max_depth:
                    enqueue_buttons_from(result["new_message"], depth + 1, current_path)
            if result.get("edited_message"):
                node["result_edited"] = result["edited_message"]
                if depth < max_depth:
                    enqueue_buttons_from(result["edited_message"], depth + 1, current_path)
            if depth > stats["max_depth_reached"]:
                stats["max_depth_reached"] = depth
            button_tree.append(node)

        # =====================================================================
        # Phase 7: Common commands probing
        # =====================================================================
        probe_results = []
        for cmd in COMMON_COMMANDS:
            if cmd in already_tested:
                continue
            already_tested.add(cmd)

            await asyncio.sleep(INTERACTION_DELAY)
            rec = await send_and_capture(client, bot_entity, cmd, timeout)
            stats["total_interactions"] += 1
            stats["commands_tested"] += 1

            first_text = rec["responses"][0].get("text", "") if rec["responses"] else ""
            if rec["responses"] and not is_unknown_response(first_text):
                rec["recognized"] = True
                stats["successful_responses"] += 1
            else:
                rec["recognized"] = False
                if rec["timed_out"]:
                    stats["timeouts"] += 1

            probe_results.append(rec)

        report["structure"]["common_commands"] = probe_results

        # =====================================================================
        # Phase 8: Input Handling Test (debug mode only)
        # =====================================================================
        if mode == "debug":
            input_results = []
            for inp in DEBUG_INPUTS:
                await asyncio.sleep(INTERACTION_DELAY)
                rec = await send_and_capture(client, bot_entity, inp["value"], timeout)
                rec["input_label"] = inp["label"]
                input_results.append(rec)
                stats["total_interactions"] += 1
                if rec["responses"]:
                    stats["successful_responses"] += 1
                elif rec["timed_out"]:
                    stats["timeouts"] += 1

            report["structure"]["input_handling"] = input_results

        # =====================================================================
        # Phase 9: Button Repeat Test (debug mode only)
        # =====================================================================
        if mode == "debug":
            repeat_results = []
            # Select up to 10 previously visited callback buttons to re-click
            candidates = []
            for node in button_tree:
                if node.get("error"):
                    continue
                if node.get("button_data") and (node.get("result_message") or node.get("result_edited") or node.get("callback_answer")):
                    candidates.append(node)

            sample = candidates[:10] if len(candidates) <= 10 else random.sample(candidates, 10)

            for original in sample:
                btn_data = original["button_data"]
                btn_text = original["button_text"]
                path = original.get("path", "unknown")

                # We need a valid msg_id to click. Try to find one from the latest
                # messages in the chat — re-send /start to get a fresh context.
                await asyncio.sleep(INTERACTION_DELAY)

                # Find a message that has this button data still present
                # The simplest approach: look for messages with inline buttons
                msg_id = None
                async for m in client.iter_messages(bot_entity, limit=20):
                    if m.out:
                        continue
                    if m.reply_markup:
                        inline, _ = extract_button_layout(m.reply_markup)
                        if inline:
                            for row in inline:
                                for btn in row:
                                    if btn.get("data") == btn_data:
                                        msg_id = m.id
                                        break
                                if msg_id:
                                    break
                    if msg_id:
                        break

                if not msg_id:
                    continue

                try:
                    result = await click_button(client, msg_id, bot_entity, btn_data)
                except FloodWaitError as e:
                    repeat_results.append({
                        "path": path,
                        "button_text": btn_text,
                        "button_data": btn_data,
                        "error": f"FloodWaitError: wait {e.seconds}s",
                        "inconsistent": False,
                    })
                    stats["errors"] += 1
                    break
                except Exception as e:
                    repeat_results.append({
                        "path": path,
                        "button_text": btn_text,
                        "button_data": btn_data,
                        "error": str(e),
                        "inconsistent": False,
                    })
                    stats["errors"] += 1
                    continue

                stats["total_interactions"] += 1
                stats["buttons_explored"] += 1

                # Compare with original result
                inconsistent = False
                difference = None

                orig_cb = original.get("callback_answer")
                new_cb = result.get("callback_answer")

                orig_text = ""
                new_text = ""
                for key in ("result_message", "result_edited"):
                    orig_msg = original.get(key)
                    if orig_msg:
                        orig_text = orig_msg.get("text", "")
                for key in ("new_message", "edited_message"):
                    new_msg = result.get(key)
                    if new_msg:
                        new_text = new_msg.get("text", "")

                if orig_cb != new_cb:
                    inconsistent = True
                    difference = f"callback_answer changed: {orig_cb!r} -> {new_cb!r}"
                elif orig_text and new_text and orig_text != new_text:
                    inconsistent = True
                    difference = f"response text changed (first: {len(orig_text)} chars, repeat: {len(new_text)} chars)"
                elif (orig_text and not new_text) or (not orig_text and new_text):
                    inconsistent = True
                    difference = f"response presence changed (first had text: {bool(orig_text)}, repeat: {bool(new_text)})"

                if result.get("error"):
                    stats["errors"] += 1
                else:
                    stats["successful_responses"] += 1

                repeat_results.append({
                    "path": path,
                    "button_text": btn_text,
                    "button_data": btn_data,
                    "inconsistent": inconsistent,
                    "difference": difference,
                    "error": result.get("error"),
                })

            report["structure"]["button_repeat_test"] = repeat_results

        report["test_finished"] = datetime.now(timezone.utc).isoformat()
        report["statistics"] = stats

    except FloodWaitError as e:
        report["error"] = f"FloodWaitError: must wait {e.seconds}s. Test aborted."
        stats["errors"] += 1
    except Exception as e:
        report["error"] = f"{type(e).__name__}: {e}"
        stats["errors"] += 1
    finally:
        await client.disconnect()

    return report


# ---------------------------------------------------------------------------
# Targeted mode — walk a specific path
# ---------------------------------------------------------------------------

def parse_targeted_path(path_str):
    """Parse a targeted path string into a list of steps.

    Format: '/start > [Button A] > [Button B]'
    Returns: ['/start', 'Button A', 'Button B']

    The first element is the command to send.
    Subsequent elements are button texts to click in order.
    """
    parts = [p.strip() for p in path_str.split(">")]
    steps = []
    for part in parts:
        # Strip surrounding [ ] if present
        if part.startswith("[") and part.endswith("]"):
            steps.append(part[1:-1])
        else:
            steps.append(part)
    return steps


def _find_button_in_responses(responses, target_text):
    """Find a callback button matching target_text in a list of serialized responses.

    Uses substring matching and case-insensitive comparison as fallback.
    Returns (msg_id, button_text, button_data) or (None, None, None).
    """
    # Pass 1: exact match
    for resp in responses:
        msg_id = resp.get("id")
        if not msg_id:
            continue
        for row in resp.get("inline_buttons", []):
            for btn in row:
                if btn.get("type") == "callback" and btn.get("text") == target_text:
                    return msg_id, btn["text"], btn["data"]

    # Pass 2: case-insensitive match
    target_lower = target_text.lower()
    for resp in responses:
        msg_id = resp.get("id")
        if not msg_id:
            continue
        for row in resp.get("inline_buttons", []):
            for btn in row:
                if btn.get("type") == "callback" and btn.get("text", "").lower() == target_lower:
                    return msg_id, btn["text"], btn["data"]

    # Pass 3: substring match (target is contained in button text, or vice versa)
    for resp in responses:
        msg_id = resp.get("id")
        if not msg_id:
            continue
        for row in resp.get("inline_buttons", []):
            for btn in row:
                if btn.get("type") != "callback":
                    continue
                btn_text = btn.get("text", "")
                if target_lower in btn_text.lower() or btn_text.lower() in target_lower:
                    return msg_id, btn["text"], btn["data"]

    return None, None, None


async def run_targeted_test(bot_username, path_str, timeout=10):
    """Execute only the specific path and return the result of each step."""
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError

    config, error = load_config()
    if error:
        return {"ok": False, "error": error}

    steps = parse_targeted_path(path_str)
    if not steps:
        return {"ok": False, "error": "Empty path. Use format: /start > [Button A] > [Button B]"}

    client = TelegramClient(config["session_path"], config["api_id"], config["api_hash"])
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        return {"ok": False, "error": "Not authorized. Run tg_login.py --login first."}

    report = {
        "ok": True,
        "mode": "targeted",
        "bot_username": bot_username,
        "path": path_str,
        "test_started": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }

    try:
        try:
            bot_entity = await client.get_entity(bot_username)
        except Exception as e:
            await client.disconnect()
            return {"ok": False, "error": f"Cannot find bot '{bot_username}': {e}"}

        command = steps[0]
        button_steps = steps[1:]

        # Step 1: Send the initial command
        await asyncio.sleep(INTERACTION_DELAY)
        cmd_rec = await send_and_capture(client, bot_entity, command, timeout)

        step_entry = {
            "action": "send_command",
            "command": command,
            "responses": cmd_rec.get("responses", []),
            "error": cmd_rec.get("error"),
            "timed_out": cmd_rec.get("timed_out", False),
        }

        # List available buttons for context
        available_buttons = []
        for resp in cmd_rec.get("responses", []):
            for row in resp.get("inline_buttons", []):
                for btn in row:
                    available_buttons.append(btn.get("text", ""))
        if available_buttons:
            step_entry["available_buttons"] = available_buttons

        report["steps"].append(step_entry)

        if cmd_rec.get("timed_out") or not cmd_rec.get("responses"):
            report["steps"][-1]["note"] = f"Command {command} produced no response, cannot continue path."
            report["test_finished"] = datetime.now(timezone.utc).isoformat()
            await client.disconnect()
            return report

        # Step 2+: Click each button in sequence
        current_responses = cmd_rec.get("responses", [])

        for i, btn_target in enumerate(button_steps):
            await asyncio.sleep(INTERACTION_DELAY)

            msg_id, matched_text, btn_data = _find_button_in_responses(current_responses, btn_target)

            if msg_id is None:
                # Also check edited messages from the previous step's result
                available = []
                for resp in current_responses:
                    for row in resp.get("inline_buttons", []):
                        for btn in row:
                            available.append(btn.get("text", ""))
                report["steps"].append({
                    "action": "click_button",
                    "target": btn_target,
                    "error": f"Button '{btn_target}' not found in current response.",
                    "available_buttons": available,
                })
                break

            try:
                result = await click_button(client, msg_id, bot_entity, btn_data)
            except FloodWaitError as e:
                report["steps"].append({
                    "action": "click_button",
                    "target": btn_target,
                    "matched_text": matched_text,
                    "button_data": btn_data,
                    "error": f"FloodWaitError: wait {e.seconds}s",
                })
                break
            except Exception as e:
                report["steps"].append({
                    "action": "click_button",
                    "target": btn_target,
                    "matched_text": matched_text,
                    "button_data": btn_data,
                    "error": f"{type(e).__name__}: {e}",
                })
                break

            step_entry = {
                "action": "click_button",
                "target": btn_target,
                "matched_text": matched_text,
                "button_data": btn_data,
                "callback_answer": result.get("callback_answer"),
                "error": result.get("error"),
            }

            if result.get("new_message"):
                step_entry["new_message"] = result["new_message"]
            if result.get("edited_message"):
                step_entry["edited_message"] = result["edited_message"]

            # Collect available buttons from the result for next step
            next_responses = []
            if result.get("new_message"):
                next_responses.append(result["new_message"])
            if result.get("edited_message"):
                next_responses.append(result["edited_message"])

            available_buttons = []
            for resp in next_responses:
                for row in resp.get("inline_buttons", []):
                    for btn in row:
                        available_buttons.append(btn.get("text", ""))
            if available_buttons:
                step_entry["available_buttons"] = available_buttons

            report["steps"].append(step_entry)

            # Prepare for next iteration
            current_responses = next_responses
            if not current_responses and i < len(button_steps) - 1:
                report["steps"][-1]["note"] = "No new message or edit after click, cannot continue path."
                break

        report["test_finished"] = datetime.now(timezone.utc).isoformat()

    except FloodWaitError as e:
        report["error"] = f"FloodWaitError: must wait {e.seconds}s. Test aborted."
    except Exception as e:
        report["error"] = f"{type(e).__name__}: {e}"
    finally:
        await client.disconnect()

    return report


def main():
    parser = argparse.ArgumentParser(description="Telegram Bot Deep Explorer")
    parser.add_argument("bot", help="Bot username (e.g. @BotFather)")
    parser.add_argument("--timeout", type=int, default=10, help="Response timeout (default: 10)")
    parser.add_argument("--max-depth", type=int, default=5, help="Max button exploration depth (default: 5)")
    parser.add_argument("--max-buttons", type=int, default=100, help="Max total buttons to click (default: 100)")
    parser.add_argument("--mode", choices=["blueprint", "debug", "targeted"], default="blueprint",
                        help="Test mode: blueprint (structure mapping), debug (bug finding), or targeted (specific path)")
    parser.add_argument("--path", type=str, default=None,
                        help="Targeted mode path, e.g. '/start > [Button A] > [Button B]'")
    parser.add_argument("--save", action="store_true", help="Save report to ~/.telegram-bot-autotest/reports/")

    args = parser.parse_args()

    bot = args.bot
    if not bot.startswith("@"):
        bot = "@" + bot

    if args.mode == "targeted":
        if not args.path:
            print(json.dumps({"ok": False, "error": "--path is required for targeted mode. Example: --path='/start > [Button A]'"}))
            sys.exit(1)
        report = asyncio.run(run_targeted_test(bot, args.path, timeout=args.timeout))
    else:
        report = asyncio.run(run_test(
            bot, timeout=args.timeout, max_depth=args.max_depth,
            max_buttons=args.max_buttons, mode=args.mode,
        ))

        # In debug mode, run bug analysis on the completed report
        if args.mode == "debug" and report.get("ok"):
            bugs = analyze_bugs(report)
            report["bugs"] = bugs
            report["health_score"] = compute_health_score(bugs)

    if args.save and report.get("ok"):
        reports_dir = Path.home() / ".telegram-bot-autotest" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{bot.lstrip('@')}_{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = reports_dir / filename
        filepath.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        report["saved_to"] = str(filepath)

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not report.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
