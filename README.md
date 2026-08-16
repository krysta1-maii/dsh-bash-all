# DSH Shell-Native Agent Runtime
## ——以 `bash + str_replace_editor` 为稳定模型 ABI，将工具能力下沉到 Shell 的 Agent 架构提案

> **Status:** Proposal / Experimental  
> **Working title:** Shell Presentation / Bash-First DSH / Minimal++  
> **Primary target:** DeepSeek V4-Pro + DeepSeek Harness (DSH)  
> **Core thesis:** **不要通过增加模型可见 Tool Schema 来扩展 Agent 能力；保持模型侧接口稳定，把复杂性下沉到 Shell 环境与 Harness Runtime。**

---

## 0. 摘要

本项目提出一种针对 DeepSeek V4-Pro 与 DSH 的 Agent Runtime 设计：

- 模型侧长期保持一个极小、稳定、训练充分的工具 ABI：
  - `bash`
  - `str_replace_editor`
- 不再将 Web Search、Browser、GitHub、Subagent、Skill、Workflow 等能力逐一暴露成新的模型可见 Tool Schema。
- 相反，将这些能力：
  1. 尽可能以原生 CLI / Python / Node / Unix 工具形式提供给 Bash；
  2. 或通过一个 DSH Shell Gateway，将已有 DSH Tool Registry 自动映射为 CLI；
  3. 仍然保留 DSH 的权限、审批、沙箱、审计、取消、事件与 UI 能力。
- 模型通过熟悉的 Bash 接口调用越来越丰富的外部能力，而无需改变其模型可见工具组合。

简化后：

```text
                V4-Pro
                   │
        canonical model-visible ABI
          ┌────────┴────────┐
          │                 │
        bash       str_replace_editor
          │
          ▼
     Enhanced Shell
          │
   ┌──────┼────────────────────────┐
   │      │         │              │
 Unix   Python    DSH CLI       Code Mode
 tools  /NumPy   Gateway        Runtime
   │      │         │              │
 git    scipy     web/search      tools.*
 rg     pandas    browser          SDK
 jq     pillow    subagent
 ...     ...      skills
                  workflow
```

这不是“让 Bash 代替一切基础设施”，而是：

> **让 Bash 成为模型侧稳定的能力入口；真正复杂的工具治理仍然属于 DSH Runtime。**

---

# 1. 背景与问题

## 1.1 当前观察：V4-Pro 对 Tool Schema 异常敏感

目前围绕 V4-Pro + DSH 的社区测试出现了一个值得认真研究的现象：

- **无工具（0 tools）** 时，模型往往进入稳定、高效的裸推理状态；
- **精确的 `bash + str_replace_editor`** 组合下，也容易进入稳定、高效的 Coding Agent 状态；
- 但以下变化可能显著扰动模型 policy / CoT trajectory：
  - 只保留 `bash`；
  - 只保留 `str_replace_editor`；
  - 首轮直接提供更多工具；
  - 在两工具之外增加更多 Model-visible tools；
  - 更改 `bash` / editor 的 description；
  - 更改工具命名、schema 或控制面工具结构。

这提示一个重要可能性：

> V4-Pro 学到的不只是“如何使用 Bash”，而可能对**完整 Agent Interface Fingerprint**形成了较强条件化。

可以把这一假说写成：

```text
Interface Fingerprint =
  persona
+ tool names
+ tool descriptions
+ parameter schema
+ tool count / catalog shape
+ protocol
+ context shape
+ interaction history
```

目前尚不能证明 DeepSeek 内部具体使用了怎样的训练分布，但至少从黑盒行为上看：

> **模型可能没有充分学到对 Harness Interface 变化的不变性。**

---

## 1.2 两个可能的训练甜点

一个值得验证的工作假说是，V4-Pro 至少存在两个训练覆盖特别充分的稳定区：

### Sweet Spot A：无工具 / 裸模型

```text
system + user
     ↓
reasoning
     ↓
answer
```

这是普通 reasoning / instruction post-training 的自然分布。

### Sweet Spot B：Minimal Coding Agent

```text
software-engineer persona
+
bash
+
str_replace_editor
        ↓
reason
→ action
→ observation
→ reason
```

如果大量 Coding Agent RL / evaluation trajectory 都围绕类似接口构建，那么模型在这一环境下形成非常稳定的动作先验并不奇怪。

关键点是：

> **0 tools、1 tool、2 tools、20 tools 并不是一条天然连续的“工具数量轴”。**

训练分布完全可能大量覆盖：

```text
0 tools
```

和：

```text
exact bash + editor
```

却很少覆盖：

```text
bash only
editor only
bash + editor + workflow
同义改写版 bash description
任意第三方 tool catalog
```

因此模型行为可能出现明显的离散稳定岛，而不是平滑变化。

---

# 2. 为什么不是继续堆 Prompt / Router

当前已有不少实验试图通过：

- persona；
- first-turn anchoring；
- `We need` / `Let me` trajectory；
- tool catalog narrowing；
- router；
- mode boost；

来把 V4-Pro 推回更高效的 policy 区域。

这些工作非常有价值，但如果 **Tool Schema 本身就是核心 conditioning signal**，那么单纯在 Prompt 层修补可能永远不够稳定。

更重要的是：

> **Anchoring 依赖“后续环境不要把模型从锚点拖走”。**

例如：

```text
首轮：
bash + str_replace_editor

后续：
bash + str_replace_editor + full Standard
```

是一种增量扩张，可能相对稳定。

但：

```text
首轮：
bash + str_replace_editor

后续：
撤掉二者，切换到另一套工具协议
```

则更像一次 Runtime 换轨，模型可能重新进入另一种 policy。

因此本项目希望减少对“如何不断重新锚定模型”的依赖，转而提出：

> **既然模型已经有一套训练充分的动作语言，那就尽量不要换语言。**

---

# 3. 核心原则：稳定模型 ABI，扩张环境能力

本项目的第一原则：

> **模型可见接口尽量不变；能力扩展发生在接口背后。**

也就是：

```text
第 1 轮：
bash + str_replace_editor

第 50 轮：
bash + str_replace_editor

第 500 轮：
bash + str_replace_editor
```

变化的是 Bash 后面的世界：

```text
最初：
bash
├── python
├── git
└── rg

后来：
bash
├── python + numpy/scipy/pandas
├── node/pnpm
├── git/gh
├── browser CLI
├── web search CLI
├── DSH Tool Gateway
├── subagent CLI
├── skills CLI
└── Code Mode bridge
```

最终目标是：

> **Minimal 的模型接口 + Standard 的 Runtime 能力。**

---

# 4. 为什么 Bash 值得成为模型侧主 ABI

## 4.1 Bash 是组合语言，而不只是一个工具

独立工具通常是一对一能力：

```text
read_file
search_files
run_tests
git_status
download_url
parse_json
```

而 Bash 天然支持：

```bash
find ... | grep ... | sort ... | head ...
git diff --name-only | xargs rg "TODO"
curl ... | jq ... | python ...
```

模型面对的不是几十套互不相关的 JSON Schema，而是一种统一的动作语言：

> **程序是工具，stdout/stderr 是 observation，pipe 是组合。**

---

## 4.2 把 Tool Generalization 转化为 Coding Generalization

如果模型看到一个全新工具：

```text
search_repository({
  pattern,
  paths,
  context_lines,
  exclude,
  max_results
})
```

它必须先理解一个新的 Tool Schema。

如果改成：

```bash
rg -n -C 3 'pattern' src --glob '!vendor/**' | head -100
```

这个问题就变成了模型更熟悉的：

> **写代码 / 写命令。**

对于 Coding 能力已经很强的模型，这可能是一种更稳妥的能力迁移方式。

---

## 4.3 双叉臂悬挂案例：环境增强已经产生直接收益

此前在双叉臂悬挂 HTML 任务中，V4-Pro 曾尝试使用 NumPy，但当时环境没有安装，于是退化为手写向量与矩阵运算。

在 WSL 安装 NumPy 后，同类任务轨迹中模型已经自然出现：

```bash
python3 - << 'PY'
import numpy as np, math
...
PY
```

并使用 NumPy 进行：

- 空间几何；
- Jacobian；
- Newton 求解；
- 数值验证。

这说明：

> **只丰富 Bash 环境，而完全不增加模型可见工具，就已经能够改变模型的实际工作策略，并减少其为“环境贫瘠”支付的认知成本。**

这是本项目最直接的早期实证之一。

---

# 5. DSH 已经存在的关键先例：Code Mode

本提案并不是从零发明“工具转接层”。

DSH 已经实现了 **Code Mode**，而它实际上已经证明了最关键的架构前提：

> **Tool Registry 中存在什么能力，与模型最终看到什么工具接口，是可以解耦的。**

DSH Code Mode 当前的基本思想是：

### Native Mode

```text
Tool Registry
    ↓
tool A schema
tool B schema
tool C schema
...
    ↓
Model
```

### Code Mode

```text
Tool Registry
    ↓
generated TypeScript SDK
    ↓
single run_code transport
    ↓
Model writes a TypeScript program
```

也就是说，模型不再逐步调用多个 JSON Tool，而是：

```ts
const a = await tools.A(...)
const b = await tools.B(a)
return await tools.C(b)
```

程序在 Code Runtime 中执行，内部子调用仍然经过 DSH 的完整工具流水线。

DSH 官方实现已经具有：

- Tool Registry；
- presentation mode；
- generated SDK；
- `run_code` transport；
- Code Runtime；
- 子调用调度；
- 权限与 pre/post execute；
- 审计事件；
- cancellation；
- result normalization。

这意味着 DSH 已经接受：

```text
Internal Capability
        ≠
Model-visible Tool Schema
```

这个抽象。

---

# 6. Shell Presentation：Code Mode 的兄弟方案

本项目建议在概念上增加一种新的 Tool Presentation：

```text
native
code
shell
```

或者更抽象：

```text
                 Tool Registry
                      │
         ┌────────────┼────────────┐
         │            │            │
       Native        Code         Shell
         │            │            │
     JSON tools    run_code      canonical bash
                      │            │
                   TS SDK       CLI Gateway
```

三者解决的问题不同：

| Presentation | 模型看到什么 | 主要优势 |
|---|---|---|
| Native | 多个 JSON Tool Schema | 显式、结构化、易审计 |
| Code | `run_code` + SDK | 多步组合、减少模型往返 |
| Shell | canonical `bash` + editor | 稳定 ABI、按需发现、最大化训练分布兼容性 |

---

# 7. Shell Mode 与 Code Mode 的关键区别

两者有亲缘关系，但不是同一个东西。

## Code Mode

核心思想：

> **模型很会写代码，因此让模型用程序组合 Tool Registry。**

但模型侧接口依然发生明显变化：

```text
run_code
+
生成的 TypeScript SDK
+
Code Mode guidance
```

如果 V4-Pro 对 Tool Schema / system prompt shape 高度敏感，那么：

```text
bash + str_replace_editor
```

和：

```text
run_code + SDK
```

可能属于完全不同的 policy 条件。

---

## Shell Mode

核心思想：

> **如果 V4-Pro 已经在 `bash + str_replace_editor` 上训练充分，那么不要重新发明一种模型侧工具语言。**

因此：

```text
Tool Registry
     ↓
Shell Gateway
     ↓
CLI commands
     ↓
canonical bash
     ↓
V4-Pro
```

模型一直认为自己在使用 Bash。

---

# 8. Shell Mode 与 Code Mode 可以组合，而不是互斥

一个更强的设计是：

```text
V4-Pro
   │
   └── bash
         │
         ├── normal shell
         │     ├── git
         │     ├── rg
         │     ├── python
         │     └── node
         │
         └── dsh code
               │
               ▼
          Code Runtime
               │
          generated SDK
               │
          Tool Registry
```

例如：

```bash
dsh code <<'TS'
const results = await tools.web_search({ query: "..." })
const pages = await Promise.all(
  results.slice(0, 4).map(x => tools.web_open({ id: x.id }))
)
return pages.map(x => x.summary)
TS
```

这样：

- **模型侧仍然只有 Bash；**
- 复杂工具编排仍然可以复用 Code Mode；
- DSH 不需要放弃已经实现的 Code Runtime；
- `run_code` 不必直接暴露为模型 Tool Schema。

这是本项目非常值得验证的一条路线。

---

# 9. 目标架构

```text
                         ┌──────────────────────┐
                         │       V4-Pro         │
                         └──────────┬───────────┘
                                    │
                         Model-visible ABI
                    ┌───────────────┴───────────────┐
                    │                               │
                  bash                    str_replace_editor
                    │
                    ▼
        ┌───────────────────────────┐
        │     Persistent Shell      │
        │     / Shell Substrate     │
        └────────────┬──────────────┘
                     │
      ┌──────────────┼──────────────────────────────────┐
      │              │                 │                │
      ▼              ▼                 ▼                ▼
 Native CLI      Language Env      DSH Gateway      Code Bridge
      │              │                 │                │
 git/rg/jq       Python/Node         dsh tool          dsh code
 gh/curl/...     NumPy/SciPy            │                │
                                     ToolRuntime     CodeRuntime
                                         │                │
                                         └──────┬─────────┘
                                                │
                                                ▼
                                       DSH Tool Registry
                                                │
                              ┌─────────────────┼───────────────┐
                              │                 │               │
                              ▼                 ▼               ▼
                            Web             Subagent         Skills/...
```

---

# 10. 第一阶段：Enhanced Minimal

第一阶段完全不需要写 Tool Gateway。

目标：

> **只把 Shell 世界做富。**

建议默认提供或检测：

## Python / 数值

- Python 3
- NumPy
- SciPy
- pandas
- Pillow
- （可选）OpenCV

## JS / TS

- Node.js
- pnpm
- tsx
- 常用构建链

## Unix 工具

- `rg`
- `fd`
- `jq`
- `tree`
- `file`
- `sed`
- `awk`
- `perl`
- `tar`
- `unzip`
- `curl`
- `wget`

## 开发工具

- git
- gh
- make
- cmake
- ninja
- 编译器工具链

第一阶段应尽量做到：

> **零 Prompt 修改、零 Tool Schema 修改。**

只改变 environment。

---

# 11. 第二阶段：DSH Shell Gateway

建议设计统一命令：

```bash
dsh tools
dsh help web
dsh web search "..."
dsh web open ...
dsh agent run "..."
dsh agent status ...
dsh skill list
```

底层不应直接绕开 DSH，而应进入：

```text
Shell CLI
   ↓
Shell Gateway
   ↓
ToolRuntime
   ↓
pre-execute
   ↓
approval / permission
   ↓
executor
   ↓
post-execute
   ↓
normalized result
   ↓
stdout
```

---

# 12. Generic Tool Bridge

为了避免插件作者维护两套实现，可以先提供一个通用桥：

```bash
dsh tool list
dsh tool describe web_search
dsh tool call web_search --json '{"query":"DeepSeek V4 Pro"}'
```

流程：

```text
Plugin
  ↓
defineTool()
  ↓
Tool Registry
  ↓
Shell Adapter auto-generates CLI exposure
```

因此：

> **新插件只注册一次 Tool，Native / Code / Shell 三种 presentation 自动获得能力。**

对于高频能力，再增加 ergonomic alias：

```bash
dsh web search "..."
```

内部仍然可以转成：

```bash
dsh tool call web_search ...
```

---

# 13. Capability Discovery：让模型“发现”，而不是提前塞满 Prompt

一个核心问题是：

> 模型怎么知道 Bash 后面还有 Web、Subagent、Skill 等能力？

本项目不建议修改 canonical Bash description 来塞入大量说明。

原因：

- description 本身可能影响 V4-Pro policy；
- 首轮 system/tool fingerprint 应尽量保持 reference interface；
- 一次性暴露所有能力又会重新制造 Tool Catalog 过载。

建议按风险从低到高测试三种方案。

---

## 方案 A：纯环境发现

只保证：

```bash
command -v dsh
dsh --help
```

存在。

完全不主动提示。

观察模型是否会在需要时自然探索环境。

---

## 方案 B：首个 Bash Observation 后的一次性 Hint

第一次 Bash 调用完成后，observation 尾部附加：

```text
Extended DSH shell capabilities are available.
Run `dsh help` if additional services are needed.
```

只出现一次。

这样：

```text
首轮请求
→ canonical Minimal interface
→ model enters desired trajectory
→ first bash call
→ observation
→ capability hint
```

不会污染首轮模型接口。

---

## 方案 C：Shell MOTD / Lazy Discovery

第一次 persistent shell session 返回：

```text
Additional DSH capabilities are available through `dsh`.
Run `dsh help` to inspect them when needed.
```

具体能力只有在：

```bash
dsh help web
dsh help agent
```

时才动态加载。

本质是：

> **Lazy Tool Description。**

---

# 14. 安全原则：Bash 简化的是模型接口，不是安全边界

本项目绝不能把：

> “Everything is Bash”

误解成：

> “所有危险操作都直接执行”。

正确设计应是：

```text
Model
  ↓
bash("dsh mail send ...")
  ↓
Shell Gateway
  ↓
Policy / Approval
  ↓
Actual Connector
```

必须保留：

- sandbox；
- approval；
- access control；
- tool permissions；
- cancellation；
- audit trail；
- UI rendering；
- session persistence；
- telemetry。

即：

> **模型 ABI 极简，控制平面可以非常复杂。**

---

# 15. 为什么这可能是 DSH 的合理第一方路线

本提案对 DSH 尤其自然，因为 DSH 已经拥有：

1. **极简 Minimal reference composition**
2. **Tool Registry**
3. **Tool presentation 抽象**
4. **Code Mode**
5. **Code Runtime**
6. **完整的 Tool execution pipeline**
7. **权限 / approval / sandbox / event 系统**
8. **插件化 Cordis 基础设施**

因此 Shell Mode 不需要重新发明整个 Harness。

它更像：

> **给 ToolRuntime 增加一种新的 presentation adapter。**

甚至从架构演化上看，可以想象：

```ts
mode:
  | "native"
  | "code"
  | "both"
  | "shell"
```

或者未来把 presentation 完全抽象为独立 provider。

---

# 16. 为什么这也可能适用于第三方 Harness

如果 DeepSeek 最终确认某套 reference Agent Interface 对 V4-Pro 最稳定，那么理论上可以发布：

> **DeepSeek Agent Compatibility Kit**

包含：

## Reference Profile

- canonical system conditioning；
- canonical `bash` schema；
- canonical `str_replace_editor` schema；
- context conventions；
- recommended reasoning effort。

## Shell Runtime

例如：

```text
deepseek-agent-runtime
```

提供：

```bash
ds-agent help
ds-agent tool list
ds-agent tool call ...
```

## Harness Adapter

第三方 Harness 只需要把自己的：

```text
Host Tool Registry
```

映射到：

```text
DeepSeek Shell Gateway
```

模型仍然看到统一 reference interface。

这会形成类似：

> **Model Agent ABI / Driver**

的概念。

---

# 17. 与“重新后训练修复”的关系

本项目不是否认未来应当修复模型鲁棒性。

长期正确方向仍然应该包括：

- tool schema randomization；
- tool count randomization；
- description paraphrasing；
- system prompt diversification；
- context strategy diversification；
- interaction protocol diversification；
- multi-harness RL；
- cross-harness OOD evaluation。

但对于已经冻结并具有很高峰值能力的 V4-Pro：

> **Harness-side compatibility layer 的确定性可能显著高于立即重新打开 post-training。**

重新训练可能影响：

- reasoning depth；
- coding peak；
- initiative；
- tool-use efficiency；
- token economy；
- 其他已经达到局部最优的能力。

而 Shell Presentation：

- 不改模型权重；
- 不改 canonical tool ABI；
- 可快速 A/B；
- 易回滚；
- 可渐进部署；
- 不阻碍后续模型训练修复。

因此它很适合作为：

> **产品层 mitigation + 下一代训练前的稳定交付方案。**

---

# 18. 项目目标

## G1. 保持 reference trajectory

在增强能力后，V4-Pro 仍应尽可能保持 Minimal-like 的：

```text
reason briefly
→ act
→ observe
→ update
→ act
```

而不是进入长时间首轮过度推理。

---

## G2. 不增加模型可见 Tool Schema

项目的严格实验约束：

> **新增 Agent 能力时，不通过增加 Model-visible tools 实现。**

---

## G3. Standard capability coverage

逐步覆盖：

- 文件与工程操作；
- Web Search；
- Browser；
- Git / GitHub；
- Python / Data；
- Subagent；
- Skills；
- Workflow；
- Code Mode；
- 其他 DSH Plugins。

---

## G4. 保留 DSH Governance

所有经 Shell Gateway 调用的能力仍应经过：

- permission；
- approval；
- sandbox；
- telemetry；
- audit；
- cancellation。

---

## G5. Harness-independent value

即使未来 V4-Pro 修复 schema sensitivity，这套：

> **高质量 Agent Shell Substrate**

仍应对其他 Coding / Research Agent 有价值。

---

# 19. 非目标

本项目当前不追求：

- 修改 V4-Pro 权重；
- 破解模型内部真实机制；
- 证明某个具体 CoT token 是“真正模式开关”；
- 把所有 UI 动作都强行 Unix 化；
- 取消 Native Tool Mode；
- 取消 Code Mode；
- 绕过 DSH 的安全与权限系统。

---

# 20. MVP 路线

## Milestone 0：基线冻结

记录官方 Minimal：

- exact system prompt；
- exact Bash schema / description；
- exact editor schema；
- tool count；
- runtime context 行为。

建立 regression fixture。

---

## Milestone 1：Enhanced Shell Environment

只做环境增强：

- NumPy / SciPy；
- `rg` / `fd` / `jq`；
- git / gh；
- Node / pnpm；
- build tools。

**不修改 system prompt 和 tool schema。**

评测：

- 双叉臂悬挂；
- repo maintenance；
- 数据分析任务；
- greenfield web task。

---

## Milestone 2：Read-only DSH Gateway

优先接入无副作用能力：

```bash
dsh web search
dsh web open
dsh github read
dsh skill list
```

验证：

- 模型是否主动发现；
- CoT 是否漂移；
- token / latency 是否变化；
- success rate 是否提升。

---

## Milestone 3：Generic Tool Bridge

实现：

```bash
dsh tool list
dsh tool describe
dsh tool call
```

自动映射 Tool Registry。

---

## Milestone 4：Subagent

实现：

```bash
dsh agent run
dsh agent status
dsh agent result
```

保留 DSH session / event / permission 语义。

---

## Milestone 5：Code Mode Behind Bash

实现：

```bash
dsh code ...
```

让 Bash 进入现有 Code Runtime。

---

## Milestone 6：Approval / Side Effects

逐步接入：

- GitHub write；
- 文件危险操作；
- 网络副作用；
- 其他受控动作。

---

# 21. 评测矩阵

每次新增能力，必须保留以下对照：

| Variant | Model-visible tools | Runtime |
|---|---|---|
| A. Official Minimal | exact 2 | baseline |
| B. Enhanced Minimal | exact 2 | enriched shell |
| C. Shell Gateway | exact 2 | enriched + DSH CLI |
| D. Anchored Standard | 2 → full | Standard |
| E. Standard | full | Standard |
| F. Code/PTC | `run_code` + SDK | Code Runtime |

重点比较：

```text
C vs D
C vs E
C vs F
```

---

# 22. 指标

## Trajectory

- first reasoning length；
- time to first action；
- `We need` / `Let me` 等可观测轨迹标志；
- reasoning/tool ratio；
- 长程模式漂移。

## Efficiency

- total reasoning tokens；
- total tokens；
- wall-clock time；
- tool calls；
- duplicate calls；
- stdout/context volume。

## Capability

- task success；
- hidden tests；
- artifact completeness；
- repair rounds；
- self-verification quality。

## Interface Robustness

- shell environment 增强前后；
- `dsh help` hint 前后；
- CLI 数量增加前后；
- 第 10 / 50 / 100 步 trajectory 稳定性。

---

# 23. 一个重要实验：能力增加是否仍然保持 ABI 稳定

目标曲线：

```text
Shell capability count
        ↑
        │
        │      desired:
        │      success ↑
        │      trajectory stable ─────────
        │
        └────────────────────────────→
```

如果随着 CLI 能力增加，模型仍保持 canonical Minimal trajectory，那么项目核心假说得到强支持。

如果 CLI 描述本身也开始显著影响模型，则需要进一步研究：

- discovery 时机；
- stdout 格式；
- help 文本长度；
- lazy loading；
- environment observation conditioning。

---

# 24. 风险

## R1. Bash 命令发现困难

模型不知道环境有什么能力。

Mitigation：

- `dsh help`；
- one-shot post-first-action hint；
- shell MOTD；
- lazy capability discovery。

---

## R2. CLI 变成另一种“大 Tool Catalog”

如果一次性输出 50 个命令及说明，只是把 schema 爆炸换成 help 爆炸。

Mitigation：

> **按需发现，不做全量 preload。**

---

## R3. stdout 污染上下文

复杂 CLI 可能产生巨大输出。

Mitigation：

- structured compact output；
- paging；
- `--json`；
- explicit limits；
- temp artifact + summary。

---

## R4. 绕过权限系统

如果 CLI 直接调用外部程序，可能失去 DSH governance。

Mitigation：

> DSH capability 必须通过 Gateway → ToolRuntime，而不是私自直连。

---

## R5. Shell Injection / Quoting

模型生成的 shell 命令天然存在 quoting 与 injection 风险。

Mitigation：

- sandbox；
- trusted wrapper；
- structured `--json` args；
- capability-specific CLI；
- dangerous command approval。

---

## R6. “Minimal 甜点”假说本身可能部分错误

即使如此，Enhanced Shell 仍然具有独立价值：

- Coding Agent 本来就受益于丰富 CLI；
- Code Mode 仍可复用；
- Tool Gateway 仍是一种可组合的 Harness abstraction。

---

# 25. 成功标准

项目不是以：

> “CoT 看起来像 `We need`”

作为最终成功标准。

真正成功应满足：

1. V4-Pro trajectory 相对 Minimal 保持稳定；
2. Agent 能力覆盖显著扩大；
3. token / latency 不恶化，最好下降；
4. artifact quality 不低于 Standard / PTC；
5. tool governance 完整保留；
6. Shell Gateway 可以扩展到第三方插件；
7. 新能力不要求修改 canonical tool schema。

---

# 26. 项目哲学

这个项目最终想验证的不是一句：

> “Bash is all you need.”

而是一个更一般的 Agent 架构命题：

> **复杂性属于环境；模型接口应该尽可能小、稳定、训练充分。**

也可以写成：

```text
Stable Model ABI
      ×
Rich Environment
      ×
Strong Runtime Governance
      =
Robust Agent System
```

对于当前 V4-Pro，这可能是一个 workaround。

但如果成立，它也可能指向更长期的方向：

> **Agent 的能力扩展不一定意味着模型 Tool Schema 的无限扩张。**

---

# 27. 一句话项目定义

> **在不增加 V4-Pro 模型可见工具 Schema 的前提下，以官方 Minimal 的 `bash + str_replace_editor` 为稳定 Agent ABI，通过增强 Shell 环境、DSH Tool Gateway 与 Code Mode Bridge，逐步获得 Standard/Code Mode 的完整能力。**

---

# 28. 下一步

建议真正开工时从最小闭环开始：

```text
1. 冻结官方 Minimal ABI
2. 建 Enhanced Shell 环境
3. 写一个只读 `dsh` CLI prototype
4. 先包装一个 Web Search 能力
5. 用固定 benchmark A/B：
   Minimal vs Shell Gateway vs Anchored Standard vs PTC
6. 如果 trajectory 不漂，再继续扩张
```

第一阶段不要急着实现 Subagent、Workflow 或复杂审批。

最关键的第一个问题只有一个：

> **在模型始终只看到 canonical `bash + str_replace_editor` 的情况下，我们能否让它自然使用一个新增的 Shell-side capability，同时保持 Minimal 的高效 policy？**

如果答案是“能”，这条路线就值得正式进入长期开发。

---

# 29. DSH Code Mode 相关依据

DSH 当前 Code Mode 已经明确采用“Tool Registry 与模型工具呈现解耦”的设计：

- PTC preset 的官方描述：具备 Standard 的全部能力，但通过 Code Mode SDK 呈现工具，让模型用 TypeScript 程序组合多步操作。
- Code Mode 是 `ToolRuntime` 的一等 presentation mode。
- `code` 模式下，原生工具不直接作为协议 Tool Schema 暴露，而通过 `run_code` + generated SDK 提供。
- 程序内部的工具子调用仍进入完整 ToolRuntime execution pipeline。
- Code Runtime 被实现为独立 capability seam，因此 presentation 与 execution 已经有清晰分层。

因此 Shell Presentation 并不是偏离 DSH 架构，而可以被理解为：

> **在现有 Tool Presentation 抽象上的进一步扩展。**

---

# 30. 备注：证据与假说边界

当前需要明确区分：

## 已观察 / 可直接验证

- DSH 官方存在 Minimal；
- DSH 官方存在 Code Mode；
- Code Mode 已经把 Tool Registry 与模型可见 Tool Schema 解耦；
- V4-Pro 在 Minimal-like 环境下常出现显著不同于丰富工具环境的行为；
- NumPy 安装后，模型已经自然通过 Bash → Python → NumPy 使用数值能力。

## 工作假说

- `0 tools` 与 exact `bash + str_replace_editor` 是两个训练甜点；
- V4-Pro 存在明显 harness / tool-schema over-conditioning；
- Shell Presentation 能保留 Minimal policy，同时获得 Standard 能力；
- 这可能成为 DeepSeek 第一方的短期产品 mitigation。

这些假说必须通过严格 A/B 和长期 trajectory 测试验证，而不能仅凭 CoT 风格下结论。

---

## End

**Project thesis:**

> **Keep the model interface small. Make the world behind it powerful.**
