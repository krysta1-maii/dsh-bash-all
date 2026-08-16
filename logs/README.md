# Raw test exports

Put DSH/agent conversation exports here as `.jsonl` files, one conversation per file
when possible. Suggested layout:

```text
logs/
  phase1/
    baseline/
      task-01-json.jsonl
      task-02-find.jsonl
    t1-enhanced/
      task-01-json.jsonl
      task-02-find.jsonl
```

The analyzer is schema-tolerant: DSH event lines, OpenAI-style messages and
Anthropic-style content blocks are all supported. Keep the original export
format; do not pre-clean it.

Run the analyzer from the repo root. For a single log file, results are
written to `reports/<log-stem>/` with the same stem as the log:

```bash
python3 analyze_logs.py logs/双叉臂测试.jsonl --no-txt
# -> reports/双叉臂测试/
```

To analyze every log into its own matching report folder:

```bash
for f in logs/*.jsonl; do
  python3 analyze_logs.py "$f" --no-txt
done
```

To create one merged comparison across all logs instead:

```bash
python3 analyze_logs.py logs
# -> reports/analysis/
```

Generated CSV files:

| File | Contents |
|---|---|
| `trajectory_summary.csv` | one row per conversation/session |
| `tool_usage.csv` | tool call counts by session |
| `executable_usage.csv` | executables seen inside bash commands |
| `python_imports.csv` | Python imports in Python-invoking bash commands |
| `capability_probes.csv` | binaries probed via `which`, `command -v`, `type`, `hash` |
| `missing_commands.csv` | `command not found` signals from tool results |
| `missing_modules.csv` | `No module named ...` signals from tool results |
| `install_attempts.csv` | package-manager install attempts |
| `install_packages.csv` | raw package specs from install attempts |
| `bash_commands.txt` | all bash commands, grouped by session |
