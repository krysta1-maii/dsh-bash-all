# Step 0.1 环境基线：bash 工具可调用的包体

- **性质：基线冻结（只盘点，不安装）**
- 快照时间：2026-08-17T02:43:47+08:00（UTC 2026-08-16T18:43:47Z）
- 主机：WSL2 / Ubuntu 26.04 (Resolute)，`x86_64`
- 运行身份：`andyk`（uid 1000，非 root）
- Shell：`/bin/bash`，GNU bash 5.3.9
- 模型可见工具：`bash` + `str_replace_editor`（本项目 ABI；本文件只描述 Bash 背后的可调用面）
- 复现脚本：`reports/step0.1-environment/snapshot_step01_packages.py`

本文件把“当前 bash 工具可调用哪些包体”冻结为 **Step 0.1 基线**。判断口径是：已安装且可直接通过 `PATH` 调用的 CLI、可直接 `import` 的 Python 模块、`apt list --installed` 中的系统包，以及 `npm ls -g` 中的全局包。

---

## 0. 结论

当前 bash 工具的可调用面：

| 来源 | 数量 | 说明 |
|---|---:|---|
| apt 已安装包 | 1244 | 完整系统包面 |
| pip 可见发行包 | 116 | 完整清单见 `reports/step0.1-environment/pip_freeze.txt` |
| npm 全局包 | 4 | `@deepseek-ai/dsh`、`corepack`、`npm`、`pnpm` |
| 关键 CLI | 已盘点 | 详细状态见 `reports/step0.1-environment/package_baseline.csv` |

相对 Step 0.1 包体决策矩阵（`reports/bash-behavior-analysis/step01_package_bundles.csv`）的 25 个推荐 apt 包：

| 包体层 | 安装情况 | 缺口 |
|---|---:|---|
| P0 Core（Python 入口/测试/胶水） | **5/7** | `python3-websocket`、`pngcheck` |
| P0 Docs（文档/PDF/字体） | **7/11** | `python3-reportlab`、`python3-pymupdf`、`python3-svglib`、`weasyprint` |
| P0 Build（原生构建/发布） | **4/4** | 无 |
| P1 Data（科学计算/绘图） | **3/3** | 无 |
| 合计 | **19/25** | 6 个未安装 |

Step 0 的既有增强包全部仍在：`Pillow`、`ImageMagick`、`chafa`、`tesseract`（eng/osd）、`google-chrome`、`numpy`。

运行时安装约束与 Step 0 相同：

- 当前用户非 root，`sudo -n` 不可用（不能无交互 `apt install`）；
- Python 3.14 系统环境受 PEP 668 保护，`pip install` 到系统路径被拒绝；
- `~/.local` 存在但不可写（mode 0755），`pip install --user` 同样失败；
- 因此本基线只冻结“现状”，补齐 6 个缺口应走镜像构建或可交互 root，而不是依赖模型在 Bash 里运行时自救。

---

## 1. Step 0.1 决策矩阵安装状态

状态中的版本来自 `dpkg-query -W`；❌ 表示未安装。

### 1.1 P0 Core：Python 入口、测试与轻量胶水

| 推荐包 | 状态 | 已安装版本 |
|---|---|---|
| `python-is-python3` | ✅ | 3.13.3-1+build1 |
| `python3-venv` | ✅ | 3.14.3-0ubuntu2 |
| `python3-pytest` | ✅ | 9.0.2-4 |
| `python3-websocket` | ❌ | - |
| `zip` | ✅ | 3.0-15ubuntu3 |
| `unzip` | ✅ | 6.0-29ubuntu1 |
| `pngcheck` | ❌ | - |

对应可调用面：`python` / `python3` = Python 3.14.4；`pip` / `pip3` = 25.1.1；`pytest` = 9.0.2。`import websocket` / `import websockets` 均缺失。

### 1.2 P0 Docs：文档、PDF 与字体

| 推荐包 | 状态 | 已安装版本 |
|---|---|---|
| `pandoc` | ✅ | 3.7.0.2+ds-1 |
| `poppler-utils` | ✅ | 26.01.0-2ubuntu0.1 |
| `poppler-data` | ✅ | 0.4.12-1build1 |
| `ghostscript` | ✅ | 10.06.0~dfsg-3ubuntu1 |
| `fontconfig` | ✅ | 2.17.1-3ubuntu1 |
| `fonts-noto-cjk` | ✅ | 1:20240730+repack1-1build1 |
| `python3-reportlab` | ❌ | - |
| `python3-pymupdf` | ❌ | - |
| `python3-svglib` | ❌ | - |
| `python3-fonttools` | ✅ | 4.61.1-3build1 |
| `weasyprint` | ❌ | - |

对应可调用面：`pandoc 3.7.0.2`、`pdftotext/pdfinfo/pdftoppm 26.01.0`、`gs 10.06.0`、`fc-list/fc-cache 2.17.1`。系统中文字体 `fc-list :lang=zh` 有 31 条记录。Python 侧 `fontTools 4.61.1` 可导入；`reportlab`、`fitz`、`svglib`、`weasyprint` 不可导入。

### 1.3 P0 Build：原生构建与发布

| 推荐包 | 状态 | 已安装版本 |
|---|---|---|
| `build-essential` | ✅ | 12.12ubuntu2.26.04.2 |
| `cmake` | ✅ | 4.2.3-2ubuntu2 |
| `ninja-build` | ✅ | 1.13.2-1 |
| `pkgconf` | ✅ | 2.5.1-4 |

对应可调用面：`make 4.4.1`、`gcc/g++ 15.2.0`、`cmake/ctest 4.2.3`、`ninja 1.13.2`、`pkgconf/pkg-config 2.5.1`、`dpkg-deb 1.23.7`。未安装的上下文项：`meson`、`gfortran`、`clang`。

### 1.4 P1 Data：科学计算、数据与绘图

| 推荐包 | 状态 | 已安装版本 |
|---|---|---|
| `python3-scipy` | ✅ | 1.16.3-4build1 |
| `python3-matplotlib` | ✅ | 3.10.7+dfsg1-2build1 |
| `python3-pandas` | ✅ | 2.3.3+dfsg-3ubuntu1 |

对应可调用面：`numpy 2.3.5`、`scipy 1.16.3`、`pandas 2.3.3`、`matplotlib 3.10.7+dfsg1`、`Pillow 12.1.1` 均可 `import`；另有 `sympy 1.14.0`。`sklearn`、`cv2` 缺失。

---

## 2. 其他已安装 / 缺失的 Bash 可调用面

### 2.1 Step 0 遗留增强（全部可用）

| 项目 | 版本 / 状态 |
|---|---|
| `google-chrome` | 151.0.7922.137 |
| `chafa` | 1.18.1 |
| `convert` / `identify` / `magick` | ImageMagick 7.1.2-18 |
| `tesseract` | 5.5.0，语言 `eng`、`osd` |
| `python3-pil` | Pillow 12.1.1 |

### 2.2 通用 CLI 与 JS/TS 运行时

已可用：

| 项目 | 版本 |
|---|---|
| `git` | 2.53.0 |
| `gh` | 2.46.0 |
| `rg` | 15.1.0 |
| `curl` | 8.18.0 |
| `wget` | 1.25.0 |
| `node` / `npm` / `npx` | v24.19.0 / 11.17.0 / 11.17.0 |
| `pnpm` | 11.21.0 |
| `awk` / `sed` / `perl` / `tar` / `file` | 系统自带 |
| `@deepseek-ai/dsh`（npm 全局） | 0.1.0-rc.6 |

仍缺失的观察项：`jq`、`fd`、`tree`、`sqlite3`、`yarn`、`tsx`、`chromium`、`chromium-browser`、`firefox`、`playwright`。这与 Step 0.1 决策矩阵中 P2 “先实验或暂缓”的结论一致。

### 2.3 可 import 的其它非标准 Python 模块（节选）

已可用：`requests 2.32.5`、`beautifulsoup4 4.14.3`、`lxml 6.0.2`、`PyYAML 6.0.3`、`openpyxl 3.1.5`、`rich 13.9.4`、`click 8.1.8`、`Pygments 2.19.2`、`tables 3.10.2`、`numba 0.64.0` 等。

仍缺失：`playwright`、`selenium`、`flask`、`fastapi`、`uvicorn`、`httpx`、`sklearn`、`cv2` 等。

完整 pip 面见 `reports/step0.1-environment/pip_freeze.txt`（116 项）。

---

## 3. 基线文件

| 文件 | 内容 |
|---|---|
| `reports/step0.1-environment.md` | 本文件：人类可读基线 |
| `reports/step0.1-environment/package_baseline.csv` | 逐项探测结果（apt / CLI / Python module / npm global） |
| `reports/step0.1-environment/pip_freeze.txt` | 完整 pip 包版本快照 |
| `reports/step0.1-environment/npm_global.json` | npm 全局包快照 |
| `reports/step0.1-environment/snapshot_meta.json` | 主机、工具链与可写性元数据 |
| `reports/step0.1-environment/snapshot_step01_packages.py` | 只读探测脚本；重跑可刷新基线 |

重新生成：

```bash
python3 reports/step0.1-environment/snapshot_step01_packages.py
```

## 4. 与 Step 0 基线的关系

- Step 0 基线：`reports/step0-environment.md`（记录 pip、Pillow、chafa、ImageMagick、tesseract 六项显式安装）。
- 本基线是 Step 0 之后、按 Step 0.1 决策矩阵盘点得到的“安装现状”，不是一次新安装动作的结果。
- 已从 Step 0 状态新增/观察到：pytest、zip/unzip、pandoc、poppler、ghostscript、fontconfig/Noto CJK、build-essential、cmake、ninja、pkgconf、scipy、matplotlib、pandas、fontTools、sympy、requests、bs4/lxml 等。
- 仍未满足的 Step 0.1 目标只有 6 个 apt 包；其中 `python3-websocket`、`pngcheck` 属于默认 Core，4 个 PDF/SVG/HTML 渲染库属于 Docs 层。
- 若下一步要“完成 Step 0.1 安装”，建议在镜像/root 层补齐这 6 个包；在普通用户 Bash 运行时，因 `sudo -n` 不可用、PEP 668 与 `~/.local` 只读，模型不应被期望自行完成系统级安装。
