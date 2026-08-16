# Chart map

| Section | Question | Family / type | Fields | Supported claim | Palette policy | Delivery |
|---|---|---|---|---|---|---|
| Bash 已成为统一 ABI | 工具调用集中在哪个入口？ | Comparison / bar | tool, calls | Bash 占绝大多数正式调用 | single-root preferred | artifact.json → report.html |
| Python 是默认能力层 | 哪些可执行程序跨会话最稳定？ | Ranking / bar | executable, sessions | Python3 与基础 Unix 工具覆盖最广 | single-root preferred | artifact.json → report.html |
| 单次调用像小程序 | 哪些组合语法最常见？ | Comparison / bar | feature, call_share | 复合命令、链式执行与管道是核心形态 | single-root preferred | artifact.json → report.html |
| 恢复成本呈长尾 | 哪些会话贡献最多 Bash 调用？ | Ranking / bar | task, bash_calls | 少数复杂任务主导总调用量 | single-root preferred | artifact.json → report.html |

All four visuals are categorical comparisons, so repeated bars are intentional. The portable artifact bar contract is vertical; labels are shortened in the chart dataset and full definitions remain in tooltips/source rows.

## Reproducibility

Run `python reports/bash-behavior-analysis/build_analysis.py` from the repository root, then package `artifact.json` with the Data Analytics portable report builder. The script imports `analyze_logs.py`, counts only formal tool events, and writes all derived CSV/JSON files in this directory.

## Data-quality corrections

- `session-case-01` is DeepSeek V4-Flash; the other 21 sessions are V4-Pro.
- Install detection is rerun on heredoc-masked shell text so generated source strings are not counted as executed installs.
- Direct install outcomes were checked against paired tool results: isolated venv/--target pip 10/10 succeeded; global/user pip 0/13 and apt install 0/6 succeeded.
- Import counts are textual signals, not proof of successful imports.
- Final non-zero Bash status uses the last `\[exit code: N\]` marker in the paired tool-result text; compound commands can still hide earlier subcommand failures.
- Stale triple-counted figures in `reports/step0-environment.md` are excluded.

## Step 0.1 decision framework

The package matrix ranks domains by observed recovery cost, cross-task reuse, fallback quality, image footprint, and persistence risk. It is a product recommendation from 22 non-random sessions, not a causal package-effect estimate. No new chart was added: the decision requires exact package/profile lookup, so a five-row spacious table is more honest than a synthetic score chart. The four existing charts and their datasets remain unchanged.

Package names were checked against Ubuntu 26.04 Resolute on 2026-08-16. Key references: [Ubuntu package index](https://packages.ubuntu.com/resolute/), [Pandoc](https://packages.ubuntu.com/resolute/pandoc), [Poppler utilities file list](https://packages.ubuntu.com/resolute/amd64/poppler-utils/filelist), [CMake](https://packages.ubuntu.com/resolute/cmake), [PEP 668](https://peps.python.org/pep-0668/), and [Python venv](https://docs.python.org/3/library/venv.html). `pkgconf` is preferred over the transitional `pkg-config` package. `python3-websocket` maps to PyPI websocket-client. PyMuPDF requires an AGPL/commercial-license review.

## Audience structure mapping

The product-stakeholder structure is: title → Executive Summary → evidence-backed findings and existing charts/tables → Step 0.1 decision table and rollout → general recommendations → further questions → caveats. The new package section is inserted after observed anti-patterns so the recommendation follows the evidence; no required role is omitted.
