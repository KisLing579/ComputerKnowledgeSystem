# 学生知识状态与学习证据 v1

已接入 resource_planning.pipeline：状态接口、模拟数据与前置展开策略参与最终解释和 StoryPlan；不实现或训练知识追踪模型，不写入学生状态或 Neo4j。

## 数据关系

```text
Student ──< StudentNodeState >── KnowledgeNode
Student ──< Interaction >── LearningItem
LearningItem ──< ItemNodeMapping >── KnowledgeNode
Interaction ──< NodeEvidence >── KnowledgeNode
NodeEvidence ──> 状态估计器 ──> StudentNodeState + StateHistory
```

知识图谱保存公共概念与教学依赖；学生状态独立存储，通过 node_id 关联。初期使用 JSON；后续可迁移到关系数据库。读取状态缺失时返回 unknown，不修改数据库。不同学生之间禁止共享状态。

## StudentNodeState

当前快照唯一键为 `(student_id, node_id)`；一个发布中的模型负责当前快照，多个实验模型的历史快照应另带 model_run_id 区分。

沿用用户提出的全部字段。mastery_prob 为指定知识追踪模型估计的掌握概率，不是正确率；无模型估计时为 null。uncertainty 取 [0,1]、越高越不确定，由模型适配器定义和校准，不能直接等同于 1 - mastery_prob。forgetting_risk 为独立遗忘估计，缺失为 null，不假装已经评估遗忘。

evidence_count 是归因到本节点、去重后参与评估的证据数量；positive_evidence / negative_evidence 只统计可判定的正负证据，因此二者之和可以小于 evidence_count。普通视频曝光只记录接触，不计为掌握证据。

新增字段：

- last_mastered_at：最近一次达到掌握标准的时间，forgotten 的必要历史依据。
- misconception_ids：关联独立错误概念目录，misconceived 需要诊断依据。
- is_simulated：假设数据显式为 true；model_name=mock，不能标成 BKT。
- state_version：数据结构版本，与 model_version 分开。

时间用带时区的 ISO 8601；持久化统一 UTC。updated_at 是快照计算时间，last_interaction_at 是最近学习事件时间，不能混用。历史记录建议增加 snapshot_id、model_run_id、policy_version、evidence_watermark、input_evidence_ids，支持重算和追溯。

## 标签与教学动作

| 标签 | 含义 | 当前默认动作 |
|---|---|---|
| unknown | 尚无足够证据 | 有限解释、继续查必要前置 |
| introduced | 接触过，未形成掌握证据 | 解释，不能因看过视频跳过 |
| learning | 正在形成掌握 | 解释并展开必要前置 |
| mastered | 基本掌握 | 满足可靠性条件时仅引用并停止向上展开 |
| unstable | 掌握但不稳定 | 复习并检查前置 |
| forgotten | 曾掌握、当前可能遗忘 | 恢复性复习并检查前置 |
| misconceived | 存在稳定错误概念 | 纠错并检查前置 |

标签不是七档概率区间。未来标签推导建议优先检查已诊断误概念、历史掌握与遗忘，再判断掌握稳定性，最后区分 learning / introduced / unknown。一次错误不能推出 misconceived；低概率本身不能推出 forgotten。状态估计与标签推导需独立版本化，本阶段直接使用显式模拟标签。

当前 mastered 停止展开需同时满足：掌握概率 >= 0.85、不确定性 <= 0.20、遗忘风险 <= 0.20、证据数 >= 3、快照在规划时间之前且不超过 30 天。这些是可配置演示阈值，未经教育实验校准。过期快照仅触发复习，不擅自把持久化标签改成 forgotten。

## 原始事件 Interaction

保留用户提供的 interaction_id、student_id、session_id、item_id、event_type、timestamp、response、is_correct、score、response_time_ms、attempt_no、hint_count、completed、behavior_data、data_version。

约束：interaction_id 全局唯一并用于幂等接入；timestamp 为事件发生时间，增加 received_at 记录到达时间；event_type 首期可用 answer / video_progress / video_complete / video_pause / video_replay。非答题事件的 is_correct、score、response、attempt_no 可以为 null，不能用 false 表示“没有评分”。分数约定 [0,1]；时长非负；答题次数 >= 1。原始事件追加保存，纠正通过新事件的 supersedes_interaction_id 表达。

视频事件还应记录 video_id、segment_id、position_ms、watched_intervals_ms、playback_rate。观看覆盖率使用观看区间并集，不能累加重播时长；pause/replay 只是行为信号，不自动解释为掌握或不会。

## 学习项与节点映射 ItemNodeMapping

唯一键 `(item_id, item_version, node_id, segment_id)`，segment_id 无分段时使用空字符串。字段包括 mapping_version、role（primary/supporting）、assessment_weight、start_ms、end_ms。题目映射相当于知识组件映射，视频映射限定到时间片段。教材章节粒度与可评估技能粒度可能不同，之后可增加 knowledge_component_id 并映射到 KG 节点。

示例：

```json
{
  "item_id": "Q_CACHE_004",
  "item_version": "v1",
  "mapping_version": "mock-v1",
  "node_id": "CO033",
  "segment_id": "",
  "role": "primary",
  "assessment_weight": 1.0,
  "is_simulated": true
}
```

## 节点证据 NodeEvidence

原始事件不直接更新所有关联节点。评分/归因层产生下列记录，唯一键建议 `(interaction_id, node_id, attribution_version)`：

```json
{
  "evidence_id": "NE000128_CO033",
  "interaction_id": "INT000128",
  "student_id": "STU001",
  "node_id": "CO033",
  "evidence_type": "assessment",
  "polarity": "positive",
  "observed_score": 0.8,
  "reliability": 0.6,
  "attribution_weight": 1.0,
  "misconception_ids": [],
  "mapping_version": "mock-v1",
  "attribution_version": "mock-v1",
  "is_simulated": true
}
```

示例数值仅演示结构，不是对给定答案的真实评分。evidence_type 可为 assessment / exposure / diagnostic，polarity 可为 positive / negative / neutral。hint_count、重试和响应时间保留给评分模型处理，不先硬编码折扣公式。多节点题需要分步骤/分知识点评分，无法区分时保留低可靠度或不作单节点判断，避免一次回答给每个节点都增加一条独立成功证据。

## Knowledge tracing 接口与演进

估计器消费按事件时间排序并去重的 NodeEvidence，输出概率和模型诊断；标签派生器输出标签；规划器只读 StudentNodeState。乱序事件需要从历史检查点重放，不按到达顺序直接累加；同一事件的新归因版本替代旧版，不能重复计数。

经典 BKT 使用初始掌握、学习转移、猜测与失误等参数，基于观测更新隐含掌握状态。七种标签、误概念诊断和视频行为不应声称都是经典 BKT 的直接输出；不确定性与遗忘模块单独定义。起步采用可解释的 BKT 适配器，收集数据后再评估支持遗忘或更多特征的模型。

原始研究：[Corbett & Anderson, 1995](https://perso.liris.cnrs.fr/pierre-antoine.champin/2014/m2iade-ia2/_static/893CorbettAnderson1995.pdf)。本文的七标签和展开阈值是项目设计，不是论文结论。

## 前置展开与演示

`expand_prerequisites` 针对单个核心概念沿入边展开；默认 required，recommended 可显式开启。深度默认 3、节点预算 20；稳定掌握的前置节点保留引用并停止递归。核心概念始终保留。去重、循环和预算截断均有输出；被截断不代表前置已满足。每个核心概念单独调用，后续统一规划器再做跨子图共享和总预算管理。

运行 `python -m student_model.demo`，使用当前工作簿真实依赖，产生 `data/student_model_demo/states.json` 和 `expansion_plans.json`。七名模拟学生分别处于七种局部性状态，对高速缓存 CO033 的前置展开进行比较。依赖表可能没有某个节点的更深前序，因此不同动作不保证节点数不同，禁止为展示差异编造 KG 关系。

## Pipeline 使用

证据修复：`--planning-rounds 3`（允许 1–5）控制检查与子问题重规划轮数；该参数不是全流程 LLM 请求数上限。原问题的要求固定。子问题证据不足时，规划器根据现有证据改写、替换、拆分或删除，记录 replaces / removed 和理由，再检索与检查新子问题。新问题使用新 ID，重新提取其自身要求；不将失败的旧子问题升级为用户必须满足的要求。原问题本身不足仍按固定缺口补查。请求/格式失败不伪装成事实缺口。记录在 `planning_attempts.json.revisions`，最终版本保存在 `reasoning_plan.json.final_subquestions` 并传给教学规划。

教学审核若返回明确语义问题，将意见附到检索问题，补查后重新验证原问题要求并重建解释及学生前置场景；不会绕过答案门禁。strict / partial 按原问题要求计算覆盖率；最终子问题方案仍须通过检查，无法找到可用方案时停止。格式错误与服务异常由教学模块自身的有界重试处理。`teaching_plan.json.planning_attempts` 保留教学尝试记录。

```powershell
.venv/Scripts/python.exe -m resource_planning.pipeline "高速缓存为什么能提高访存性能？" --reasoning llm --student-id STU004 --student-states data/student_model_demo/states.json --state-as-of 2026-09-08T12:00:00Z --out-dir out_student --no-manim-script
```

默认开启前置展开；未指定学生文件时使用 unknown 状态，student_id 默认 anonymous。状态文件给定时必须包含指定学生，否则启动报错。正常运行不指定 --state-as-of，使用当前 UTC；指定时间用于可复现演示，不重新计算模型状态。

- `--no-prerequisites`：关闭本次前置展开。
- `--prerequisite-depth 3`：单个核心概念的最大展开深度。
- `--prerequisite-max-nodes 20`：单子图节点预算，同时限制整堂课新增前置概念总数。
- `--include-recommended-prerequisites`：同时考虑推荐依赖。

先执行原有答案覆盖检查，再做前置展开，保留原答案事实树。依赖和定义读取 config 指定的同一工作簿，避免将教学边混入事实候选；部署时应保持 Neo4j 与工作簿版本一致。每条原问题、LLM 子问题和覆盖补查记录保留独立来源，通过 QuestionAnalyzer 的直接提及节点确定核心，不把模糊召回节点全部展开。

新增 `prerequisite_plan.json` 保存各子问题候选路径、每个核心节点的子图、状态快照、动作、共享片段和截断原因。工作簿缺少依赖表时状态为 unavailable；未找到明确核心节点、缺少定义或预算截断时显式记录，不能声称前置知识完整。

新增前置概念按前序顺序置于答案之前，共享节点只生成一次场景；已掌握节点生成简短引用，其他节点使用工作簿定义。当前 misconceived 仅做定义复核，不生成未经证据支持的特定误概念诊断或纠错材料。后续可接入误概念目录与习题。LLM 教学精简仅处理答案场景，前置场景作为受保护前缀恢复，不能被删减或重排。学生状态只读。
