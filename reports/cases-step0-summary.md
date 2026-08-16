# 12 用例分析汇总：step0 环境

- 日志目录：`logs/cases/step0/`
- 逐用例报告：`reports/cases/step0/session-case-XX/`
- 合并 CSV：`reports/cases-step0-summary.csv`

## 总览

| case | 任务 | 会话内结果 | bash | 消息数 | 第一选择 | 缺口/回退 |
|---|---|---|---:|---:|---|---|
| C01 | JSON 解析 | PASS | 5 | 12 | python3 + json/decimal | 无 → 未使用 jq |
| C02 | 文件查找 | PASS | 5 | 11 | python3 + pathlib/json | 无 → 未使用 fd；只用 find 做初览 |
| C03 | 压缩包处理 | PASS | 5 | 12 | python3 + zipfile/pathlib | 无 → 未使用 unzip |
| C04 | CSV 统计 | PASS | 7 | 14 | python3 + csv/Decimal | 无 → 未使用 pandas/awk |
| C05 | 数值求解 | PASS | 17 | 36 | python3 + numpy；scipy 补装后使用 | scipy ×1 → 先手写 numpy 求解，后 pip/venv 补 scipy |
| C06 | 符号计算 | PASS | 4 | 10 | python3 标准库 + importlib | 无 → 未尝试 sympy |
| C07 | 图表生成 | PASS | 18 | 38 | Pillow 手绘 PNG；chafa 查看 | matplotlib ×2, pandas ×1 → 优先探测 matplotlib/pandas，最终 Pillow 兜底 |
| C08 | 图像处理 | PASS | 7 | 16 | python3 + PIL | 无 → 未使用 convert/identify |
| C09 | 测试诊断 | PASS | 11 | 23 | 先 pytest，再 unittest | python cmd ×1, pytest ×1 → 默认想用 pytest，缺失后回退 unittest |
| C10 | C/C++ 构建 | PASS | 7 | 15 | make | 无 → 未使用 cmake/ninja |
| C11 | 文档转换 | PASS* | 51 | 103 | pypandoc-binary + weasyprint + apt 下载 poppler 到 /tmp | pdfinfo ×1 → 首选 pandoc 系；系统包缺失时用 /tmp 自建依赖 |
| C12 | 本地 HTTP + JSON | PASS | 11 | 24 | python3 + urllib.request | 无 → 未使用 curl/jq/requests |

## 关键结论

1. **12 个用例在会话内全部通过 verifier**。唯一需要标注的是 C11：它通过的依赖位于 `/tmp`，shell 重置后不持久；现在直接重跑 verifier 会报 `pdfinfo` 缺失。
2. **V4-Pro 的首选是 Python，而不是专用 CLI**：
   - C01 没有用 `jq`，直接用 Python 标准库；
   - C02 没有用 `fd`，用 Python `pathlib`；
   - C03 没有用 `unzip`，用 Python `zipfile`；
   - C04 没有用 `pandas`/`awk`，用 Python `csv`；
   - C08 没有用 `convert`/`identify`，用 Pillow；
   - C12 没有用 `curl`/`jq`，用 Python `urllib`。
3. **它想要的第三方 Python 包**：`scipy`、`matplotlib`、`pandas`、`pytest`。这些都在任务中出现缺失信号。
4. **已装 Step 0 包中实际被 12 用例使用**：Pillow（C07/C08 等）、chafa（C07 查看图）；ImageMagick 和 tesseract 本轮没有被实际调用。
5. **回退模式稳定**：缺包时优先尝试 `pip`，系统路径失败后会使用 `python3 -m venv /tmp/...` 或 `pip --target /tmp/...`，最终大多能自行恢复。
6. **C11 暴露持久化问题**：模型可以下载 deb 并解压到 `/tmp` 自建 poppler 工具，但 `/home/andyk/.local` 只读导致无法写入 wrapper；所以依赖不能跨 shell 持久。

## 建议

- 如果这些任务域会反复出现，优先预装：`python3-scipy`、`python3-matplotlib`、`python3-pandas`、`python3-pytest`、`poppler-utils`。
- `jq`、`fd`、`unzip` 在当前 12 用例中不是第一选择，暂不需要因这些用例预装。
- 修复 `/home/andyk/.local` 只读或提供可写的用户 bin 目录，可显著减少 C05/C07/C09/C11 的恢复成本。
