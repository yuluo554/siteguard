# benchmarks/ 基准说明

内置基准设计（详见 plan/06 与 README 评测表）：

- **输入解析 F1**：`siteguard.datagen` 以 seed=42 生成带真值语料，
  `siteguard.benchmark.run_eval` 对比规则通路输出与真值，微平均 P/R/F1；
- **分级准确率**：判定等级 vs 生成器期望等级；
- **误报率**：正常记录被误判为隐患的计数（目标 0）。

纪律：基准必须**零 API 依赖可重复**（纯规则通路）；指标随 README 交付。
M1 起增加"注入已知差异的配对语料"端到端检出率/误报率基准。
