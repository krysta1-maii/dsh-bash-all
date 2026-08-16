# 分析报告：双叉臂测试

> 对应原始日志：`logs/双叉臂测试.jsonl`
> 生成方式：`python3 analyze_logs.py logs/双叉臂测试.jsonl -o reports/双叉臂测试 --no-txt`
> 计数口径：只统计 DSH 的正式 `tool/call` / `tool/result` 事件，不重复统计流式 chunk。

## 1. 会话信息

| 项目 | 值 |
|---|---|
| DSH session id | `session-a8157e06-0059-44de-8e71-6ed42ec6197d` |
| 工作目录 | `/home/andyk/projects/测试用` |
| 初始 agent preset | `anchored-standard` |
| 实际选择 preset | `minimal` |
| 有效 JSON 行 | 6987 |
| 会话消息数 | 141 |
| 工具调用总数 | 70 |
| bash 调用 | 69 |
| str_replace_editor 调用 | 0 |
| vision_toolkit_activate 调用 | 1 |
| 主动能力探测次数 | 13 |

## 2. 模型可见工具与工具调用

`request/header` 显示本会话模型可见工具为：

```text
bash
str_replace_editor
vision_toolkit_activate
```

实际调用：

| 工具 | 次数 |
|---|---:|
| bash | 69 |
| vision_toolkit_activate | 1 |
| str_replace_editor | 0 |

### vision_toolkit_activate 行为

- 模型在 step 13 生成截图后，根据该工具的 description 推测可以激活视觉能力，调用了一次 `vision_toolkit_activate`。
- 返回结果：

```text
Error: vision_toolkit_activate: load the vision-tools Skill first
```

- 之后模型 reasoning 明确写出 `No vision`，随后转入 `google-chrome`、Python 像素分析、PNG 手写解码和 OCR 探测等替代路径。
- 因此它不是“读到了 vision-tools Skill 本身”，而是读到了这个激活工具的 schema；Skill 并未加载，激活失败一次后没有重试。

## 3. Bash 中高频可执行程序

| 可执行程序 | 次数 |
|---|---:|
| python3 | 41 |
| node | 22 |
| google-chrome | 18 |
| grep | 17 |
| sleep | 11 |
| kill | 11 |
| echo | 10 |
| cd | 8 |
| tail | 7 |
| ls / true / head | 6 |
| apt-get / rm | 4 |

## 4. Python import 信号

| 模块 | 次数 | 说明 |
|---|---:|---|
| pathlib | 16 | 标准库 |
| struct | 11 | 标准库，本任务中用于手写 PNG 解码 |
| numpy | 6 | 已安装并被自然使用 |
| PIL | 4 | 缺失，模型反复尝试 |
| selenium | 1 | 环境探测 |
| playwright | 1 | 环境探测 |

## 5. 模型主动探测的工具（`which` 信号）

`which` 探测失败不会产生 `command not found`，但能直接暴露模型默认假设环境里“应该有什么”。

| 探测目标 | 次数 |
|---|---:|
| chafa | 2 |
| chromium-browser | 1 |
| chromium | 1 |
| google-chrome | 1 |
| firefox | 1 |
| viu | 1 |
| jp2 | 1 |
| txt2img | 1 |
| img2txt | 1 |
| convert | 1 |
| identify | 1 |
| tesseract | 1 |

原始探测命令示例：

```bash
which chafa viu jp2 txt2img img2txt convert identify tesseract 2>/dev/null || true
which chromium-browser chromium google-chrome firefox 2>/dev/null || true
```

## 6. 环境缺口

| 缺口 | 次数 |
|---|---:|
| `pip: command not found` | 1 |
| `No module named 'pip'` | 1 |
| `No module named 'PIL'` | 4 |

## 7. 安装尝试

| 包管理器 | 次数 | 原始目标 |
|---|---:|---|
| apt-get | 3 | `chafa`、`python3-pil` |
| pip / python3 -m pip | 2 | `pillow` |

说明：模型先尝试 `pip install pillow`，随后退回 `python3 -m pip install pillow`；在 pip 不可用后又尝试 `apt-get install python3-pil`。这些 apt 尝试最终都因非 root 用户权限失败。

## 8. 对第一阶段包清单的启示

本次单任务观察支持 Step 0 的最小安装集：

- `python3-pip`
- `python3-pil`
- `chafa`
- `imagemagick`
- `tesseract-ocr`（含英文语言包）

不安装：

- `viu`、`img2txt` / `txt2img`：后备选择
- `jp2`：Ubuntu 26.04 中不存在 `/usr/bin/jp2`，疑似模型幻觉探测
- `chromium` / `firefox`：浏览器后备选择
- `selenium` / `playwright`：仅 import 探测，无实际使用
- E 层工具（`jq`、`fd`、`pandas` 等）

这是一条已有任务轨迹，不是受控 Phase 1 A/B；下一步用同一提示词在 Step 0 环境重跑后，与本报告做同口径对比。
