# Step 0 环境快照

安装方式：WSL2 / Ubuntu 26.04，root 下 `apt-get install`。

| 包 | 版本 |
|---|---|
| python3-pip | 25.1.1+dfsg-1ubuntu2 |
| python3-pil | 12.1.1-2ubuntu1.2 |
| chafa | 1.18.1-1 |
| imagemagick | 8:7.1.2.18+dfsg1-1 |
| tesseract-ocr | 5.5.0-1build1 |
| tesseract-ocr-eng | 1:4.1.0-2build1 |

已有且未重装的第一选择：

- `google-chrome`：上一轮轨迹实际使用 54 次
- `numpy`：上一轮轨迹 import 18 次
- `python3`、`node`、`git`、`gh`、`rg`、`curl`、`wget`

Step 0 不包含 E 层工具（`jq`、`fd`、`tree`、`unzip`、`pandas`、`scipy` 等）。
