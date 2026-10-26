"""Native agy transcript reader, verified against CLI 1.4.7 and Google hooks.

https://antigravity.google/docs/hooks?tab=cli names the conversation-bound
transcript path. Rows carry no conversation ID; only that canonical path can
bind them to a session. Archived arbitrary JSONL cannot prove delivery.
No SQLite/protobuf decoding, transcript copying or credential access.
"""

from pathlib import Path
import json
import math
import os
import re
import subprocess

from .errors import HerdrError, ParseError


SESSION = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z")
SOURCE = "herdr:antigravity_cli"
#: Claude models launch without `--effort` (#73). CLI 1.4.7 answered
#: `--model claude-sonnet-4-6 --effort high` with a warning and ran Gemini 3.8
#: Flash; without the flag both models below ran as requested. Their effort is
#: never displayed, so it stays unknown rather than measured.
NO_EFFORT_MODELS = frozenset({"claude-opus-4-6-thinking", "claude-sonnet-4-6"})
#: The captured native display of each requested `(model, effort)` pair (#73):
#: the running model its idle footer names, its first turn's `Model Selection`
#: and the effort that display proves. Claude pairs show no effort, so theirs
#: stays unknown. The captured Gemini fallback renders its footer and selection
#: differently (`Gemini 3.8 Flash · high`, `Gemini 3.8 Flash (High)`), so each
#: is kept. No Gemini-requested launch is captured yet. A pair absent here is
#: refused before input until its capture is added, as
#: references/antigravity.md Admission Capture names.
CAPTURED_DISPLAYS: "dict[tuple[str, str | None], dict[str, str]]" = {
    ("claude-opus-4-6-thinking", None): {"footer": "Claude Opus 4.6 (Thinking)",
                                         "selection": "Claude Opus 4.6 (Thinking)", "effort": "unknown"},
    ("claude-sonnet-4-6", None): {"footer": "Claude Sonnet 4.6 (Thinking)",
                                  "selection": "Claude Sonnet 4.6 (Thinking)", "effort": "unknown"},
}
#: The idle footer's last visible row: shortcut hint, then the running model.
FOOTER = re.compile(r"\? for shortcuts {2,}(\S(?:.*\S)?)")
USAGE_TIMEOUT = 20
USAGE_BYTES = 65_536
#: CLI 1.4.7 stores a submitted prompt as `<USER_REQUEST>\n{prompt}\n</USER_REQUEST>`
#: followed by these native blocks, in this order, each at most once (#74).
REQUEST_OPEN = "<USER_REQUEST>\n"
REQUEST_CLOSE = "\n</USER_REQUEST>"
TRAILING_BLOCKS = ("ADDITIONAL_METADATA", "USER_SETTINGS_CHANGE")
ENVELOPE_TAG = re.compile(r"</?(?:USER_REQUEST|ADDITIONAL_METADATA|USER_SETTINGS_CHANGE)>")
TRAILING_BLOCK = re.compile(r"\n<([A-Z_]+)>\n(.*?)\n</\1>", re.DOTALL)
MODEL_SELECTION = re.compile(
    r"The user changed setting `Model Selection` from ([^\n`]+?) to ([^\n`]+?)\. "
    r"No need to comment on this change if the user doesn't ask about it\. "
    r"If reporting what model you are, please use a human readable name instead of the exact string\.")


def parse_usage(text):
    """Read the native slash-command JSON; remaining fractions are not usage."""
    try:
        data = json.loads(text)
        if data.get("status") != "SUCCESS" or data.get("command", {}).get("name") != "usage":
            raise ValueError("usage command failed")
        groups = data["command"]["data"]["groups"]
        if not isinstance(groups, list) or not groups:
            raise ValueError("subscription quota absent")
        windows = {}
        for group in groups:
            name = group["name"]
            if not isinstance(name, str) or not name:
                raise ValueError("quota group absent")
            buckets = group["buckets"]
            if not isinstance(buckets, list) or not buckets:
                raise ValueError("quota buckets absent")
            for bucket in buckets:
                fraction, reset = bucket["remaining_fraction"], bucket["reset_time"]
                key = name + "/" + bucket["id"]
                if (key in windows or isinstance(fraction, bool) or not isinstance(fraction, (int, float))
                        or not math.isfinite(fraction) or not 0 <= fraction <= 1
                        or not isinstance(reset, str) or not reset):
                    raise ValueError("quota reading invalid")
                remaining = round(100 * fraction, 6)
                windows[key] = {"remaining_pct": remaining, "used_pct": round(100 - remaining, 6), "resets": reset}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ParseError("Cannot read Antigravity subscription quota. Run `agy -p /usage --output-format json` under the worker's Google sign-in; restore nonempty quota groups before staffing it.", {"kind": "agy"}) from None
    return {"windows": windows, "credits": None, "plan": None}


def subscription_usage(*, run=subprocess.run):
    """Read account quota without a model turn or API-key fallback."""
    environment = {key: value for key, value in os.environ.items() if key not in {
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_APPLICATION_CREDENTIALS", "AGY_ADC_AUTH"}}
    try:
        result = run(["agy", "-p", "/usage", "--output-format", "json", "--print-timeout", "15s"],
                     capture_output=True, text=True, timeout=USAGE_TIMEOUT, check=False, env=environment)
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired):
        raise HerdrError("Antigravity quota lookup failed. Install native `agy`, sign in to the Google subscription on this controller host, then retry only this provider.", {"kind": "agy"}) from None
    if result.returncode or len(result.stdout.encode("utf-8")) > USAGE_BYTES:
        raise HerdrError("Antigravity quota lookup did not return a bounded successful result. Run `agy -p /usage --output-format json` with the worker's subscription sign-in before retrying this provider.", {"kind": "agy"})
    return parse_usage(result.stdout)


def captured_display(tier):
    """The captured native display of a requested tier's exact pair, or None when unproven."""
    model = tier.get("model") if isinstance(tier, dict) else None
    effort = tier.get("effort") if isinstance(tier, dict) else None
    if not isinstance(model, str) or effort is not None and not isinstance(effort, str):
        return None
    return CAPTURED_DISPLAYS.get((model, effort))


def displayed_model(text):
    """The model the live footer names, or None when the read shows no footer."""
    rows = [row.rstrip() for row in text.splitlines() if row.strip()] if isinstance(text, str) else []
    match = FOOTER.fullmatch(rows[-1]) if rows else None
    return match.group(1) if match else None


def admit_model(tier, text):
    """Prove from the native display that the requested model runs; argv only asks.

    Returns the display proof with the effort its capture proves: `unknown`
    for a no-effort Claude model, whose effort no native surface shows.
    """
    captured, shown = captured_display(tier), displayed_model(text)
    details = {"kind": "agy", "model": tier.get("model"), "effort": tier.get("effort"), "displayed": shown}
    if captured is None:
        raise HerdrError("Antigravity has no captured native display for model {!r} at effort {}, so nothing proves it "
                         "would run as requested; nothing was sent. Configure a captured pair, or capture this exact "
                         "pair's native launch as skills/herdr-foreman/references/antigravity.md Admission Capture "
                         "names.".format(tier.get("model"), tier.get("effort") or "none"), details)
    if shown is None:
        raise HerdrError("Antigravity's native model footer is not visible, so the running model is unproven; inspect "
                         "the pane before retrying. Nothing was sent.", details)
    if shown != captured["footer"]:
        raise HerdrError("Antigravity runs {!r}, not the requested {!r}; nothing was sent. Start a fresh worker with "
                         "a launch the native CLI honors.".format(shown, captured["footer"]), details)
    return {"source": "native_display", "label": shown, "effort": captured["effort"]}


def sessions_root():
    return (Path.home() / ".gemini/antigravity-cli/brain").resolve()


def transcript_path(session):
    if not isinstance(session, str) or SESSION.fullmatch(session) is None:
        return None
    return sessions_root() / session / ".system_generated/logs/transcript.jsonl"


def main_turn(rows, session, path):
    """Return the latest explicit user turn only under its actual native path."""
    expected = transcript_path(session)
    if expected is None or path is None or Path(path) != expected or expected.resolve() != expected:
        return None
    indexed = {}
    for row in rows:
        index = row.get("step_index")
        if type(index) is not int or index < 0 or index in indexed:
            return None
        indexed[index] = row
    ordered = [indexed[index] for index in sorted(indexed)]
    start = None
    for offset, row in enumerate(ordered):
        if row.get("type") == "USER_INPUT" and row.get("source") == "USER_EXPLICIT":
            if row.get("status") != "DONE" or not isinstance(row.get("content"), str):
                return None
            start = offset
    return ordered[start:] if start is not None else None


def final_message(rows, session, path):
    turn = main_turn(rows, session, path)
    if not turn or len(turn) < 2:
        return None
    final = turn[-1]
    if (final.get("type") != "PLANNER_RESPONSE" or final.get("source") != "MODEL"
            or final.get("status") != "DONE" or not isinstance(final.get("content"), str)):
        return None
    return final["content"]


def user_request(content):
    """Split one native USER_INPUT envelope, or None when it is not exactly one.

    The request keeps every byte between its framing newlines, multiline
    whitespace included. Any other prefix, a wrapper tag inside the request or
    a block, an unknown, repeated or reordered block, a settings block other
    than the model selection, and trailing bytes all refuse.
    """
    if not isinstance(content, str) or not content.startswith(REQUEST_OPEN):
        return None
    end = content.find(REQUEST_CLOSE)
    if end < 0:
        return None
    request, rest = content[len(REQUEST_OPEN):end], content[end + len(REQUEST_CLOSE):]
    if ENVELOPE_TAG.search(request):
        return None
    order = {tag: index for index, tag in enumerate(TRAILING_BLOCKS)}
    position, blocks = 0, {}
    while rest:
        match = TRAILING_BLOCK.match(rest)
        if match is None or order.get(match.group(1), -1) < position:
            return None
        tag, body = match.groups()
        if not body or ENVELOPE_TAG.search(body):
            return None
        position = order[tag] + 1
        blocks[tag] = body
        rest = rest[match.end():]
    selection = None
    if "USER_SETTINGS_CHANGE" in blocks:
        match = MODEL_SELECTION.fullmatch(blocks["USER_SETTINGS_CHANGE"])
        if match is None:
            return None
        selection = match.group(2)
    return {"request": request, "model_selection": selection}


def prompt_text(rows, session, path):
    """The exact dispatched text of the latest explicit turn, never its envelope."""
    turn = main_turn(rows, session, path)
    envelope = user_request(turn[0]["content"]) if turn else None
    return envelope["request"] if envelope else None


def model_selection(rows, session, path):
    """The model the latest explicit turn's native settings change selected, or None."""
    turn = main_turn(rows, session, path)
    envelope = user_request(turn[0]["content"]) if turn else None
    return envelope["model_selection"] if envelope else None
