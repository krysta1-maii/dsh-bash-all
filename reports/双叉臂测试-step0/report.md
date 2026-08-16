# 分析报告：双叉臂测试-step0

> 对应原始日志：`logs/双叉臂测试-step0.jsonl`
> 环境：已安装 Step 0 包（pip、Pillow、chafa、ImageMagick、tesseract-ocr/eng）
> 计数口径：只统计正式 `tool/call` / `tool/result` 事件。

## 1. 会话信息

| 项目 | 值 |
|---|---|
| DSH session id | `session-0e1a356e-b9a5-418c-9473-98a7851704c3` |
| 工作目录 | `/home/andyk/projects/测试用` |
| agent preset | `minimal`（会话开始即为 minimal） |
| 模型可见工具 | `bash`, `str_replace_editor`, `vision_toolkit_activate` |
| 有效 JSON 行 | 10569 |
| 会话消息数 | 212 |
| 工具调用总数 | 106 |
| bash 调用 | 105 |
| vision_toolkit_activate 调用 | 1 |
| str_replace_editor 调用 | 0 |
| 主动能力探测次数 | 8 |

## 2. 工具调用

| 工具 | 次数 |
|---|---:|
| bash | 105 |
| vision_toolkit_activate | 1 |
| str_replace_editor | 0 |

`vision_toolkit_activate` 仍然调用一次并返回：

```text
Error: vision_toolkit_activate: load the vision-tools Skill first
```

之后模型继续走 `google-chrome + Python/PIL + chafa + tesseract` 替代路径。

## 3. Step 0 新工具是否被自然使用

| 新装能力 | 实际使用 | 说明 |
|---|---:|---|
| Pillow / PIL | 4 次 import | 无 `No module named 'PIL'` |
| chafa | 5 次 | 用于终端查看截图 |
| tesseract | 2 次 | 用于 OCR 截图标签 |
| ImageMagick convert/identify | 0 次 | 本轮未实际调用 |
| pip | 3 次 | 用于临时安装 `websocket-client` |

## 4. Bash 中高频可执行程序

| 可执行程序 | 次数 |
|---|---:|
| python3 | 85 |
| pkill | 19 |
| node | 18 |
| echo / cd | 16 |
| head | 14 |
| true | 13 |
| rm / google-chrome / sleep | 11 |
| cat | 8 |
| ls / grep | 6 |
| chafa / timeout | 5 |
| which / pip / tail | 3 |
| tesseract / kill / wc | 2 |

## 5. Python import 信号

| 模块 | 次数 | 说明 |
|---|---:|---|
| numpy | 49 | 数值验证显著增加 |
| pathlib | 21 | 标准库 |
| json | 11 | 标准库 |
| PIL | 4 | 已可用，无缺失 |
| playwright | 1 | 缺失 |
| websocket | 1 | 通过 pip --target 临时安装成功 |
| collections / unicodedata | 各 1 | 标准库 |

## 6. 能力探测

| 探测目标 | 次数 |
|---|---:|
| chafa / chromium / chromium-browser / google-chrome | 各 1 |
| img2txt / jp2 / tesseract / viu | 各 1 |

相比 baseline，本轮未再探测 `convert`、`identify`、`firefox`、`txt2img`。

## 7. 环境缺口与自我安装

缺失信号：

| 缺口 | 次数 |
|---|---:|
| `No module named 'playwright'` | 1 |
| `command not found` | 0 |
| `No module named 'PIL'` / `pip` | 0 |

pip 安装尝试共 3 次，全部围绕 `websocket-client`：

```text
pip install websocket-client -q
pip install websocket-client -q --break-system-packages
pip install websocket-client -q --target /tmp/ws --break-system-packages
```

前两次因 PEP 668 和 `~/.local` 只读失败，第三次用 `--target /tmp/ws` 成功。

## 8. 产物

- 输出文件：`/home/andyk/projects/测试用/index.html`
- 大小：63595 bytes，1535 行
- 标题：`双叉臂前悬架线弹性运动学仿真系统`
- 渲染测试：Chrome 1600x900 截图成功，OCR 可识别 `DOUBLE WISHBONE SUSPENSION / LINE-ELEMENT KINEMATICS`、`VIEW-A FRONT / XZ`、`WSOLVER CONVERGED` 等标签。
