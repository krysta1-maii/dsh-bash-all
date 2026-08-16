#!/usr/bin/env python3
"""Build reproducible Bash-behavior statistics and the report artifact.

The script intentionally depends only on the Python standard library and the
repository's schema-tolerant ``analyze_logs.py`` parser.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import analyze_logs as base  # noqa: E402


GROUP_LABELS = {
    "step0_vibe": "Step 0 · vibe 项目",
    "step0_cases": "Step 0 · 12 用例",
    "double_step0": "双叉臂 · Step 0",
    "double_baseline": "双叉臂 · baseline",
}

TASK_LABELS = {
    "session-case-01": "C01 JSON 解析",
    "session-case-02": "C02 文件查找",
    "session-case-03": "C03 压缩包处理",
    "session-case-04": "C04 CSV 统计",
    "session-case-05": "C05 数值求解",
    "session-case-06": "C06 符号计算",
    "session-case-07": "C07 图表生成",
    "session-case-08": "C08 图像处理",
    "session-case-09": "C09 测试诊断",
    "session-case-10": "C10 C/C++ 构建",
    "session-case-11": "C11 文档转换",
    "session-case-12": "C12 本地 HTTP + JSON",
    "session-vibe-01": "P1 财务 Dashboard",
    "session-vibe-02": "P2 文档工程",
    "session-vibe-03": "P3 修仓库",
    "session-vibe-04": "P4 本地任务管理",
    "session-vibe-05": "P5 交互式物理仿真",
    "session-vibe-06": "P6 OCR 表格流水线",
    "session-vibe-07": "P7 本地网站爬取",
    "session-vibe-08": "P8 C++ 打包发布",
    "双叉臂测试-step0": "双叉臂 · Step 0",
    "双叉臂测试": "双叉臂 · baseline",
}

INSPECTION_EXES = {
    "pwd",
    "ls",
    "find",
    "cat",
    "head",
    "tail",
    "sed",
    "grep",
    "rg",
    "wc",
    "file",
    "stat",
    "git",
}

VALIDATION_EXES = {
    "pytest",
    "ctest",
    "chafa",
    "tesseract",
    "identify",
    "pdfinfo",
    "pdftotext",
    "pdftoppm",
    "google-chrome",
    "file",
}

PROCESS_EXES = {
    "google-chrome",
    "sleep",
    "kill",
    "pkill",
    "timeout",
    "curl",
    "wget",
}


def relative_log_files() -> list[Path]:
    return sorted(p.relative_to(ROOT) for p in (ROOT / "logs").rglob("*.jsonl"))


def classify_group(source_file: str) -> str:
    normalized = source_file.replace("\\", "/")
    if "/step0-vibe/" in normalized:
        return "step0_vibe"
    if "/cases/step0/" in normalized:
        return "step0_cases"
    if normalized.endswith("双叉臂测试-step0.jsonl"):
        return "double_step0"
    return "double_baseline"


def task_label(source_file: str) -> str:
    return TASK_LABELS.get(Path(source_file).stem, Path(source_file).stem)


def request_metadata(path: Path) -> dict[str, Any]:
    """Read the first formal request header without ingesting its tool schemas."""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "request/header":
                continue
            header = record.get("data", {}).get("header", {})
            config = header.get("config", {})
            tools = header.get("tools", [])
            return {
                "model": config.get("model", "unknown"),
                "reasoning_effort": config.get("reasoningEffort", "unknown"),
                "visible_tools": [tool.get("name") for tool in tools if tool.get("name")],
            }
    return {"model": "unknown", "reasoning_effort": "unknown", "visible_tools": []}


def protocol_tool_stats(paths: list[Path]) -> dict[str, Any]:
    calls: dict[str, tuple[str, str]] = {}
    results: dict[str, bool] = {}
    result_exit_codes: dict[str, int] = {}
    for path in paths:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "tool/call":
                    data = record.get("data", {})
                    if data.get("callId") and data.get("name"):
                        calls[data["callId"]] = (data["name"], str(path))
                elif record.get("type") == "tool/result":
                    message = record.get("data", {}).get("message", {})
                    for block in message.get("content", []):
                        if block.get("type") == "tool-result" and block.get("toolCallId"):
                            call_id = block["toolCallId"]
                            results[call_id] = bool(block.get("isError"))
                            matches = re.findall(
                                r"\[exit code:\s*(-?\d+)\]",
                                json.dumps(block, ensure_ascii=False),
                            )
                            if matches:
                                result_exit_codes[call_id] = int(matches[-1])
    errors = Counter(
        calls[call_id][0]
        for call_id, is_error in results.items()
        if is_error and call_id in calls
    )
    nonzero_bash_by_source: Counter[str] = Counter()
    nonzero_bash_codes: Counter[int] = Counter()
    for call_id, exit_code in result_exit_codes.items():
        if call_id not in calls or calls[call_id][0] != "bash" or exit_code == 0:
            continue
        nonzero_bash_by_source[calls[call_id][1]] += 1
        nonzero_bash_codes[exit_code] += 1
    return {
        "formal_calls": len(calls),
        "formal_results": len(results),
        "matched_call_results": len(set(calls) & set(results)),
        "transport_errors_by_tool": dict(errors),
        "nonzero_bash_results": sum(nonzero_bash_codes.values()),
        "nonzero_bash_exit_codes": dict(nonzero_bash_codes),
        "nonzero_bash_by_source": dict(nonzero_bash_by_source),
    }


def shell_operators(command: str) -> dict[str, bool]:
    """Approximate top-level Bash operators while respecting quotes/parens."""
    heredoc = bool(re.search(r"<<-?\s*(?:['\"][^'\"]+['\"]|[A-Za-z_]\w*)", command))
    masked = base.mask_heredocs(command)
    found = {
        "pipeline": False,
        "logical_chain": False,
        "sequential": False,
        "background": False,
        "redirection": heredoc,
        "heredoc": heredoc,
        "command_substitution": "$(" in masked,
    }
    quote: str | None = None
    escaped = False
    depth = 0
    i = 0
    while i < len(masked):
        ch = masked[i]
        nxt = masked[i + 1] if i + 1 < len(masked) else ""
        if escaped:
            escaped = False
            i += 1
            continue
        if quote is not None:
            if ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        if ch == "\\":
            escaped = True
            i += 1
            continue
        if ch == "$" and nxt == "(":
            depth += 1
            i += 2
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")" and depth:
            depth -= 1
            i += 1
            continue
        if depth:
            i += 1
            continue
        if ch == "&" and nxt == "&":
            found["logical_chain"] = True
            i += 2
            continue
        if ch == "|" and nxt == "|":
            found["logical_chain"] = True
            i += 2
            continue
        if ch == "|":
            found["pipeline"] = True
            i += 2 if nxt == "&" else 1
            continue
        if ch == ";" or ch == "\n":
            found["sequential"] = True
            i += 1
            continue
        if ch == "&":
            previous = masked[i - 1] if i else ""
            if previous not in "<>":
                found["background"] = True
            i += 1
            continue
        if ch in "<>":
            found["redirection"] = True
        i += 1
    return found


def write_method(command: str) -> set[str]:
    methods: set[str] = set()
    low = command.lower()
    if "sed -i" in low or "sed --in-place" in low:
        methods.add("sed 原地修改")
    if re.search(r"\btee\b", low):
        methods.add("tee 写入")
    if re.search(r"\bcat\b[^\n]*(?:>|>>)\s*(?!&|/dev/null)", low) and "<<" in low:
        methods.add("cat + heredoc")
    if re.search(r"\b(?:echo|printf)\b[^\n;]*(?:>|>>)\s*(?!&|/dev/null)", low):
        methods.add("echo/printf 重定向")
    masked = base.mask_heredocs(low)
    if re.search(r"(?<!\d)>{1,2}\s*(?!&\d|/dev/null)", masked):
        methods.add("Shell 输出重定向")
    if any(
        token in low
        for token in (".write_text(", ".write_bytes(", ".save(", "json.dump(", "csv.writer(")
    ):
        methods.add("Python 文件 API")
    if re.search(r"\bopen\s*\([^\n)]*,\s*['\"][wax+]", low):
        methods.add("Python 文件 API")
    if set(base.extract_executables(command)) & {"cp", "mv", "touch", "mkdir", "rm", "chmod"}:
        methods.add("文件系统命令")
    if set(base.extract_executables(command)) & {"make", "ninja", "cpack"} or re.search(
        r"\b(?:cmake\s+--build|pandoc\b[^\n]*(?:-o|--output))\b", low
    ):
        methods.add("构建 / 生成命令")
    return methods


def executed_install_attempts(command: str) -> list[tuple[str, str]]:
    """Count install syntax only in executed shell text, not heredoc payloads."""
    return base.extract_installs(base.mask_heredocs(command))


def explicit_validation(command: str) -> bool:
    exes = set(base.extract_executables(command))
    low = command.lower()
    if exes & VALIDATION_EXES:
        return True
    return bool(
        re.search(
            r"(?:\bpytest\b|\bunittest\b|\bctest\b|\bselftest\b|"
            r"\bverify\w*\b|\bevaluat\w*\b|\bassert\b|\btest(?:s|ing)?\b|npm\s+(?:run\s+)?test)",
            low,
        )
    )


def command_features(command: str) -> set[str]:
    exes = base.extract_executables(command)
    exe_set = set(exes)
    operators = shell_operators(command)
    segments = [segment for segment in base._quote_aware_split(command) if segment.strip()]
    features: set[str] = set()
    if len(segments) > 1:
        features.add("复合调用（≥2 个命令段）")
    if operators["logical_chain"]:
        features.add("条件链（&& / ||）")
    if operators["pipeline"]:
        features.add("管道（|）")
    if operators["redirection"]:
        features.add("重定向 / heredoc")
    if re.search(
        r"\bpython(?:3(?:\.\d+)?)?\b[^\n;|&]*<<-?\s*(?:['\"][^'\"]+['\"]|[A-Za-z_]\w*)",
        command,
    ):
        features.add("内联 Python heredoc")
    if operators["background"] or exe_set & PROCESS_EXES:
        features.add("进程 / 服务编排")
    if base.extract_capability_probes(command) or "importlib.util.find_spec" in command:
        features.add("能力探测")
    if executed_install_attempts(command) or re.search(
        r"\b(?:venv|apt-get\s+download|dpkg-deb)\b", base.mask_heredocs(command)
    ):
        features.add("依赖恢复")
    if any(exe.startswith("python") for exe in exes):
        features.add("Python 执行")
    if explicit_validation(command):
        features.add("显式验证 / 视觉检查")
    if write_method(command):
        features.add("通过 Bash 写/改文件")
    return features


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def rounded_share(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def main() -> int:
    files = relative_log_files()
    protocol = protocol_tool_stats(files)
    store: dict[str, dict[str, Any]] = {}
    stats: Counter[str] = Counter()
    metadata_by_file: dict[str, dict[str, Any]] = {}
    for relative_path in files:
        metadata_by_file[str(relative_path)] = request_metadata(relative_path)
        base.process_jsonl_file(relative_path, store, stats)

    sessions: list[dict[str, Any]] = []
    feature_calls: Counter[str] = Counter()
    feature_sessions: defaultdict[str, set[str]] = defaultdict(set)
    method_calls: Counter[str] = Counter()
    method_sessions: defaultdict[str, set[str]] = defaultdict(set)
    executable_calls: Counter[str] = Counter()
    executable_sessions: defaultdict[str, set[str]] = defaultdict(set)
    tool_calls: Counter[str] = Counter()
    tool_sessions: defaultdict[str, set[str]] = defaultdict(set)
    install_managers: Counter[str] = Counter()
    install_classes: Counter[str] = Counter()
    tmp_calls = 0
    tmp_sessions: set[str] = set()

    for session_id, session in sorted(store.items(), key=lambda item: item[1].get("source_file", "")):
        source_file = session.get("source_file", "")
        meta = metadata_by_file.get(source_file, {})
        commands = session.get("bash_commands", [])
        group = classify_group(source_file)
        first_write_index = next((i for i, command in enumerate(commands) if write_method(command)), None)
        prior_inspection = False
        post_write_validation = False
        if first_write_index is not None:
            prior_inspection = any(
                set(base.extract_executables(command)) & INSPECTION_EXES
                for command in commands[:first_write_index]
            )
            post_write_validation = any(explicit_validation(command) for command in commands[first_write_index:])

        for tool, count in session.get("tool_calls", Counter()).items():
            tool_calls[tool] += count
            tool_sessions[tool].add(session_id)
        for exe, count in session.get("executables", Counter()).items():
            executable_calls[exe] += count
            executable_sessions[exe].add(session_id)
        for command in commands:
            if "/tmp" in command:
                tmp_calls += 1
                tmp_sessions.add(session_id)
            for manager, _ in executed_install_attempts(command):
                install_managers[manager] += 1
                masked_command = base.mask_heredocs(command)
                if manager == "pip" and (
                    "--target" in masked_command
                    or re.search(r"\S*(?:venv|\.build-venv)\S*/bin/pip\b", masked_command)
                ):
                    install_classes["isolated_pip_success"] += 1
                elif manager == "pip":
                    install_classes["global_or_user_pip_failure"] += 1
                elif manager == "apt":
                    install_classes["apt_install_failure"] += 1
            for feature in command_features(command):
                feature_calls[feature] += 1
                feature_sessions[feature].add(session_id)
            for method in write_method(command):
                method_calls[method] += 1
                method_sessions[method].add(session_id)

        missing_count = sum(session.get("missing_commands", Counter()).values()) + sum(
            session.get("missing_modules", Counter()).values()
        )
        sessions.append(
            {
                "session_id": session_id,
                "source_file": source_file,
                "task": task_label(source_file),
                "group": group,
                "group_label": GROUP_LABELS[group],
                "model": meta.get("model", "unknown"),
                "reasoning_effort": meta.get("reasoning_effort", "unknown"),
                "visible_tools": ",".join(meta.get("visible_tools", [])),
                "message_count": session.get("message_count", 0),
                "tool_calls": session.get("tool_call_count", 0),
                "bash_calls": session.get("bash_call_count", 0),
                "editor_calls": session.get("editor_call_count", 0),
                "probe_events": sum(session.get("capability_probes", Counter()).values()),
                "missing_signals": missing_count,
                "install_attempts": sum(
                    len(executed_install_attempts(command)) for command in commands
                ),
                "nonzero_bash_results": protocol["nonzero_bash_by_source"].get(source_file, 0),
                "first_call_inspects": bool(set(base.extract_executables(commands[0])) & INSPECTION_EXES)
                and not bool(write_method(commands[0]))
                if commands
                else False,
                "read_before_write": prior_inspection if first_write_index is not None else None,
                "post_write_validation": post_write_validation if first_write_index is not None else None,
                "bash_write_calls": sum(bool(write_method(command)) for command in commands),
                "explicit_validation_calls": sum(explicit_validation(command) for command in commands),
            }
        )

    total_sessions = len(sessions)
    total_tool_calls = sum(tool_calls.values())
    total_bash_calls = tool_calls.get("bash", 0)
    bash_counts = sorted(int(row["bash_calls"]) for row in sessions)
    top_sessions = sorted(sessions, key=lambda row: int(row["bash_calls"]), reverse=True)
    top5_calls = sum(int(row["bash_calls"]) for row in top_sessions[:5])

    tool_rows = [
        {
            "tool": tool,
            "calls": count,
            "sessions": len(tool_sessions[tool]),
            "call_share": rounded_share(count, total_tool_calls),
        }
        for tool, count in tool_calls.most_common()
    ]
    executable_rows = [
        {
            "executable": exe,
            "calls": executable_calls[exe],
            "sessions": len(executable_sessions[exe]),
            "session_share": rounded_share(len(executable_sessions[exe]), total_sessions),
        }
        for exe in sorted(executable_calls, key=lambda name: (-len(executable_sessions[name]), -executable_calls[name], name))
    ]
    feature_rows = [
        {
            "feature": feature,
            "calls": feature_calls[feature],
            "call_share": rounded_share(feature_calls[feature], total_bash_calls),
            "sessions": len(feature_sessions[feature]),
            "session_share": rounded_share(len(feature_sessions[feature]), total_sessions),
        }
        for feature in sorted(feature_calls, key=lambda name: (-feature_calls[name], name))
    ]
    method_rows = [
        {
            "method": method,
            "calls": method_calls[method],
            "sessions": len(method_sessions[method]),
        }
        for method in sorted(method_calls, key=lambda name: (-method_calls[name], name))
    ]

    groups: list[dict[str, Any]] = []
    for group in GROUP_LABELS:
        rows = [row for row in sessions if row["group"] == group]
        values = sorted(int(row["bash_calls"]) for row in rows)
        groups.append(
            {
                "group": GROUP_LABELS[group],
                "sessions": len(rows),
                "bash_calls": sum(values),
                "median_bash_calls": statistics.median(values),
                "probe_events": sum(int(row["probe_events"]) for row in rows),
                "missing_signals": sum(int(row["missing_signals"]) for row in rows),
                "install_attempts": sum(int(row["install_attempts"]) for row in rows),
                "nonzero_bash_results": sum(int(row["nonzero_bash_results"]) for row in rows),
                "nonzero_bash_rate": rounded_share(
                    sum(int(row["nonzero_bash_results"]) for row in rows),
                    sum(int(row["bash_calls"]) for row in rows),
                ),
                "editor_calls": sum(int(row["editor_calls"]) for row in rows),
            }
        )

    first_inspect_count = sum(bool(row["first_call_inspects"]) for row in sessions)
    writable_sessions = [row for row in sessions if row["read_before_write"] is not None]
    read_before_write_count = sum(bool(row["read_before_write"]) for row in writable_sessions)
    post_write_validation_count = sum(bool(row["post_write_validation"]) for row in writable_sessions)
    missing_sessions = sum(int(row["missing_signals"]) > 0 for row in sessions)
    installing_sessions = sum(int(row["install_attempts"]) > 0 for row in sessions)

    baseline = next(row for row in sessions if row["group"] == "double_baseline")
    step0 = next(row for row in sessions if row["group"] == "double_step0")
    ab_rows = [
        {"metric": "Bash 调用", "baseline": baseline["bash_calls"], "step0": step0["bash_calls"], "change": "+52.2%"},
        {"metric": "最终非零 Bash", "baseline": baseline["nonzero_bash_results"], "step0": step0["nonzero_bash_results"], "change": "-1"},
        {"metric": "主动探测目标", "baseline": baseline["probe_events"], "step0": step0["probe_events"], "change": "-38.5%"},
        {"metric": "缺失信号", "baseline": baseline["missing_signals"], "step0": step0["missing_signals"], "change": "-83.3%"},
        {"metric": "安装尝试", "baseline": baseline["install_attempts"], "step0": step0["install_attempts"], "change": "-40.0%"},
    ]
    step01_rows = [
        {
            "priority": "P0",
            "domain": "Python 入口、测试与轻量胶水",
            "delivery": "默认 core",
            "apt_packages": "python-is-python3; python3-venv; python3-pytest; python3-websocket; zip; unzip; pngcheck",
            "evidence": "python3 覆盖 22/22；python 别名缺 2 次；pytest 缺 3 次；CDP websocket 曾运行时自装",
        },
        {
            "priority": "P0",
            "domain": "文档、PDF 与字体",
            "delivery": "docs profile；单镜像时纳入",
            "apt_packages": "pandoc; poppler-utils; poppler-data; ghostscript; fontconfig; fonts-noto-cjk; python3-reportlab; python3-pymupdf; python3-svglib; python3-fonttools; weasyprint",
            "evidence": "P2+C11 共 161/650 次 Bash；缺 pandoc/pdfinfo/reportlab/fontTools/rlPyCairo，并出现 /tmp poppler 自举",
        },
        {
            "priority": "P0",
            "domain": "原生构建与发布",
            "delivery": "build profile；单镜像时纳入",
            "apt_packages": "build-essential; cmake; ninja-build; pkgconf",
            "evidence": "P8 共 55 次 Bash；缺 cmake/ctest/zip/unzip，并通过 apt-download/dpkg-deb 自建工具链",
        },
        {
            "priority": "P1",
            "domain": "科学计算、数据与绘图",
            "delivery": "data profile；按任务挂载",
            "apt_packages": "python3-scipy; python3-matplotlib; python3-pandas",
            "evidence": "scipy 缺 1 次；matplotlib 缺 3 次/2 会话；pandas 缺 2 次/2 会话；存在 stdlib/Pillow 回退",
        },
        {
            "priority": "P2",
            "domain": "通用 CLI、浏览器框架、CV 与 Web 框架",
            "delivery": "先实验或暂缓",
            "apt_packages": "不新增；另设 browser/docs-heavy profile 时再评估",
            "evidence": "rg/jq/fd/awk/curl/wget 全部 0 次；Playwright/OpenCV/Flask/FastAPI/Uvicorn 只是零星探测且均有现成回退",
        },
    ]

    model_counts = Counter(row["model"] for row in sessions)
    interface_counts = Counter(row["visible_tools"] for row in sessions)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": len(files),
        "valid_json_lines": stats.get("lines", 0),
        "invalid_json_lines": stats.get("bad_lines", 0),
        "sessions": total_sessions,
        "models": dict(model_counts),
        "interfaces": dict(interface_counts),
        "protocol": protocol,
        "tool_calls": total_tool_calls,
        "bash_calls": total_bash_calls,
        "bash_share": rounded_share(total_bash_calls, total_tool_calls),
        "bash_calls_median": statistics.median(bash_counts),
        "bash_calls_mean": round(statistics.mean(bash_counts), 2),
        "bash_calls_min": min(bash_counts),
        "bash_calls_max": max(bash_counts),
        "top5_bash_call_share": rounded_share(top5_calls, total_bash_calls),
        "first_call_inspection_sessions": first_inspect_count,
        "sessions_with_detected_write": len(writable_sessions),
        "read_before_write_sessions": read_before_write_count,
        "post_write_validation_sessions": post_write_validation_count,
        "sessions_with_missing_signals": missing_sessions,
        "sessions_with_install_attempts": installing_sessions,
        "total_missing_signals": sum(int(row["missing_signals"]) for row in sessions),
        "total_install_attempts": sum(int(row["install_attempts"]) for row in sessions),
        "install_managers": dict(install_managers),
        "install_outcomes": dict(install_classes),
        "tmp_path_calls": tmp_calls,
        "tmp_path_sessions": len(tmp_sessions),
        "tool_usage": tool_rows,
        "top_executables": executable_rows[:30],
        "command_features": feature_rows,
        "write_methods": method_rows,
        "groups": groups,
        "ab_comparison": ab_rows,
        "step01_package_bundles": step01_rows,
    }

    write_csv(
        OUT / "session_behavior.csv",
        sessions,
        list(sessions[0].keys()),
    )
    write_csv(OUT / "executable_coverage.csv", executable_rows, list(executable_rows[0].keys()))
    write_csv(OUT / "command_features.csv", feature_rows, list(feature_rows[0].keys()))
    write_csv(OUT / "write_methods.csv", method_rows, list(method_rows[0].keys()))
    write_csv(OUT / "group_summary.csv", groups, list(groups[0].keys()))
    (OUT / "behavior_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    chart_features = [
        dict(row)
        for row in feature_rows
        if row["feature"]
        in {
            "复合调用（≥2 个命令段）",
            "条件链（&& / ||）",
            "管道（|）",
            "重定向 / heredoc",
            "内联 Python heredoc",
            "能力探测",
            "依赖恢复",
            "进程 / 服务编排",
        }
    ]
    feature_labels = {
        "复合调用（≥2 个命令段）": "复合调用",
        "条件链（&& / ||）": "条件链",
        "管道（|）": "管道",
        "重定向 / heredoc": "重定向/heredoc",
        "内联 Python heredoc": "内联 Python",
        "能力探测": "能力探测",
        "依赖恢复": "依赖恢复",
        "进程 / 服务编排": "进程编排",
    }
    for row in chart_features:
        row["display_feature"] = feature_labels[row["feature"]]
    chart_features.sort(key=lambda row: row["call_share"], reverse=True)
    high_cost_rows = [
        {
            "task": row["task"],
            "bash_calls": row["bash_calls"],
            "group": row["group_label"],
            "missing_signals": row["missing_signals"],
            "install_attempts": row["install_attempts"],
        }
        for row in top_sessions[:10]
    ]

    write_csv(OUT / "tool_usage_summary.csv", tool_rows, list(tool_rows[0].keys()))
    write_csv(
        OUT / "command_composition.csv",
        chart_features,
        list(chart_features[0].keys()),
    )
    write_csv(
        OUT / "high_cost_sessions.csv",
        high_cost_rows,
        list(high_cost_rows[0].keys()),
    )
    write_csv(OUT / "ab_comparison.csv", ab_rows, list(ab_rows[0].keys()))
    write_csv(
        OUT / "step01_package_bundles.csv",
        step01_rows,
        list(step01_rows[0].keys()),
    )

    source_raw = {"id": "raw_logs", "label": "22 份 DSH JSONL 对话导出", "path": "logs"}
    source_metrics = {
        "id": "behavior_metrics",
        "label": "Bash 行为统计（由仓库解析器复算）",
        "path": "reports/bash-behavior-analysis/behavior_metrics.json",
    }
    source_case_report = {
        "id": "case_report",
        "label": "12 用例现有汇总",
        "path": "reports/cases-step0-summary.md",
    }
    source_vibe_report = {
        "id": "vibe_report",
        "label": "8 个 vibe 项目现有汇总",
        "path": "reports/step0-vibe-summary.md",
    }
    source_ab_report = {
        "id": "ab_report",
        "label": "双叉臂 baseline / Step 0 现有对比",
        "path": "reports/step0-vs-baseline.md",
    }
    generated_at = summary["generated_at"]

    def sql_source(source_id: str, label: str, path: str, sql: str) -> dict[str, Any]:
        return {
            "id": source_id,
            "label": label,
            "path": path,
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "description": label,
                "sql": sql,
                "executed_at": generated_at,
                "tables_used": [path],
            },
        }

    source_tool_mix = sql_source(
        "tool_mix_query",
        "Formal tool calls by tool",
        "reports/bash-behavior-analysis/tool_usage_summary.csv",
        "SELECT tool, calls, sessions, call_share FROM read_csv_auto('reports/bash-behavior-analysis/tool_usage_summary.csv', header=true) ORDER BY calls DESC",
    )
    source_executable_coverage = sql_source(
        "executable_coverage_query",
        "Executable counts and session coverage",
        "reports/bash-behavior-analysis/executable_coverage.csv",
        "SELECT executable, calls, sessions, session_share FROM read_csv_auto('reports/bash-behavior-analysis/executable_coverage.csv', header=true) ORDER BY sessions DESC, calls DESC LIMIT 12",
    )
    source_composition = sql_source(
        "command_composition_query",
        "Observable Bash composition features",
        "reports/bash-behavior-analysis/command_composition.csv",
        "SELECT feature, display_feature, calls, call_share, sessions, session_share FROM read_csv_auto('reports/bash-behavior-analysis/command_composition.csv', header=true) ORDER BY call_share DESC",
    )
    source_high_cost = sql_source(
        "high_cost_query",
        "Bash calls for the ten highest-cost sessions",
        "reports/bash-behavior-analysis/high_cost_sessions.csv",
        "SELECT task, bash_calls, \"group\", missing_signals, install_attempts FROM read_csv_auto('reports/bash-behavior-analysis/high_cost_sessions.csv', header=true) ORDER BY bash_calls DESC LIMIT 10",
    )
    source_groups = sql_source(
        "group_summary_query",
        "Log group behavior totals",
        "reports/bash-behavior-analysis/group_summary.csv",
        "SELECT \"group\", sessions, bash_calls, median_bash_calls, probe_events, missing_signals, install_attempts, nonzero_bash_results, nonzero_bash_rate, editor_calls FROM read_csv_auto('reports/bash-behavior-analysis/group_summary.csv', header=true)",
    )
    source_ab = sql_source(
        "ab_comparison_query",
        "Double-wishbone baseline and Step 0 comparison",
        "reports/bash-behavior-analysis/ab_comparison.csv",
        "SELECT metric, baseline, step0, change FROM read_csv_auto('reports/bash-behavior-analysis/ab_comparison.csv', header=true)",
    )
    source_step01 = sql_source(
        "step01_package_query",
        "Step 0.1 package-layer decision matrix",
        "reports/bash-behavior-analysis/step01_package_bundles.csv",
        "SELECT priority, domain, delivery, apt_packages, evidence FROM read_csv_auto('reports/bash-behavior-analysis/step01_package_bundles.csv', header=true) ORDER BY priority, domain",
    )
    source_ubuntu_resolute = {
        "id": "ubuntu_resolute_packages",
        "label": "Ubuntu 26.04 (Resolute) package index",
        "href": "https://packages.ubuntu.com/resolute/",
    }
    source_pep668 = {
        "id": "pep668",
        "label": "PEP 668: externally managed Python environments",
        "href": "https://peps.python.org/pep-0668/",
    }
    source_python_venv = {
        "id": "python_venv",
        "label": "Python venv documentation",
        "href": "https://docs.python.org/3/library/venv.html",
    }
    artifact_sources = [
        source_raw,
        source_metrics,
        source_case_report,
        source_vibe_report,
        source_ab_report,
        source_tool_mix,
        source_executable_coverage,
        source_composition,
        source_high_cost,
        source_groups,
        source_ab,
        source_step01,
        source_ubuntu_resolute,
        source_pep668,
        source_python_venv,
    ]

    manifest = {
        "version": 1,
        "surface": "report",
        "title": "模型如何使用 Bash",
        "description": "22 个 DSH 会话中的命令倾向、常用工具与可观察策略。",
        "generatedAt": generated_at,
        "charts": [
            {
                "id": "tool_mix_chart",
                "title": "模型可见工具的实际调用",
                "subtitle": f"{total_tool_calls} 次正式 tool/call；按工具汇总",
                "type": "bar",
                "dataset": "tool_mix",
                "sourceId": "tool_mix_query",
                "encodings": {
                    "x": {"field": "tool", "type": "nominal", "label": "工具"},
                    "y": {"field": "calls", "type": "quantitative", "label": "调用次数"},
                    "tooltip": [
                        {"field": "sessions", "type": "quantitative", "label": "覆盖会话"},
                        {"field": "call_share", "type": "quantitative", "label": "调用占比", "format": "percent"},
                    ],
                },
                "layout": "full",
            },
            {
                "id": "executable_coverage_chart",
                "title": "高覆盖率 Bash 可执行程序",
                "subtitle": "按覆盖会话数排序；调用次数保留在提示信息中",
                "type": "bar",
                "dataset": "top_executable_coverage",
                "sourceId": "executable_coverage_query",
                "encodings": {
                    "x": {"field": "executable", "type": "nominal", "label": "可执行程序"},
                    "y": {"field": "sessions", "type": "quantitative", "label": "覆盖会话数"},
                    "tooltip": [
                        {"field": "calls", "type": "quantitative", "label": "命令段计数"},
                        {"field": "session_share", "type": "quantitative", "label": "会话覆盖率", "format": "percent"},
                    ],
                },
                "layout": "full",
            },
            {
                "id": "composition_chart",
                "title": "Bash 调用的组合形态",
                "subtitle": "分母为 650 次 Bash 调用；特征可重叠",
                "type": "bar",
                "dataset": "command_composition",
                "sourceId": "command_composition_query",
                "valueFormat": "percent",
                "encodings": {
                    "x": {"field": "display_feature", "type": "nominal", "label": "可观察特征"},
                    "y": {"field": "call_share", "type": "quantitative", "label": "Bash 调用占比", "format": "percent"},
                    "tooltip": [
                        {"field": "feature", "type": "nominal", "label": "完整定义"},
                        {"field": "calls", "type": "quantitative", "label": "调用数"},
                        {"field": "sessions", "type": "quantitative", "label": "覆盖会话"},
                    ],
                },
                "layout": "full",
            },
            {
                "id": "cost_concentration_chart",
                "title": "Bash 调用最多的 10 个会话",
                "subtitle": f"中位数 {summary['bash_calls_median']:.1f} 次；最高 {summary['bash_calls_max']} 次",
                "type": "bar",
                "dataset": "high_cost_sessions",
                "sourceId": "high_cost_query",
                "encodings": {
                    "x": {"field": "task", "type": "nominal", "label": "会话 / 任务"},
                    "y": {"field": "bash_calls", "type": "quantitative", "label": "Bash 调用次数"},
                    "tooltip": [
                        {"field": "group", "type": "nominal", "label": "分组"},
                        {"field": "missing_signals", "type": "quantitative", "label": "缺失信号"},
                        {"field": "install_attempts", "type": "quantitative", "label": "安装尝试"},
                    ],
                },
                "layout": "full",
            },
        ],
        "tables": [
            {
                "id": "group_table",
                "title": "日志分组与行为总量",
                "subtitle": "四组任务规模不同，横向对比仅用于描述样本构成",
                "dataset": "group_summary",
                "sourceId": "group_summary_query",
                "defaultSort": {"field": "bash_calls", "direction": "desc"},
                "columns": [
                    {"field": "group", "label": "分组", "type": "text"},
                    {"field": "sessions", "label": "会话"},
                    {"field": "bash_calls", "label": "Bash 调用"},
                    {"field": "median_bash_calls", "label": "会话中位数"},
                    {"field": "probe_events", "label": "探测目标"},
                    {"field": "missing_signals", "label": "缺失信号"},
                    {"field": "install_attempts", "label": "安装尝试"},
                    {"field": "nonzero_bash_rate", "label": "最终非零率", "format": "percent"},
                ],
                "layout": "full",
            },
            {
                "id": "ab_table",
                "title": "双叉臂任务：baseline 与 Step 0",
                "subtitle": "同一提示词与模型；Step 0 增加 pip、Pillow、chafa、ImageMagick 与 tesseract",
                "dataset": "ab_comparison",
                "sourceId": "ab_comparison_query",
                "defaultSort": {"field": "metric", "direction": "asc"},
                "columns": [
                    {"field": "metric", "label": "指标", "type": "text"},
                    {"field": "baseline", "label": "baseline"},
                    {"field": "step0", "label": "Step 0"},
                    {"field": "change", "label": "变化", "type": "text"},
                ],
                "layout": "full",
            },
            {
                "id": "step01_package_table",
                "title": "Step 0.1 包体分层决策",
                "subtitle": "Ubuntu 26.04 apt 包名；优先级来自 22 个会话中的恢复成本、复用面与替代路径",
                "dataset": "step01_package_bundles",
                "sourceId": "step01_package_query",
                "defaultSort": {"field": "priority", "direction": "asc"},
                "columns": [
                    {"field": "priority", "label": "优先级", "type": "text"},
                    {"field": "domain", "label": "领域", "type": "text"},
                    {"field": "delivery", "label": "交付层", "type": "text"},
                    {"field": "apt_packages", "label": "建议 apt 包", "type": "text"},
                    {"field": "evidence", "label": "日志证据", "type": "text"},
                ],
                "layout": "full",
            },
        ],
        "sources": artifact_sources,
        "blocks": [
            {"id": "title", "type": "markdown", "body": "# 模型如何使用 Bash", "layout": "full"},
            {
                "id": "executive_summary",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## Executive Summary\n\n"
                    f"- **Bash 几乎就是唯一动作平面。** 22 个会话共有 {total_tool_calls} 次正式工具调用，其中 Bash {total_bash_calls} 次（{summary['bash_share']:.1%}）；编辑器仅 6 次，视觉激活 2 次。\n"
                    f"- **Python 是 Bash 背后的默认能力层。** `python3` 出现在全部 22 个会话、共 {executable_calls['python3']} 个命令段；模型用 Shell 负责编排，再用 Python 标准库、NumPy、Pillow 等完成数据处理、生成与验证。\n"
                    f"- **可观察流程高度稳定：先看环境，再做事，再验证。** {first_inspect_count}/22 个首个 Bash 调用包含目录或文件检查；在检测到写入的 {len(writable_sessions)} 个会话中，{read_before_write_count} 个先读后写，{post_write_validation_count} 个在写入当次或之后出现显式测试或视觉/格式检查。\n"
                    f"- **Step 0.1 应做分层包体，而不是继续横向堆 CLI。** {missing_sessions} 个会话出现缺命令/缺模块信号，{installing_sessions} 个尝试安装或自建环境；调用最多的 5 个会话占全部 Bash 调用的 {summary['top5_bash_call_share']:.1%}。建议默认提供轻量 Core，并叠加 docs、build、data 领域层；若只能维护一个镜像，优先 Core + docs + build。"
                ),
            },
            {
                "id": "scope",
                "type": "markdown",
                "sourceId": "raw_logs",
                "layout": "full",
                "body": (
                    "## 样本与口径\n\n"
                    f"本报告重新解析 `logs/` 中 {len(files)} 份 JSONL，共 {stats.get('lines', 0):,} 条有效 JSON、0 条坏行。样本包含 21 个 `deepseek-v4-pro` 会话和 1 个 `deepseek-v4-flash` 会话，均为 `max` reasoning effort。20 个 case/vibe 会话只暴露 `bash + str_replace_editor`；两次双叉臂会话还暴露 `vision_toolkit_activate`。\n\n"
                    "只统计正式 `tool/call` / `tool/result`，跳过流式 chunk。一个 Bash 调用可包含多个由管道、分号或逻辑运算符连接的命令段，因此“可执行程序计数”不是工具调用数。以下结论描述这批任务上的可观察行为，不等同于模型在所有任务上的固有偏好。"
                    " 安装统计会先屏蔽 heredoc 正文，避免把生成脚本中的 `pip install` 字符串当成真实执行；Python import 仍只是命令文本信号，不代表模块成功导入。"
                ),
            },
            {"id": "group_table_block", "type": "table", "tableId": "group_table", "layout": "full"},
            {
                "id": "bash_dominance",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## Bash 已成为事实上的统一 ABI\n\n"
                    "**模型没有把编辑器当作主要编辑通道。** `str_replace_editor` 只在 2 个会话中出现 6 次：5 次因 schema、路径或 range 错误失败，唯一成功的一次只是 `view`，成功编辑为 0；两次视觉激活也都因 Skill 未加载而失败。真正的创建与修改通常由 `cat` heredoc、Python 文件 API、重定向或 `sed -i` 完成。Bash 因而同时承担发现、编辑、执行、验证和进程管理。\n\n"
                    "这支持仓库的核心观察：在当前 harness 下，稳定的小工具面并没有限制任务覆盖；但也意味着 Shell 安全、输出约束和可写路径会直接影响几乎全部 Agent 行为。"
                ),
            },
            {"id": "tool_mix_block", "type": "chart", "chartId": "tool_mix_chart", "layout": "full"},
            {
                "id": "python_default",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## Shell 负责组合，Python 负责实现\n\n"
                    f"**覆盖率比原始次数更能说明默认偏好。** `python3`、`cat`、`ls` 覆盖全部 22 个会话；`echo`、`sed`、`pwd` 覆盖 21 个。高频导入是 `pathlib`（94）、`numpy`（85）、`PIL`（59）和 `json`（35）。\n\n"
                    "12 个工具探测用例给出了更清楚的选择证据：JSON、压缩包、CSV、本地 HTTP、图像处理等任务普遍优先走 Python 标准库或 Pillow。放大到全部日志，`rg`、`jq`、`fd`、`awk`、`curl`、`wget` 均为 0；模型更常使用传统的 `find/sed/grep`。专用 CLI 仍会在合适处出现，例如 C++ 构建用 `make`，视觉兜底用 Chrome、tesseract、chafa。"
                ),
            },
            {"id": "executable_coverage_block", "type": "chart", "chartId": "executable_coverage_chart", "layout": "full"},
            {
                "id": "composition",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## 常见策略是把一次 Bash 调用写成一个小程序\n\n"
                    "**模型倾向于在单次调用里完成“定位 → 过滤 → 限流”。** 常见形式是 `cd/pwd/ls/find` 与 `sed/sort/head` 的组合；复杂生成任务则使用 Python heredoc，把多步计算或文件生成封装在一次调用中。管道用于缩小 observation，`&&` 用于让后续步骤只在前一步成功后执行。\n\n"
                    "这是一种高效的 Shell-native 策略，但也把风险集中到复合命令：一处引用、路径或依赖错误可能让整条链失败。因此运行时最好保留逐调用审计、输出截断和清晰退出码。"
                ),
            },
            {"id": "composition_chart_block", "type": "chart", "chartId": "composition_chart", "layout": "full"},
            {
                "id": "recovery",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## 依赖缺失时，模型先绕行，必要时再自建环境\n\n"
                    f"**两条恢复路线反复出现。** 结果文本记录了 {summary['protocol']['nonzero_bash_results']} 次最终非零 Bash（13 个会话），另有 {summary['total_missing_signals']} 个缺命令/缺模块信号（{missing_sessions} 个会话）；这些失败的 tool-result `isError` 仍为 false，模型主要依靠 stdout/stderr 和后续验证恢复。全部日志共有 {summary['total_install_attempts']} 条直接安装语句（23 条 pip、6 条 apt；旧口径因 heredoc 误报为 32）。若任务可用标准库或现有工具完成，模型通常直接降级：例如没有 matplotlib 时用 Pillow 画图，没有 pytest 时回退 unittest。若依赖难以绕开，则使用 `/tmp` venv、`pip --target /tmp`，甚至 `apt-get download + dpkg-deb` 解包用户态工具。\n\n"
                    f"严格复核显示 29 条直接安装中 10 条成功、19 条失败：13 次全局或 `--user` pip 全部失败，10 次 venv/`--target` 隔离安装全部成功，6 次 apt install 全部失败。`/tmp` 出现在 {summary['tmp_path_calls']}/650 次 Bash 调用、{summary['tmp_path_sessions']}/22 个会话中。恢复能力很强，但 `/tmp` 不持久、`~/.local` 只读会制造重复成本。"
                ),
            },
            {"id": "cost_chart_block", "type": "chart", "chartId": "cost_concentration_chart", "layout": "full"},
            {
                "id": "ab_finding",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## 环境增强改变了策略，但没有自动缩短轨迹\n\n"
                    "**唯一近似受控的同题对比是双叉臂任务。** Step 0 安装 pip、Pillow、chafa、ImageMagick 和 tesseract 后，模型自然采用 PIL/chafa/tesseract，主动探测、缺失信号和安装尝试都下降，最终非零 Bash 率也从 7/69（10.1%）降至 6/105（5.7%）；但 Bash 调用从 69 增至 105，主要伴随更多 NumPy 数值验证与视觉检查。\n\n"
                    "因此更丰富的环境首先提升的是可选策略和验证深度，而不保证调用数下降。评估应把成功率、产物质量、恢复成本和验证质量与调用量一起看。"
                ),
            },
            {"id": "ab_table_block", "type": "table", "tableId": "ab_table", "layout": "full"},
            {
                "id": "anti_patterns",
                "type": "markdown",
                "sourceId": "raw_logs",
                "layout": "full",
                "body": (
                    "## 有效策略之外，也出现了可重复的反模式\n\n"
                    "- **持久 cwd 被重复假设为初始状态。** 多个 vibe 会话在已经 `cd repo` 后再次执行同一命令并报路径不存在，随后才改用 `pwd` 或绝对路径。\n"
                    "- **过宽扫描代价很高。** P8 为找 `wish.md` 执行 `find /`，P2 为找字体再次扫根目录，均出现约 300 秒超时或资源问题。\n"
                    "- **容错符号会掩盖局部失败。** `2>/dev/null`、`|| true`、管道加 `tail` 很常见；复合命令的最终退出码不一定代表每个子步骤成功。\n"
                    "- **巨大 heredoc 降低可审查性。** 整文件覆盖减少往返，但小错误往往到运行阶段才暴露，也扩大了误覆盖范围。\n"
                    "- **会话内恢复不等于可复现。** C11 与 P8 依赖 `/tmp` 中的 poppler/cmake；环境重置后需要重新构建。\n"
                    "- **直接读取 verifier/evaluator 会污染成功指标。** 多数定向 case 在实现前读取 `.benchmark/verify.py`，部分 vibe 还读取 evaluator、spec 或 expected 数据；“全部通过”因此不能当作严格盲测结果。"
                ),
            },
            {
                "id": "step01_answer",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## Step 0.1：先装能终止自救循环的包\n\n"
                    "**建议采用一个默认 Core，加 docs、build、data 三个可叠加领域层。** 默认 Core 解决 `python` 别名、pytest、Chrome CDP websocket、zip/unzip 与 PNG 完整性检查；docs 层补齐 PDF 生成、抽取、渲染和 CJK 字体；build 层补齐 CMake/CTest/CPack；data 层再提供 SciPy、Matplotlib 与 pandas。若只能维护一个镜像，优先组合 **Core + docs + build**，把 data 保持为按任务挂载。\n\n"
                    "优先级来自恢复成本而非缺失次数本身：P2 与 C11 两个文档会话合计 161/650 次 Bash（24.8%），P8 构建发布任务有 55 次；而 29 条真实直接安装中，全局或 `--user` pip 13/13 失败、apt install 6/6 失败，隔离 venv/`--target` 10/10 成功。把高复用依赖在镜像构建期烘焙，比继续教模型运行时安装更可靠。"
                ),
            },
            {"id": "step01_package_table_block", "type": "table", "tableId": "step01_package_table", "layout": "full"},
            {
                "id": "step01_deployment",
                "type": "markdown",
                "layout": "full",
                "body": (
                    "## Python 包应优先进入系统解释器\n\n"
                    "**Ubuntu 26.04 上建议 apt-first。** 这批日志的模型在 22/22 个会话里直接调用普通 `python3`，因此 `python3-scipy`、`python3-reportlab` 这类发行版包会自然出现在默认解释器；只把包放进未激活的 `/opt` venv，模型仍可能看不到。Resolute 中 `pkg-config` 已是过渡包，新镜像应直接安装 `pkgconf`；`python3-websocket` 才是 PyPI `websocket-client` 对应的发行版包。可从 [Ubuntu 26.04 包索引](https://packages.ubuntu.com/resolute/) 复核。\n\n"
                    "只有 apt 版本不满足或必须锁定 PyPI 版本时，才在最终固定路径创建 `/opt/dsh-venv`，将其 `bin` 放在 PATH 首位并做完整 import smoke test。继续保留 PEP 668 的 externally-managed 保护，不用 `--break-system-packages` 修改系统 Python；[PEP 668](https://peps.python.org/pep-0668/) 与 [Python venv 文档](https://docs.python.org/3/library/venv.html) 都支持这种分工。罕见运行时依赖应进入持久 workspace venv，而不是 `/tmp`。\n\n"
                    "**体积与许可证是分层的主要原因。** Ubuntu 26.04 的 [Pandoc](https://packages.ubuntu.com/resolute/pandoc) 安装体约 202 MB、[Noto CJK 字体](https://packages.ubuntu.com/resolute/fonts-noto-cjk)约 91 MB，科学栈也会带入原生数值依赖；[`python3-pymupdf`](https://packages.ubuntu.com/resolute/python3-pymupdf) 还需通过 AGPL/商业双授权审查。docs/data 层应记录版本锁、SBOM、镜像增量和冷启动 smoke 结果。"
                ),
            },
            {
                "id": "step01_holds",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## 现在不要继续横向加包\n\n"
                    "- **通用 CLI 先做采用实验。** `rg`、`jq`、`fd`、`awk`、`curl`、`wget` 在 22 个会话中均为 0；其中 Step 0 环境已声明具备 `rg/curl/wget`，说明安装本身不保证模型自然采用。把 `jq/fd` 纳入“是否安装 × 是否在环境清单中提示”的小型 A/B，再决定是否进 Core。\n"
                    "- **暂缓 Playwright/Selenium 与浏览器下载体。** 现有 Chrome + CDP + websocket 已完成运行时和视觉验证；先补小型 `python3-websocket` 即可。\n"
                    "- **暂缓 OpenCV、pytesseract 与 Web 框架。** Pillow + tesseract CLI、标准库 HTTP server 和 unittest 已覆盖当前任务，相关缺包只来自零星探测。\n"
                    "- **重型办公栈单列。** LibreOffice、完整 TeX 与 wkhtmltopdf 只在领域探测中出现，可留给 `docs-heavy`，避免扩大默认镜像与文档解析攻击面。"
                ),
            },
            {
                "id": "step01_rollout",
                "type": "markdown",
                "sourceId": "behavior_metrics",
                "layout": "full",
                "body": (
                    "## 用三臂重放决定哪些层晋级默认镜像\n\n"
                    "对 C05、C07、C09、C11、P2、P8 和双叉臂任务，比较 **Step 0 → Step 0.1 Core → Core + 对应领域层**，固定模型、prompt、harness 与任务快照，并为每个条件做重复运行。主要判断标准应是：\n\n"
                    "1. 受支持路径的运行时 apt/pip 安装是否归零；\n"
                    "2. 冷容器是否无需 `/tmp` 依赖即可复现；\n"
                    "3. 任务成功率、隐藏测试与产物质量是否不下降；\n"
                    "4. 依赖探测、恢复调用、首次有效产物时间和下载字节是否下降；\n"
                    "5. 每 100 MB 镜像增量换回多少恢复时间或调用。\n\n"
                    "总 Bash 调用只能作为次级指标：现有唯一同题 A/B 中 Bash 从 69 增到 105，但最终非零率从 10.1% 降到 5.7%，说明丰富环境也可能把节省的成本转成更深验证。"
                ),
            },
            {
                "id": "recommendations",
                "type": "markdown",
                "layout": "full",
                "body": (
                    "## 建议优先优化 Python 基座与恢复路径\n\n"
                    "1. **把 Python 视为第一优先级。** 保证 `python3`、venv、pip、可写 wheel/cache/target 目录稳定；常用科学与视觉包应按任务域预装。\n"
                    "2. **让能力发现便宜且按需。** 保留 `which`/`command -v` 和简短 help，但避免在首轮注入大型 CLI catalog。\n"
                    "3. **提供持久、受控的用户工具目录。** 解决 `~/.local` 只读与 `/tmp` 易失问题，可显著减少重复安装和 wrapper 失败。\n"
                    "4. **围绕 Bash 的真实用法做治理。** 重点覆盖复合命令、heredoc、大 stdout、后台进程、下载/安装与文件覆盖，而不只是单一可执行程序白名单。\n"
                    "5. **不要用工具调用数单独评分。** 同时记录任务成功、验证深度、缺失恢复轮次、stdout 体积、时延与产物质量。"
                ),
            },
            {
                "id": "further_questions",
                "type": "markdown",
                "layout": "full",
                "body": (
                    "## 还需要回答的问题\n\n"
                    "- 对同一批任务补齐 baseline / enhanced、wish / spec 的完整交叉实验，区分环境与提示词效应。\n"
                    "- 将唯一的 V4-Flash 会话改用 V4-Pro 重跑，消除模型混杂。\n"
                    "- 进一步关联每条命令的退出码、时延与 stdout 体积，识别真正的重复调用和低收益探测。\n"
                    "- 单独测量 Bash 写文件与 editor 写文件的正确率、修复轮次和安全事件，而不是只看采用率。"
                ),
            },
            {
                "id": "caveats",
                "type": "markdown",
                "sourceId": "raw_logs",
                "layout": "full",
                "body": (
                    "## Caveats and assumptions\n\n"
                    f"这不是随机抽样：任务从短小工具探测到大型文档/仿真项目，难度差异很大；20 个会话处于 Step 0 环境，只有双叉臂具备 baseline 对照。C01 使用 V4-Flash，其余为 V4-Pro；双叉臂还多暴露一个视觉激活工具。双叉臂两次 request header 一致，但 baseline 的会话元数据曾从 anchored-standard 切到 minimal，Step 0 则从 minimal 开始。命令解析是 quote-aware 的近似 Shell 解析，heredoc 已屏蔽正文，但复杂嵌套语法仍可能有少量分类误差。旧版 `step0-environment.md` 中部分数字恰为正式事件口径的 3 倍，本报告没有使用这些陈旧值。结果文本中的 `[exit code: N]` 识别出 {summary['protocol']['nonzero_bash_results']}/650 次最终非零 Bash，但 DSH 的 `isError` 对 650 个 Bash 结果全部为 false，因此不能把 transport 状态当成 Shell 成功率。策略判断只基于可观察的 tool/call、tool/result 与产物检查，不推断隐藏推理过程。"
                ),
            },
        ],
    }

    artifact = {
        "surface": "report",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "tool_mix": tool_rows,
                "top_executable_coverage": executable_rows[:12],
                "command_composition": chart_features,
                "high_cost_sessions": high_cost_rows,
                "group_summary": groups,
                "ab_comparison": ab_rows,
                "step01_package_bundles": step01_rows,
            },
            "accessIssues": [],
        },
        "sources": artifact_sources,
    }
    (OUT / "artifact.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    chart_map = """# Chart map\n\n| Section | Question | Family / type | Fields | Supported claim | Palette policy | Delivery |\n|---|---|---|---|---|---|---|\n| Bash 已成为统一 ABI | 工具调用集中在哪个入口？ | Comparison / bar | tool, calls | Bash 占绝大多数正式调用 | single-root preferred | artifact.json → report.html |\n| Python 是默认能力层 | 哪些可执行程序跨会话最稳定？ | Ranking / bar | executable, sessions | Python3 与基础 Unix 工具覆盖最广 | single-root preferred | artifact.json → report.html |\n| 单次调用像小程序 | 哪些组合语法最常见？ | Comparison / bar | feature, call_share | 复合命令、链式执行与管道是核心形态 | single-root preferred | artifact.json → report.html |\n| 恢复成本呈长尾 | 哪些会话贡献最多 Bash 调用？ | Ranking / bar | task, bash_calls | 少数复杂任务主导总调用量 | single-root preferred | artifact.json → report.html |\n\nAll four visuals are categorical comparisons, so repeated bars are intentional. The portable artifact bar contract is vertical; labels are shortened in the chart dataset and full definitions remain in tooltips/source rows.\n"""
    (OUT / "source_notes.md").write_text(
        chart_map
        + "\n## Reproducibility\n\n"
        + "Run `python reports/bash-behavior-analysis/build_analysis.py` from the repository root, then package `artifact.json` with the Data Analytics portable report builder. The script imports `analyze_logs.py`, counts only formal tool events, and writes all derived CSV/JSON files in this directory.\n"
        + "\n## Data-quality corrections\n\n"
        + "- `session-case-01` is DeepSeek V4-Flash; the other 21 sessions are V4-Pro.\n"
        + "- Install detection is rerun on heredoc-masked shell text so generated source strings are not counted as executed installs.\n"
        + "- Direct install outcomes were checked against paired tool results: isolated venv/--target pip 10/10 succeeded; global/user pip 0/13 and apt install 0/6 succeeded.\n"
        + "- Import counts are textual signals, not proof of successful imports.\n"
        + "- Final non-zero Bash status uses the last `\\[exit code: N\\]` marker in the paired tool-result text; compound commands can still hide earlier subcommand failures.\n"
        + "- Stale triple-counted figures in `reports/step0-environment.md` are excluded.\n"
        + "\n## Step 0.1 decision framework\n\n"
        + "The package matrix ranks domains by observed recovery cost, cross-task reuse, fallback quality, image footprint, and persistence risk. It is a product recommendation from 22 non-random sessions, not a causal package-effect estimate. No new chart was added: the decision requires exact package/profile lookup, so a five-row spacious table is more honest than a synthetic score chart. The four existing charts and their datasets remain unchanged.\n\n"
        + "Package names were checked against Ubuntu 26.04 Resolute on 2026-08-16. Key references: [Ubuntu package index](https://packages.ubuntu.com/resolute/), [Pandoc](https://packages.ubuntu.com/resolute/pandoc), [Poppler utilities file list](https://packages.ubuntu.com/resolute/amd64/poppler-utils/filelist), [CMake](https://packages.ubuntu.com/resolute/cmake), [PEP 668](https://peps.python.org/pep-0668/), and [Python venv](https://docs.python.org/3/library/venv.html). `pkgconf` is preferred over the transitional `pkg-config` package. `python3-websocket` maps to PyPI websocket-client. PyMuPDF requires an AGPL/commercial-license review.\n"
        + "\n## Audience structure mapping\n\n"
        + "The product-stakeholder structure is: title → Executive Summary → evidence-backed findings and existing charts/tables → Step 0.1 decision table and rollout → general recommendations → further questions → caveats. The new package section is inserted after observed anti-patterns so the recommendation follows the evidence; no required role is omitted.\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "sessions": total_sessions,
        "tool_calls": total_tool_calls,
        "bash_calls": total_bash_calls,
        "bash_share": summary["bash_share"],
        "median_bash_calls": summary["bash_calls_median"],
        "first_call_inspection_sessions": first_inspect_count,
        "read_before_write_sessions": f"{read_before_write_count}/{len(writable_sessions)}",
        "post_write_validation_sessions": f"{post_write_validation_count}/{len(writable_sessions)}",
        "top5_bash_call_share": summary["top5_bash_call_share"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
