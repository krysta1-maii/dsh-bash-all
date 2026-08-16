# 对比报告：baseline vs step0

- baseline：`logs/双叉臂测试.jsonl`（Step 0 包未安装）
- step0：`logs/双叉臂测试-step0.jsonl`（已安装 pip、Pillow、chafa、ImageMagick、tesseract-ocr/eng）
- 两轮均为相同提示词、相同 cwd，模型可见工具均为 `bash + str_replace_editor + vision_toolkit_activate`。

## 1. 总量指标

| 指标 | baseline | step0 | 变化 |
|---|---:|---:|---|
| 有效 JSON 行 | 6987 | 10569 | +51.3% |
| 会话消息数 | 141 | 212 | +50.4% |
| 工具调用总数 | 70 | 106 | +51.4% |
| bash 调用 | 69 | 105 | +52.2% |
| vision_toolkit_activate | 1 | 1 | 0 |
| str_replace_editor | 0 | 0 | 0 |
| 首次 action 前消息序号 | 3 | 3 | 不变 |
| 主动能力探测 | 13 | 8 | -38.5% |
| command not found | 1 | 0 | -1 |
| module missing | 5 | 1 | -4 |
| 包安装尝试 | 5 | 3 | -2 |

## 2. 工具采用对比

| 工具/命令 | baseline | step0 | 观察 |
|---|---:|---:|---|
| chafa 实际使用 | 0 | 5 | 新工具被自然采用 |
| tesseract 实际使用 | 0 | 2 | 新工具被自然采用 |
| PIL import | 4（缺失） | 4（可用） | 从缺口变成可用 |
| apt-get | 4 | 0 | 不再尝试系统安装 |
| pip | 1 | 3 | 仍有用户态安装，但目标变为 websocket-client |
| google-chrome | 18 | 11 | 使用下降 |
| python3 | 41 | 85 | 大幅上升 |
| node | 22 | 18 | 基本稳定 |
| numpy import | 6 | 49 | 数值验证显著增加 |

## 3. 探测行为对比

| 探测目标 | baseline | step0 |
|---|---:|---:|
| chafa | 2 | 1 |
| tesseract | 1 | 1 |
| viu / jp2 / img2txt | 各 1 | 各 1 |
| convert / identify | 各 1 | 0 |
| chromium / chromium-browser / google-chrome | 各 1 | 各 1 |
| firefox | 1 | 0 |
| txt2img | 1 | 0 |

模型仍会探测 `viu`、`jp2`、`img2txt` 等未安装项，但频次下降；部分后备项不再探测。

## 4. 缺口对比

| 缺口 | baseline | step0 |
|---|---:|---:|
| `pip: command not found` | 1 | 0 |
| `No module named 'pip'` | 1 | 0 |
| `No module named 'PIL'` | 4 | 0 |
| `No module named 'playwright'` | 0 | 1 |

Step 0 解决了上一轮全部缺口；本轮新出现且唯一的模块缺口是 `playwright`。

## 5. 产物对比

| 项目 | baseline | step0 |
|---|---|---|
| 文件 | `双叉臂测试基线.html` | `index.html` |
| 大小 | 56825 bytes | 63595 bytes |
| 行数 | 1555 | 1535 |
| 标题 | Double Wishbone Suspension Kinematics Workbench | 双叉臂前悬架线弹性运动学仿真系统 |
| canvas 引用次数 | 11 | 27 |
| 截图渲染 | 1600x900 成功 | 1600x900 成功 |
| 像素差异（RMSE） | - | 0.1296（约 13%） |

说明：RMSE 和关键词计数只能说明两版结构不同，不能直接代表质量高低。

## 6. 当前结论

1. Step 0 包生效：`PIL`、`chafa`、`tesseract` 都被实际使用，上一轮的环境自救行为明显减少。
2. `vision_toolkit_activate` 两轮都失败，失败原因相同：vision-tools Skill 未加载。
3. 本轮轨迹更长、bash/python 调用更多，主要是 numpy 数值验证增加；不能仅凭 token/tool 数量判断好坏。
4. 新缺口 `playwright` 只是 import 探测失败，尚不属于本轮功能第一选择。
5. 下一步可以继续观察：在相同环境下是否稳定使用 `chafa/tesseract`，以及是否有必要补 `playwright` 或处理 `~/.local` 只读导致的 pip 失败。
