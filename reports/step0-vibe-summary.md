# 许愿式 vibe coding 8 项目分析汇总

- 日志目录：`logs/cases/step0-vibe/`
- 逐项目明细：`reports/cases/step0-vibe/session-vibe-XX/`
- 合并数据：`reports/cases/step0-vibe/_merged/`
- 数据表：`reports/step0-vibe-summary.csv`

## 总览

| 项目 | 任务 | bash | 消息 | editor | 主要工具链 | 缺失信号 | 安装尝试 | 评估 |
|---|---|---:|---:|---:|---|---|---:|---|
| P1 | 财务 Dashboard | 23 | 48 | 0 | Pillow + Python stdlib | matplotlib,pandas 仅探测 | 0 | 7/7 |
| P2 | 文档工程 | 110 | 221 | 0 | 自建 .build-venv：reportlab+PyMuPDF+svglib | pandoc 命令缺失；reportlab/fontTools/rlPyCairo 缺失 | 10 | 8/8 |
| P3 | 修仓库 | 19 | 36 | 0 | /tmp venv 中的 pytest | python 命令缺失；pytest 模块缺失 | 2 | 4/4* |
| P4 | 本地任务管理 | 24 | 50 | 0 | stdlib http.server + sqlite3 + unittest | flask/fastapi/uvicorn 仅探测 | 0 | 7/7 |
| P5 | 交互式物理仿真 | 30 | 60 | 0 | 单 HTML JS 仿真 + Chrome CDP selftest | playwright 缺失 | 1 | 7/7 |
| P6 | OCR 表格流水线 | 47 | 99 | 2 | tesseract CLI + PIL/numpy | pngcheck 命令缺失；cv2/pytesseract 缺失 | 0 | 7/7 |
| P7 | 本地网站爬取 | 20 | 37 | 0 | Python stdlib + Chrome headless | 无 | 0 | 7/7 |
| P8 | C++ 打包发布 | 55 | 120 | 4 | CMake+CTest+CPack；apt-download cmake | cmake/ctest/zip/unzip 缺失 | 4 | 6/6* |

## 核心结论

1. **8/8 项目全部通过 evaluator**。
   - P1/P2/P4/P5/P6/P7：直接在当前仓库状态通过；
   - P3*：evaluator 需要 pytest，当前系统没有；放入临时 venv 后 4/4；
   - P8*：evaluator 需要 cmake/ctest，当前系统没有；提供 cmake/ctest 后 6/6。

   模型在会话内已经分别用 `/tmp` venv 和 apt-download + dpkg-deb 自建过这些依赖。
2. **Python 仍是默认语言**。8 个项目中除 P5/P8 的构建产物外，主体逻辑全部是 Python 或 stdlib 实现。
3. **缺包时有两种策略**：
   - 如果任务能绕开依赖，就用标准库或已装工具绕开（P1 用 Pillow、P4 用 http.server、P6 用 tesseract CLI）；
   - 如果绕不开，就会非常执着地自建环境（P2 的 .build-venv、P3 的 /tmp venv、P8 的 /tmp/cmake-root）。
4. **视觉自检已经形成稳定套路**：Chrome 截图/远程调试 + PIL/numpy 像素分析 + tesseract OCR + convert/gs 渲染 + chafa 终端预览。vision_toolkit 仍然不可用，但 P2/P5/P6/P7 都靠这套兜底通过。
5. **str_replace_editor 依然几乎不用于编辑**：8 个项目共 6 次，其中 4 次是 `view` 读文件、1 次是 P6 的 `create`，实际修改仍以 `cat > file` 和 Python 文本替换为主。
6. **成本极不均衡**：
   - 顺利项目：P7 20 次 bash、P3 19 次、P1 23 次；
   - 高成本项目：P2 110 次、P8 55 次、P6 47 次。
   高成本主要花在依赖恢复和视觉验证，而不是写代码本身。
7. **环境问题再次出现**：`~/.local` 只读、系统 cmake/pandoc/poppler/pytest 缺失、`/tmp` 不持久。模型已经学会用 `/tmp` + venv/apt-download 绕过，但交付物对 /tmp 存在隐性依赖。

## 下一步建议

- 本轮只跑了 `step0/wish`。接下来优先补跑 `step0/spec`、`enhanced/wish`、`enhanced/spec` 三组，才能判断是“许愿式 prompt”还是“环境差异”在起作用。
- 若这些项目要反复测试，建议预装：`python3-pytest`、`pandoc`、`poppler-utils`、`cmake`、`ctest`、`zip`、`unzip`，以及 Python 的 `reportlab`、`pymupdf`、`svglib`、`fonttools`。
- `playwright`、`flask/fastapi/uvicorn`、`cv2/pytesseract` 在本轮只是探测或非必需，暂不建议预装。
