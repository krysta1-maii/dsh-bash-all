#!/usr/bin/env python3
"""Analyze exported agent conversation JSONL files for the dsh-bash-all Phase 1 tests.

The script intentionally uses only the Python standard library so it can run in a
fresh shell environment.

Typical usage:
    python3 analyze_logs.py logs/phase1
    python3 analyze_logs.py logs/phase1 -o logs/analysis
    python3 analyze_logs.py single-file.jsonl --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MESSAGE_ROLES = {"user", "assistant", "system", "tool", "developer"}
OBSERVATION_TYPES = {
    "tool",
    "tool_result",
    "tool/result",
    "tool-result",
    "tool_use_result",
    "tool_result_message",
    "observation",
    "function_results",
    "function_result",
}

TOOL_RESULT_ID_KEYS = ("tool_use_id", "tool_call_id", "toolCallId")
TOOL_CALL_TYPES = {"tool_call", "tool_use", "function_call", "function"}

# Internal DSH events that are not part of the main conversation transcript and
# would otherwise duplicate a user message or introduce title-generation noise.
SKIP_SUBTREE_TYPES = {
    # Internal / duplicate DSH event types.  Canonical execution events are
    # `tool/call` and `tool/result`; the chunk events below are stream deltas.
    "agent/inbox/spliced",
    "session/title-llm-request",
    "session/title",
    "assistant/chunk",
    "reasoning-chunks",
    "tool-call-chunks",
    "text-chunks",
    # Request headers/context contain tool schemas, not executed tool calls.
    "request/header",
    "request/context",
}

# Shell tools whose `command` argument should be parsed as a bash command.
BASH_TOOL_NAMES = {
    "bash",
    "shell",
    "terminal",
    "cmd",
    "bashcommand",
    "bash_command",
    "run_bash",
    "run_bash_command",
    "execute_bash",
    "run_shell",
    "run_shell_command",
    "execute_shell",
    "shell_command",
    "terminal_command",
}

BASH_TOOL_NORMALIZED = {re.sub(r"[^a-z0-9]+", "", name) for name in BASH_TOOL_NAMES}

# Token names we strip when looking for the effective first executable.
SHELL_PREFIX_TOKENS = {"sudo", "command", "builtin", "nohup", "nice", "time"}

SHELL_KEYWORDS = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "for",
    "do",
    "done",
    "while",
    "until",
    "case",
    "esac",
    "function",
    "select",
    "coproc",
    "in",
    "{",
    "}",
    "!",
}

# Keys that may carry a bash command string inside a shell-tool argument object.
COMMAND_KEYS = (
    "command",
    "cmd",
    "shell_command",
    "command_line",
    "commands",
    "script",
    "code",
)

SESSION_KEYS = (
    "conversation_id",
    "session_id",
    "thread_id",
    "run_id",
    "trace_id",
    "task_id",
    "request_id",
    "chat_id",
    "conversation",
    "session",
    "thread",
)

USAGE_KEYS = ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens", "total_tokens")

ASSIGNMENT_RE = re.compile(
    r"^(?:(?:[A-Za-z_]\w*)= (?:\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s;|&]+) \s*)+",
    re.VERBOSE,
)

MODULE_MISSING_RE = re.compile(
    r"(?:(?:ModuleNotFoundError|ImportError)\s*:\s*)?"
    r"No module named\s+['\"]?(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
    re.IGNORECASE,
)
CMD_NOT_FOUND_RE = re.compile(
    r"(?:^|[\r\n])"
    r"(?:(?:/(?:usr/)?bin/)?(?:bash|sh|zsh|fish|dash)\s*:\s*"
    r"(?:line\s+\d+\s*:\s*|\d+\s*:\s*)?)?"
    r"(?P<cmd>[A-Za-z_][A-Za-z0-9_.+-]*)"
    r"\s*:\s*"
    r"(?:command not found|not found)"
    r"(?=\s*(?:\r?\n|$))",
    re.MULTILINE,
)
CMD_NOT_FOUND_PREFIX_RE = re.compile(
    r"command not found\s*:\s*(?P<cmd>[A-Za-z_][A-Za-z0-9_.+-]*)",
    re.IGNORECASE,
)

PIP_INSTALL_RE = re.compile(
    r"\b(?:python(?:3(?:\.\d+)?)?\s+-m\s+pip|pip3?|uv\s+pip)\s+install\s+(?P<packages>[^\n;&|]+)"
)
PIPX_INSTALL_RE = re.compile(r"\bpipx\s+install\s+(?P<packages>[^\n;&|]+)")
NPM_INSTALL_RE = re.compile(r"\bnpm\s+(?:install|i)\s+(?P<packages>[^\n;&|]+)")
PNPM_ADD_RE = re.compile(r"\bpnpm\s+add\s+(?P<packages>[^\n;&|]+)")
APT_INSTALL_RE = re.compile(r"\bapt(?:-get)?\s+(?:install|add)\s+(?P<packages>[^\n;&|]+)")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def is_string(value: Any) -> bool:
    return isinstance(value, str)


def text_to_str(value: Any, limit: int = 200_000) -> str:
    """Best-effort conversion of arbitrary JSON content to a string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.append(text_to_str(item, limit))
            if sum(len(p) for p in parts) > limit:
                break
        return "\n".join(parts)[:limit]
    if isinstance(value, dict):
        # Anthropic-style blocks: {"type":"text","text":"..."}
        for key in ("text", "content", "message", "value"):
            if key in value:
                return text_to_str(value[key], limit)
        try:
            return json.dumps(value, ensure_ascii=False)[:limit]
        except (TypeError, ValueError):
            return ""
    return ""


def parse_json_if_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return value
    return parsed


def top_module(module_name: str) -> str:
    return module_name.split(".", 1)[0]


def path_to_session_name(path: Path) -> str:
    return path.stem or path.name


def detect_session(value: Any) -> str | None:
    """Return a session identifier from an event/message object, if present."""
    if not isinstance(value, dict):
        return None
    for key in SESSION_KEYS:
        raw = value.get(key)
        if is_string(raw) and raw.strip():
            return raw.strip()
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return str(raw)
    return None


# ---------------------------------------------------------------------------
# Shell command parsing
# ---------------------------------------------------------------------------


def mask_heredocs(text: str) -> str:
    """Replace heredoc bodies with blank lines so they don't look like commands."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.search(
            r"<<-?\s*(?P<q>\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|(?P<word>[A-Za-z_]\w*))",
            line,
        )
        if match:
            delimiter = match.group("word") or match.group("q")[1:-1]
            # Keep only the prefix of the line (the command before `<<`).
            out.append(line[: match.start()])
            i += 1
            # Skip until the terminator line.  POSIX allows the delimiter to be
            # preceded by tabs when `<<-` is used.
            while i < len(lines):
                term = lines[i].strip()
                if term == delimiter or term == delimiter + "\r":
                    break
                i += 1
            # Do not append the delimiter line itself.
            i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _quote_aware_split(text: str) -> list[str]:
    """Split a shell command string on unquoted newline/; /| /&.

    This is deliberately approximate: it only needs to recover executable
    tokens from model-generated bash commands, not parse shell perfectly.
    """
    text = mask_heredocs(text)
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    escaped = False
    paren_depth = 0

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if escaped:
            buf.append(ch)
            escaped = False
            i += 1
            continue

        if quote is not None:
            buf.append(ch)
            if ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch == "'" or ch == '"':
            quote = ch
            buf.append(ch)
            i += 1
            continue

        if ch == "\\":
            escaped = True
            buf.append(ch)
            i += 1
            continue

        # Track $(...) and plain (...) nesting so separators inside command
        # substitutions are not treated as top-level separators.
        if ch == "$" and nxt == "(":
            paren_depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            paren_depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")" and paren_depth > 0:
            paren_depth -= 1
            buf.append(ch)
            i += 1
            continue

        if paren_depth == 0 and ch in "\n;":
            segments.append("".join(buf))
            buf = []
            i += 1
            continue

        if paren_depth == 0 and ch == "|":
            segments.append("".join(buf))
            buf = []
            i += 1
            if nxt == "&":
                i += 1
            continue

        if paren_depth == 0 and ch == "&":
            # `cmd &`, `cmd && other`.  Do not split redirections like `2>&1`.
            if nxt == "&":
                segments.append("".join(buf))
                buf = []
                i += 2
                continue
            prev = text[i - 1] if i > 0 else ""
            prev_non_space = None
            j = i - 1
            while j >= 0 and text[j].isspace():
                j -= 1
            if j >= 0:
                prev_non_space = text[j]
            if prev_non_space in (">", "<"):
                buf.append(ch)
                i += 1
                continue
            if prev.strip() == "" or prev.isspace() or (i + 1 < n and nxt.isspace()):
                segments.append("".join(buf))
                buf = []
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue

        buf.append(ch)
        i += 1

    segments.append("".join(buf))
    return segments


def _strip_assignments_and_prefixes(tokens: list[str]) -> list[str]:
    tokens = list(tokens)
    # `VAR=value` prefixes and common shell prefixes.
    changed = True
    while changed:
        changed = False
        if tokens and re.match(r"^[A-Za-z_]\w*=", tokens[0]):
            tokens.pop(0)
            changed = True
            continue
        if tokens and tokens[0].lower() in SHELL_PREFIX_TOKENS:
            tokens.pop(0)
            changed = True
            # `time` can take `-p`; `nice` can take `-n 10`.
            if tokens and tokens[0].startswith("-"):
                tokens.pop(0)
            continue
        if tokens and tokens[0] == "env":
            tokens.pop(0)
            changed = True
            while tokens and (tokens[0].startswith("-") or "=" in tokens[0]):
                tokens.pop(0)
    return tokens


def _tokens_or_fallback(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        # Keep this fallback intentionally simple.
        return re.findall(r"'[^']*'|\"[^\"]*\"|\S+", segment)


def extract_executables(command: str) -> list[str]:
    """Return an approximate list of executable tokens used in a bash command."""
    if not is_string(command) or not command.strip():
        return []
    found: list[str] = []
    for segment in _quote_aware_split(command):
        segment = segment.strip()
        if not segment or segment.startswith("#"):
            continue
        tokens = _tokens_or_fallback(segment)
        tokens = _strip_assignments_and_prefixes(tokens)
        if not tokens:
            continue
        exe = tokens[0]
        # Strip quoting artifacts from the fallback path.
        if exe and exe[0] in ("'", '"'):
            try:
                exe = shlex.split(exe)[0]
            except ValueError:
                pass
        if not exe:
            continue
        low = exe.lower()
        if low in SHELL_KEYWORDS:
            continue
        if exe.startswith("-"):
            continue
        # Normalize common path forms to the basename.
        exe = exe.rstrip("/")
        exe = os.path.basename(exe) if "/" in exe else exe
        if exe:
            found.append(exe)
    return found


def extract_capability_probes(command: str) -> list[str]:
    """Detect explicit environment probes such as `which jq`, `command -v fd`.

    These are valuable even when the probed binary is absent, because `which`
    returns non-zero silently and therefore produces no `command not found`
    observation.
    """
    if not is_string(command) or not command.strip():
        return []
    probes: list[str] = []
    for segment in _quote_aware_split(command):
        segment = segment.strip()
        if not segment or segment.startswith("#"):
            continue
        raw = _tokens_or_fallback(segment)
        # Remove leading VAR=value assignments, but NOT `command`/`which` etc.
        while raw and re.match(r"^[A-Za-z_]\w*=", raw[0]):
            raw.pop(0)
        if not raw:
            continue
        head = raw[0]
        candidates: list[str] = []
        if head == "which":
            candidates = raw[1:]
        elif head == "command" and len(raw) >= 2 and raw[1] in ("-v", "-V", "--version"):
            candidates = raw[2:]
        elif head == "type" and len(raw) >= 2 and raw[1] in ("-a", "-p", "-P", "-t"):
            candidates = raw[2:]
        elif head == "hash":
            candidates = raw[1:]
        else:
            continue

        for token in candidates:
            if not token or token.startswith("-"):
                continue
            if any(ch in token for ch in "<>|&;="):
                continue
            try:
                clean = shlex.split(token)[0] if shlex.split(token) else token
            except ValueError:
                clean = token.strip("\"'")
            clean = clean.rstrip("/")
            clean = os.path.basename(clean) if "/" in clean else clean
            if re.match(r"^[A-Za-z_][A-Za-z0-9_.+-]*$", clean):
                probes.append(clean)
    return probes


# ---------------------------------------------------------------------------
# Pattern extraction
# ---------------------------------------------------------------------------

# `[^\S\r\n]+` (spaces/tabs only) prevents comments like
# `# copied from before\nimport struct` from being mistaken for an import.
IMPORT_LINE_RE = re.compile(
    r"\b(?:"
    r"from[^\S\r\n]+(?P<from>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)[^\S\r\n]+import\b"
    r"|"
    r"import[^\S\r\n]+(?P<import>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\b"
    r")"
)


def extract_imports(command: str) -> list[str]:
    if not is_string(command):
        return []
    modules: list[str] = []
    for match in IMPORT_LINE_RE.finditer(command):
        module = match.group("from") or match.group("import")
        if module:
            modules.append(module)
    return modules


def extract_installs(command: str) -> list[tuple[str, str]]:
    """Return [(package_manager, raw_packages_text), ...] for install commands."""
    if not is_string(command):
        return []
    results: list[tuple[str, str]] = []
    for regex, manager in (
        (PIP_INSTALL_RE, "pip"),
        (PIPX_INSTALL_RE, "pipx"),
        (NPM_INSTALL_RE, "npm"),
        (PNPM_ADD_RE, "pnpm"),
        (APT_INSTALL_RE, "apt"),
    ):
        for match in regex.finditer(command):
            raw = match.group("packages").strip().rstrip("\\")
            if raw:
                results.append((manager, raw))
    return results


def _add_missing(mapping: Counter, key: str, source_file: str) -> None:
    mapping[key] += 1


def extract_missing_from_text(text: str) -> tuple[list[str], list[str]]:
    """Extract missing shell commands and missing Python modules from an observation."""
    if not is_string(text) or not text:
        return [], []
    missing_commands: list[str] = []
    missing_modules: list[str] = []

    # zsh-style: `command not found: jq`
    for match in CMD_NOT_FOUND_PREFIX_RE.finditer(text):
        missing_commands.append(match.group("cmd"))

    # bash-style: `jq: command not found`
    for match in CMD_NOT_FOUND_RE.finditer(text):
        missing_commands.append(match.group("cmd"))

    for match in MODULE_MISSING_RE.finditer(text):
        missing_modules.append(match.group("module"))

    return missing_commands, missing_modules


# ---------------------------------------------------------------------------
# Event walking
# ---------------------------------------------------------------------------


def _contains_tool_result(value: dict[str, Any]) -> bool:
    """True when a message object embeds a tool-result content block."""
    typ = value.get("type")
    if is_string(typ) and typ.strip().lower() in OBSERVATION_TYPES:
        return True
    if any(k in value for k in TOOL_RESULT_ID_KEYS):
        return True
    content = value.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if is_string(block_type) and block_type.strip().lower() in OBSERVATION_TYPES:
                    return True
                if any(k in block for k in TOOL_RESULT_ID_KEYS):
                    return True
    return False


def _mark_nested_content_blocks(value: dict[str, Any], seen_messages: set[int]) -> None:
    """Mark child content-block dicts as already counted as messages."""
    content = value.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                seen_messages.add(id(block))
                nested = block.get("content")
                if isinstance(nested, list):
                    for child in nested:
                        if isinstance(child, dict):
                            seen_messages.add(id(child))


def extract_message(value: dict[str, Any]) -> tuple[str | None, str]:
    """Return (role, text) if this dict looks like a message/observation."""
    role = value.get("role")
    typ = value.get("type")
    if is_string(role):
        role = role.strip().lower()
    if is_string(typ):
        typ = typ.strip().lower()

    text = ""
    if is_string(value.get("content")):
        text = value.get("content")
    elif "content" in value:
        text = text_to_str(value.get("content"))
    elif is_string(value.get("text")):
        text = value.get("text")
    elif is_string(value.get("message")):
        text = value.get("message")

    if role in MESSAGE_ROLES:
        if role == "user" and _contains_tool_result(value):
            return "tool", text
        return role, text
    if typ in MESSAGE_ROLES:
        if typ == "user" and _contains_tool_result(value):
            return "tool", text
        return typ, text
    if _contains_tool_result(value):
        return "tool", text
    if any(k in value for k in TOOL_RESULT_ID_KEYS):
        if text:
            return "tool", text
    if typ in {"error", "stderr"} and text:
        return "tool", text
    return None, ""


def looks_like_tool_call(value: dict[str, Any]) -> bool:
    typ = value.get("type")
    if typ == "tool-call":
        # DSH embeds a `"type":"tool-call"` block inside assistant/message;
        # the canonical execution event is the top-level `type:"tool/call"`.
        # Counting both would triple-count every tool call.
        return False
    if is_string(typ) and typ.strip().lower() in TOOL_CALL_TYPES:
        # Some messages have type "function" only as an event envelope.
        if any(k in value for k in ("name", "function", "tool_name", "input", "arguments", "parameters")):
            return True
    if "function" in value and isinstance(value.get("function"), dict):
        return True
    if any(k in value for k in ("tool_name",)):
        return True
    if is_string(value.get("name")) and any(
        k in value for k in ("input", "arguments", "parameters", "command", "cmd", "script")
    ):
        return True
    return False


def get_tool_call(value: dict[str, Any]) -> tuple[str | None, Any]:
    """Return (tool_name, arguments) from a tool-call-shaped dict."""
    name: Any = value.get("name") or value.get("tool_name")
    if not name and isinstance(value.get("function"), dict):
        name = value["function"].get("name")

    args: Any = None
    for key in ("input", "arguments", "parameters"):
        if key in value and value[key] is not None:
            args = value[key]
            break
    if isinstance(value.get("function"), dict):
        if args is None:
            args = value["function"].get("arguments") or value["function"].get("input")
    if args is None and any(k in value for k in ("command", "cmd", "script")):
        args = {k: value[k] for k in ("command", "cmd", "script") if k in value}

    args = parse_json_if_string(args)
    return (name if is_string(name) else None), args


def find_command_string(args: Any) -> str:
    args = parse_json_if_string(args)
    if is_string(args):
        # Some logs put the raw command directly in `arguments`.
        return args
    if isinstance(args, dict):
        for key in COMMAND_KEYS:
            if is_string(args.get(key)) and args.get(key).strip():
                return args[key]
        # One more level of nesting, e.g. {"input": {"command": "..."}}.
        for key in ("input", "arguments", "parameters"):
            nested = args.get(key)
            if isinstance(nested, dict):
                for command_key in COMMAND_KEYS:
                    if is_string(nested.get(command_key)) and nested.get(command_key).strip():
                        return nested[command_key]
    return ""


def is_bash_tool(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", name.strip().lower())
    if normalized in BASH_TOOL_NORMALIZED:
        return True
    return "bash" in normalized or "shell" in normalized or "terminal" in normalized


def merge_usage(session: dict[str, Any], value: dict[str, Any], seen: set[int]) -> None:
    usage_sources: list[Any] = []
    if isinstance(value.get("usage"), dict):
        usage_sources.append(value["usage"])
    for key in ("token_usage", "tokens", "usage_stats"):
        if isinstance(value.get(key), dict):
            usage_sources.append(value[key])
    has_direct = any(k in value for k in USAGE_KEYS)
    if has_direct:
        usage_sources.append(value)

    merged: dict[str, Any] = {}
    for usage in usage_sources:
        marker = id(usage)
        if marker in seen:
            continue
        seen.add(marker)
        for key in USAGE_KEYS:
            raw = usage.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                merged[key] = max(merged.get(key, 0), raw)

    totals = session.setdefault("usage", {})
    for key, amount in merged.items():
        if key == "total_tokens":
            totals[key] = totals.get(key, 0) + amount
        elif key.endswith("_tokens") and key != "total_tokens":
            totals[key] = totals.get(key, 0) + amount


def walk(value: Any, session_id: str, source_file: str, session_store: dict[str, dict[str, Any]], seen_messages: set[int], seen_tools: set[int], seen_usage: set[int]) -> None:
    if isinstance(value, list):
        for item in value:
            walk(item, session_id, source_file, session_store, seen_messages, seen_tools, seen_usage)
        return

    if not isinstance(value, dict):
        return

    if value.get("type") in SKIP_SUBTREE_TYPES:
        return

    # Allow nested records to switch session when the log contains several
    # conversations in one file.
    detected = detect_session(value)
    current_session = detected or session_id
    session = session_store.setdefault(current_session, {})
    session.setdefault("source_file", source_file)
    session.setdefault("seq", 0)

    # Lightweight DSH session metadata, useful when comparing A/B variants.
    typ = value.get("type")
    if typ == "session":
        if value.get("cwd"):
            session.setdefault("cwd", value.get("cwd"))
        if value.get("agentPreset"):
            session.setdefault("agent_preset_initial", value.get("agentPreset"))
        if value.get("id") and not session.get("ds_session_id"):
            session["ds_session_id"] = value.get("id")
    elif typ == "agent-preset/selected" and isinstance(value.get("data"), dict):
        preset = value["data"].get("agentPreset")
        if is_string(preset):
            session["agent_preset_selected"] = preset

    merge_usage(session, value, seen_usage)

    marker = id(value)
    if marker not in seen_messages:
        role, text = extract_message(value)
        if text:
            seen_messages.add(marker)
            session["seq"] += 1
            roles = session.setdefault("role_counts", Counter())
            roles[role or "unknown"] += 1
            session.setdefault("message_count", 0)
            session["message_count"] += 1

            _mark_nested_content_blocks(value, seen_messages)

            if role == "tool" or _contains_tool_result(value):
                missing_commands, missing_modules = extract_missing_from_text(text)
                for cmd in missing_commands:
                    _add_missing(session.setdefault("missing_commands", Counter()), cmd, source_file)
                for mod in missing_modules:
                    _add_missing(session.setdefault("missing_modules", Counter()), mod, source_file)

    if marker not in seen_tools and looks_like_tool_call(value):
        seen_tools.add(marker)
        # If this wrapper has a nested `function` dict, mark it as handled so the
        # recursive walk doesn't count it a second time.
        if isinstance(value.get("function"), dict):
            seen_tools.add(id(value["function"]))

        tool_name, args = get_tool_call(value)
        if tool_name:
            session.setdefault("seq", 0)
            session["seq"] += 1
            tools = session.setdefault("tool_calls", Counter())
            normalized_tool_name = tool_name.strip().lower()
            tools[normalized_tool_name] += 1
            tools_total = session.setdefault("tool_call_count", 0)
            tools_total += 1
            session["tool_call_count"] = tools_total

            if session.get("first_action_seq") is None:
                session["first_action_seq"] = session["seq"]

            if is_bash_tool(tool_name):
                command = find_command_string(args)
                if command:
                    session.setdefault("bash_call_count", 0)
                    session["bash_call_count"] += 1
                    session.setdefault("bash_commands", []).append(command)
                    executables = extract_executables(command)
                    for exe in executables:
                        session.setdefault("executables", Counter())[exe] += 1
                    # Only scan commands that actually invoke Python; otherwise
                    # heredoc contents such as HTML/JS text may create noise.
                    for probe in extract_capability_probes(command):
                        session.setdefault("capability_probes", Counter())[probe] += 1
                    if any(exe.startswith("python") for exe in executables):
                        for module in extract_imports(command):
                            session.setdefault("imports", Counter())[module] += 1
                    for manager, raw in extract_installs(command):
                        session.setdefault("install_attempts", Counter())[manager] += 1
                        session.setdefault("install_packages", Counter())[raw] += 1
            elif tool_name.lower().replace("_", "") in {"strreplaceeditor", "strreplace", "editor"} or "editor" in tool_name.lower():
                session.setdefault("editor_call_count", 0)
                session["editor_call_count"] += 1

    # Recurse into nested values.
    for child in value.values():
        walk(child, current_session, source_file, session_store, seen_messages, seen_tools, seen_usage)


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------


def process_jsonl_file(path: Path, session_store: dict[str, dict[str, Any]], stats: Counter) -> None:
    fallback_session = path_to_session_name(path)
    ok_lines = 0
    bad_lines = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                bad_lines += 1
                if bad_lines <= 3:
                    print(f"  [warn] {path}:{line_no}: invalid JSON: {exc}", file=sys.stderr)
                continue

            ok_lines += 1
            if isinstance(payload, dict) and not payload:
                continue

            seen_messages: set[int] = set()
            seen_tools: set[int] = set()
            seen_usage: set[int] = set()
            session_id = detect_session(payload) or fallback_session
            walk(payload, session_id, str(path), session_store, seen_messages, seen_tools, seen_usage)

    stats["files"] += 1
    stats["lines"] += ok_lines
    stats["bad_lines"] += bad_lines


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_csv(out_dir: Path, filename: str, rows: list[dict[str, Any]], fieldnames: list[str]) -> Path:
    import csv

    target = out_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return target


def sessions_to_rows(session_store: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session_id, session in session_store.items():
        tool_calls = session.get("tool_calls", Counter())
        role_counts = session.get("role_counts", Counter())
        row = {
            "session_id": session_id,
            "source_file": session.get("source_file", ""),
            "message_count": session.get("message_count", 0),
            "tool_call_count": session.get("tool_call_count", 0),
            "bash_call_count": session.get("bash_call_count", 0),
            "editor_call_count": session.get("editor_call_count", 0),
            "unique_tools": ",".join(sorted(tool_calls.keys())),
            "unique_executables": ",".join(sorted(session.get("executables", Counter()).keys())),
            "first_action_seq": session.get("first_action_seq", ""),
            "missing_command_errors": sum(session.get("missing_commands", Counter()).values()),
            "missing_module_errors": sum(session.get("missing_modules", Counter()).values()),
            "install_attempts": sum(session.get("install_attempts", Counter()).values()),
            "import_count": sum(session.get("imports", Counter()).values()),
            "capability_probe_count": sum(session.get("capability_probes", Counter()).values()),
            "user_messages": role_counts.get("user", 0),
            "assistant_messages": role_counts.get("assistant", 0),
            "tool_messages": role_counts.get("tool", 0),
            "cwd": session.get("cwd", ""),
            "ds_session_id": session.get("ds_session_id", ""),
            "agent_preset_initial": session.get("agent_preset_initial", ""),
            "agent_preset_selected": session.get("agent_preset_selected", ""),
        }
        usage = session.get("usage", {})
        for key in USAGE_KEYS:
            row[key] = usage.get(key, "")
        rows.append(row)
    rows.sort(key=lambda r: (r["source_file"], r["session_id"]))
    return rows


def counter_rows(session_store: dict[str, dict[str, Any]], counter_name: str, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session_id, session in session_store.items():
        counter = session.get(counter_name, Counter())
        for item, count in sorted(counter.items()):
            rows.append(
                {
                    "session_id": session_id,
                    "source_file": session.get("source_file", ""),
                    label: item,
                    "count": count,
                }
            )
    rows.sort(key=lambda r: (r["source_file"], r["session_id"], r[label]))
    return rows


def print_report(stats: Counter, session_store: dict[str, dict[str, Any]]) -> None:
    print("\n========== JSONL Analysis Report ==========")
    print(f"files processed:          {stats.get('files', 0)}")
    print(f"valid JSON lines:         {stats.get('lines', 0)}")
    print(f"invalid JSON lines:       {stats.get('bad_lines', 0)}")
    print(f"sessions detected:        {len(session_store)}")

    all_tools: Counter = Counter()
    all_executables: Counter = Counter()
    all_missing_commands: Counter = Counter()
    all_missing_modules: Counter = Counter()
    all_imports: Counter = Counter()
    all_installs: Counter = Counter()
    all_probes: Counter = Counter()
    bash_commands = 0
    for session in session_store.values():
        all_tools.update(session.get("tool_calls", Counter()))
        all_executables.update(session.get("executables", Counter()))
        all_missing_commands.update(session.get("missing_commands", Counter()))
        all_missing_modules.update(session.get("missing_modules", Counter()))
        all_imports.update(session.get("imports", Counter()))
        all_installs.update(session.get("install_attempts", Counter()))
        all_probes.update(session.get("capability_probes", Counter()))
        bash_commands += session.get("bash_call_count", 0)

    print(f"bash tool calls:          {bash_commands}")

    def top(counter: Counter, title: str, n: int = 25) -> None:
        print(f"\n{title}")
        if not counter:
            print("  (none)")
            return
        for item, count in counter.most_common(n):
            print(f"  {count:6d}  {item}")

    top(all_tools, "Tool calls:")
    top(all_executables, "Executables seen in bash commands:")
    top(all_imports, "Python imports seen in bash commands:")
    try:
        stdlib = set(sys.stdlib_module_names)
    except AttributeError:
        stdlib = set()
    non_std_imports = Counter(
        {k: v for k, v in all_imports.items() if top_module(k) not in stdlib and k != "__future__"}
    )
    top(non_std_imports, "Python imports (non-stdlib top-levels may indicate package needs):")
    top(all_probes, "Capability probes (which / command -v / type):")
    top(all_missing_commands, "Missing shell commands observed:")
    top(all_missing_modules, "Missing Python modules observed:")
    top(all_installs, "Package install attempts by manager:")


def write_bash_commands(session_store: dict[str, dict[str, Any]], out_dir: Path) -> Path:
    target = out_dir / "bash_commands.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for session_id, session in sorted(session_store.items()):
            commands = session.get("bash_commands", [])
            if not commands:
                continue
            handle.write(f"\n===== session: {session_id} =====\n")
            handle.write(f"source: {session.get('source_file', '')}\n")
            for index, command in enumerate(commands, 1):
                handle.write(f"\n--- command #{index} ---\n")
                handle.write(command.rstrip())
                handle.write("\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze agent conversation JSONL exports for bash/tool usage.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=["."],
        help="JSONL files or directories containing .jsonl files",
    )
    parser.add_argument("-o", "--out", default=None, help="output directory (default: reports/<log-stem> for one file, reports/analysis for multiple)")
    parser.add_argument("--no-txt", action="store_true", help="do not write bash_commands.txt")
    parser.add_argument("-v", "--verbose", action="store_true", help="print each processed file")
    args = parser.parse_args(argv)

    files: list[Path] = []
    for raw in args.inputs:
        path = Path(raw)
        if path.is_file():
            if path.suffix.lower() == ".jsonl" or path.name.endswith(".jsonl"):
                files.append(path)
        elif path.is_dir():
            found = sorted([p for p in path.rglob("*.jsonl") if p.is_file()])
            if args.out:
                out_path = Path(args.out)
                if out_path.is_absolute():
                    files.extend(found)
                else:
                    # Don't re-ingest previous analysis outputs living under cwd.
                    exclude_dir = path.resolve() / out_path
                    files.extend(p for p in found if exclude_dir not in p.resolve().parents)
            else:
                files.extend(found)
        else:
            print(f"[warn] path does not exist: {path}", file=sys.stderr)

    if not files:
        print(
            "No .jsonl files found. Put DSH/agent exports under e.g. logs/phase1/, "
            "then run:  python3 analyze_logs.py logs/phase1",
            file=sys.stderr,
        )
        return 1

    print(f"Analyzing {len(files)} .jsonl file(s) ...")
    session_store: dict[str, dict[str, Any]] = {}
    stats: Counter = Counter()

    for path in files:
        if args.verbose:
            print(f"  {path}")
        process_jsonl_file(path, session_store, stats)

    # Drop empty fallback sessions (e.g. files that contained only `{}` lines).
    for sid in list(session_store.keys()):
        session = session_store[sid]
        if not session.get("message_count") and not session.get("tool_call_count") and not session.get("usage"):
            del session_store[sid]

    if args.out:
        out_dir = Path(args.out)
    elif len(files) == 1:
        out_dir = Path("reports") / files[0].stem
    else:
        out_dir = Path("reports/analysis")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = sessions_to_rows(session_store)
    write_csv(
        out_dir,
        "trajectory_summary.csv",
        summary_rows,
        fieldnames=[
            "session_id",
            "source_file",
            "message_count",
            "tool_call_count",
            "bash_call_count",
            "editor_call_count",
            "unique_tools",
            "unique_executables",
            "first_action_seq",
            "missing_command_errors",
            "missing_module_errors",
            "install_attempts",
            "import_count",
            "capability_probe_count",
            "user_messages",
            "assistant_messages",
            "tool_messages",
            "cwd",
            "ds_session_id",
            "agent_preset_initial",
            "agent_preset_selected",
            *USAGE_KEYS,
        ],
    )
    write_csv(out_dir, "tool_usage.csv", counter_rows(session_store, "tool_calls", "tool"), ["session_id", "source_file", "tool", "count"])
    write_csv(out_dir, "executable_usage.csv", counter_rows(session_store, "executables", "executable"), ["session_id", "source_file", "executable", "count"])
    write_csv(out_dir, "python_imports.csv", counter_rows(session_store, "imports", "module"), ["session_id", "source_file", "module", "count"])
    write_csv(out_dir, "capability_probes.csv", counter_rows(session_store, "capability_probes", "probe"), ["session_id", "source_file", "probe", "count"])
    write_csv(out_dir, "missing_commands.csv", counter_rows(session_store, "missing_commands", "missing_command"), ["session_id", "source_file", "missing_command", "count"])
    write_csv(out_dir, "missing_modules.csv", counter_rows(session_store, "missing_modules", "missing_module"), ["session_id", "source_file", "missing_module", "count"])
    write_csv(out_dir, "install_attempts.csv", counter_rows(session_store, "install_attempts", "package_manager"), ["session_id", "source_file", "package_manager", "count"])
    write_csv(out_dir, "install_packages.csv", counter_rows(session_store, "install_packages", "raw_packages"), ["session_id", "source_file", "raw_packages", "count"])

    if not args.no_txt:
        write_bash_commands(session_store, out_dir)

    print_report(stats, session_store)
    print(f"\nOutputs written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
