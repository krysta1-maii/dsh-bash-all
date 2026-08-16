# 分析报告

每个 `logs/<name>.jsonl` 对应 `reports/<name>/`；12 用例的汇总见
`reports/cases-step0-summary.md`。


环境基线：

- Step 0：`reports/step0-environment.md`
- Step 0.1（bash 工具可调用包体快照）：`reports/step0.1-environment.md`
- Step 0.1 包体逐项探测 CSV 与重跑脚本：
  `reports/step0.1-environment/`
重新生成单个日志报告：

```bash
python3 analyze_logs.py logs/双叉臂测试.jsonl --no-txt
```

重新生成 12 用例报告：

```bash
for f in logs/cases/step0/*.jsonl; do
  python3 analyze_logs.py "$f" --no-txt
done

python3 analyze_logs.py logs/cases/step0 -o reports/cases/step0/_merged --no-txt
```

注意：DSH 日志中的流式 chunk 会被分析器跳过，只统计正式的
`tool/call` 与 `tool/result` 事件。
