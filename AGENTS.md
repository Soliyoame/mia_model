# Repository Guidelines

## Communication & Work Style

默认用中文和用户沟通。回答判断类问题时先给明确结论，再给依据；如果用户说“先别改代码”，只做只读分析。动手修改前先说明将改哪些文件和原因。保持改动小而直接，不做无关重构，不覆盖用户已有修改。

## Project Structure & Module Organization

本仓库实现 PCV-MIA，即面向 RAG 知识库的成员推理攻击流程。运行代码在 `src/`，按职责分为 `data/`、`prepare/`、`rag/`、`fact_extraction/`、`paired_claims/`、`query_generation/`、`parsing/`、`scoring/`、`baselines/`、`defenses/`、`evaluation/`、`llm/` 和 `utils/`。流水线入口在 `scripts/01_preprocess_data.py` 到 `scripts/15_generate_report.py`。配置集中在 `configs/`，测试在 `tests/`。`思路v*.txt`、`baseline.txt`、`thesislogic.txt` 是研究记录，不是运行入口。

## Architecture Invariants

必须维护 PCV-MIA 的核心边界：只有 `KB_Member` 可以进入 RAG index；`True_Non_Member`、`Spoof_Seed`、`Reserve` 和 `Spoofed_Non_Member` 都不能进入 `indexes/`。Attack benchmark 应固定并保留 hash。`Spoofed_Non_Member` 只是 hard negative 对照组，由 `PCV_ENABLE_SPOOFED_NONMEMBER=true` 控制，不是主方法必需部分。当前脚本多了 `09_filter_stealth_queries.py`，因此以当前 `scripts/` 和 README 的编号为准。

## Build, Test, and Development Commands

- `pip install -r requirements.txt`: 安装核心依赖。
- `python -B -m unittest discover -s tests`: 运行单元测试，避免写入 `.pyc`。
- `python -m compileall src scripts tests`: 做语法检查；若 Windows 缓存权限异常，改用内存编译方式。
- `python scripts/01_preprocess_data.py --config configs/data_config.yaml --datasets enron --force`: 预处理数据。
- `python scripts/10_run_rag_and_llm_only.py --dataset enron --config configs/rag_config.yaml --force`: 在前置产物存在后运行 RAG 与 LLM-only 双路推理。

## Coding Style & Naming Conventions

使用 Python 3.10+，4 空格缩进，保持类型标注。函数、变量、模块和 JSON 字段使用 `snake_case`。新增行为优先通过 `configs/*.yaml` 暴露，不把模型名、路径、阈值硬编码进逻辑。保持 numbered scripts 稳定，因为 README、输出路径和实验复现依赖这些入口。

## Testing Guidelines

测试框架是 `unittest`。新增测试放在 `tests/`，方法名使用 `test_<expected_behavior>`。优先覆盖数据隔离、RAG 边界、claim/query 构造、stance parsing、PCV scoring、resume/force 语义。涉及 LLM 的修改应 mock 或隔离 API client，不依赖真实网络调用。

## Security & Configuration Tips

不要提交 `.env`、API key、私有数据集或大型生成产物。LLM 调用统一走 OpenAI-compatible 配置，凭据来自 `PCV_VICTIM_*` 和 `PCV_SIBLING_*` 环境变量。修改评分、查询生成或生成配置后，应从受影响阶段重新跑，避免新旧中间结果混用。

## Commit & PR Guidance

当前 git 历史只有初始提交，未形成强制格式。建议使用简短 imperative subject，例如 `scoring: adjust unknown penalty`。PR 或变更说明应写清影响的 pipeline 阶段、配置变化、是否产生新 artifacts，以及已运行的验证命令。
