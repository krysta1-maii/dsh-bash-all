# Phase 1 工具探测测试用例（12 个）

本文件用于寻找：**在不提示任何工具名的情况下，V4-Pro 默认会通过 bash 调用哪些命令或 Python 包。**

每个用例都应在一个干净、独立的会话中运行，并且只描述任务结果，不出现 `jq`、`fd`、`pandas`、`pytest` 等工具名。

---

## 统一规则

1. 每次只跑一个用例，一个用例导出一个 `.jsonl`。
2. 每个用例使用独立的测试目录，避免上一个任务残留文件影响行为。
3. Prompt 中不得出现具体命令、包名或工具名。
4. 模型可以失败；失败时的 `command not found`、`No module named`、`which` 探测、`pip/apt install` 尝试都是有效信号。
5. 导出日志按以下方式命名：

```text
logs/cases/<variant>/case-01-json.jsonl
logs/cases/<variant>/case-02-find.jsonl
...
```

建议先跑：

```text
logs/cases/step0/case-01-json.jsonl
logs/cases/step0/case-02-find.jsonl
```

6. 每批跑完后执行：

```bash
python3 analyze_logs.py logs/cases/step0/case-01-json.jsonl --no-txt
# -> reports/case-01-json/
```

重点查看：

- `executable_usage.csv`
- `python_imports.csv`
- `capability_probes.csv`
- `missing_commands.csv`
- `missing_modules.csv`
- `install_attempts.csv`

---

## 测试用例

### C01 JSON 解析

- **目的**：观察模型处理 JSON 数据时首选 `jq` 还是 Python。
- **夹具**：准备 `data.json`，包含数组和嵌套字段，例如 100 条 `{"id":..., "name":..., "price":...}`。
- **Prompt**：

```text
读取 data.json，提取 items 中 price 大于 100 的所有条目，并计算这些条目的 price 总和。把结果写入 result.txt。
```

- **观察工具**：`jq` / `python3` / `node`。
- **成功标准**：`result.txt` 中的结果与参考值一致。

---

### C02 文件查找

- **目的**：观察模型查找文件时首选 `fd`、`find` 还是 `rg`。
- **夹具**：准备 `src/` 目录树，其中混有 `.py`、`.js`、`.md` 文件；部分 Python 文件内包含 `TODO` 注释。
- **Prompt**：

```text
找出 src 目录下所有 Python 文件，并列出其中包含 TODO 的文件的完整路径。结果写入 todo-files.txt。
```

- **观察工具**：`fd` / `find` / `rg` / `grep`。
- **成功标准**：路径列表完整且不包含非 Python 文件。

---

### C03 压缩包处理

- **目的**：观察模型处理 zip 时首选 `unzip` 还是 Python `zipfile`。
- **夹具**：准备 `submission.zip`，其中包含多层目录和若干文本文件。
- **Prompt**：

```text
把 submission.zip 解压到 out/ 目录，然后列出 out/ 下所有文件的相对路径，写入 file-list.txt。
```

- **观察工具**：`unzip` / `python3`（`zipfile`）。
- **成功标准**：解压结构完整，`file-list.txt` 与实际内容一致。

---

### C04 CSV 统计

- **目的**：观察模型处理表格数据时首选 `pandas` 还是 awk / Python 标准库。
- **夹具**：准备 `sales.csv`，包含 `region`、`product`、`revenue` 等列，数据有多个 region。
- **Prompt**：

```text
计算 sales.csv 中每个 region 的平均 revenue，按 region 排序后输出为 CSV 文件 result.csv。
```

- **观察工具**：`python3`（`pandas` / `csv`） / `awk`。
- **成功标准**：`result.csv` 中分组和平均值与参考结果一致。

---

### C05 数值求解

- **目的**：观察模型做数值计算时首选 `scipy` 还是手写算法。
- **夹具**：准备一个含多项式的 `equation.txt`，例如 `x^3 - 2*x - 5 = 0`。
- **Prompt**：

```text
求解 equation.txt 中方程在 2 附近的一个实根，要求至少精确到小数点后 10 位，并验证结果。结果写入 root.txt。
```

- **观察工具**：`python3`（`scipy.optimize` / 手写牛顿法 / `numpy`）。
- **成功标准**：`root.txt` 中的根与参考值误差小于 `1e-10`。

---

### C06 符号计算

- **目的**：观察模型做符号计算时是否首选 `sympy`。
- **夹具**：准备 `expression.txt`，例如要求验证三角恒等式：

```text
sin(a+b) = sin(a)cos(b) + cos(a)sin(b)
```

- **Prompt**：

```text
验证 expression.txt 中的恒等式是否成立。如果成立，请用符号方法证明或验证；如果不成立，给出反例。结论写入 verification.txt。
```

- **观察工具**：`python3`（`sympy`）。
- **成功标准**：结论正确，且验证过程不是纯文字推理。

---

### C07 图表生成

- **目的**：观察模型画图时首选 `matplotlib` 还是手写 SVG/HTML。
- **夹具**：准备 `chart-data.csv`，包含两列数值数据。
- **Prompt**：

```text
根据 chart-data.csv 生成一张 PNG 图表，要求包含坐标轴、图例和标题。输出 chart.png。
```

- **观察工具**：`python3`（`matplotlib`） / 手写 SVG 转换 / `node`。
- **成功标准**：`chart.png` 可正常打开，尺寸合理，包含预期图表元素。

---

### C08 图像处理

- **目的**：观察模型处理图像时首选 Pillow 还是 ImageMagick/ffmpeg。
- **夹具**：准备一张尺寸明显大于 200px 宽的 `input.png`。
- **Prompt**：

```text
把 input.png 缩放为宽度 200px，保持宽高比，然后转换为灰度图，保存为 output.png。
```

- **观察工具**：`python3`（`PIL`） / `convert` / `magick` / `ffmpeg`。
- **成功标准**：`output.png` 宽度为 200px，颜色模式为灰度。

---

### C09 测试执行

- **目的**：观察模型运行测试时首选 `pytest` 还是手写测试脚本。
- **夹具**：准备一个 Python 小项目 `mini_project/`，包含若干函数和一个有失败断言的测试文件。
- **Prompt**：

```text
检查 mini_project 的测试是否能全部通过。如果失败，请给出失败的测试名称和原因，写入 test-report.txt。
```

- **观察工具**：`pytest` / `python3 -m unittest` / 手写调用。
- **成功标准**：`test-report.txt` 中的失败测试名称和原因与夹具一致。

---

### C10 C/C++ 构建

- **目的**：观察模型构建项目时首选 `cmake` / `ninja` 还是 `make`。
- **夹具**：准备一个小型 C++ 项目，包含 `CMakeLists.txt` 和 `src/main.cpp`，构建后运行输出一个已知字符串。
- **Prompt**：

```text
构建 build-project 中的 C++ 项目，运行生成的可执行文件，并把输出写入 build-output.txt。
```

- **观察工具**：`cmake` / `ninja` / `make` / `g++`。
- **成功标准**：构建成功，`build-output.txt` 内容正确。

---

### C11 文档转换

- **目的**：观察模型做文档转换时首选 `pandoc` / `pdftotext` 还是 Python 库。
- **夹具**：准备一份 `README.md`。
- **Prompt**：

```text
把 README.md 转换为 HTML 文件 README.html；再从 README.html 生成 PDF；最后从 PDF 提取纯文本到 README.txt。
```

- **观察工具**：`pandoc` / `pdftotext` / `python3`。
- **成功标准**：三个文件均存在，`README.txt` 包含正文内容。

---

### C12 本地 HTTP + JSON

- **目的**：观察模型访问本地 HTTP 服务后如何解析 JSON。
- **夹具**：准备一个静态 API 服务 `api-server.py`，本地监听固定端口，返回多字段 JSON。
- **Prompt**：

```text
本地 8000 端口有一个 HTTP API。请求 /items 并提取其中 status 为 ok 的条目，按 id 排序后写入 api-result.txt。
```

- **观察工具**：`curl` / `wget` / `python3`（`requests`） / `jq`。
- **成功标准**：`api-result.txt` 内容与 API 返回值一致。

---

## 记录建议

每个用例跑完后，至少记录：

```text
- 测试用例 ID
- variant（例如 step0）
- 是否成功
- 第一次 action 使用的主要命令/工具
- 是否出现 command not found
- 是否出现 No module named
- 是否尝试 pip / apt / npm 安装
- 是否出现回退方案
- 产物文件是否与参考结果一致
```

这些字段后续可以直接并入 `reports/` 中的对比表。
