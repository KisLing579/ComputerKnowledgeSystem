from __future__ import annotations

from dataclasses import replace

from .models import AnimationPatternSpec, SemanticAnimationTemplate, SemanticPhase


def _p(phase_id: str, action: str, cue: str = "", duration: float = 0.7, **parameters) -> SemanticPhase:
    return SemanticPhase(
        phase_id=phase_id,
        action=action,
        narration_cue=cue,
        duration=duration,
        parameters=parameters,
    )


def _t(
    pattern_id: str,
    template_id: str,
    role: str,
    layout: str,
    phases: tuple[SemanticPhase, ...],
    *,
    label_mode: str = "hidden",
    preserve: bool = True,
    description: str = "",
) -> SemanticAnimationTemplate:
    return SemanticAnimationTemplate(
        pattern_id=pattern_id,
        template_id=template_id,
        semantic_role=role,
        layout_hint=layout,
        phases=phases,
        relation_label_mode=label_mode,
        preserve_object_identity=preserve,
        description=description,
    )


# These templates are the engineering realization of the pattern vocabulary
# already defined in Animation_Patterns.  The workbook decides WHICH pattern is
# selected; this file decides HOW that selected pattern unfolds over time.
TEMPLATES: dict[str, SemanticAnimationTemplate] = {
    "ADDRESS_CALC": _t("ADDRESS_CALC", "address_calc", "addressing", "connected_pair",
        (_p("show_inputs", "show_inputs", "给出地址计算的示例输入。", 0.7),
         _p("calculate", "calculate", "按当前寻址规则组合地址。", 0.9),
         _p("show_result", "show_result", "显示计算得到的目标地址。", 0.8)),
        description="Numeric examples for base-offset, indexed, PC-relative and explicit 32-bit PC+4 branch profiles; other profiles retain their schematic."),
    "PURPOSE_REVEAL": _t("PURPOSE_REVEAL", "purpose_reveal", "purpose", "connected_pair",
        (_p("show_subject", "show_subject", "先建立承担功能的对象。", 0.5),
         _p("reveal_purpose", "reveal_purpose", "展开它承担的功能。", 0.8),
         _p("connect_purpose", "connect_purpose", "将对象与功能对应起来。", 0.7))),
    "PRINCIPLE_TO_MECHANISM": _t("PRINCIPLE_TO_MECHANISM", "principle_to_mechanism", "abstraction", "abstract_concrete",
        (_p("show_principle", "show_principle", "先建立设计依据。", 0.5),
         _p("show_mechanism", "show_mechanism", "再呈现采用这一依据的设计。", 0.7),
         _p("bind_principle", "bind_principle", "显示设计与依据的对应。", 0.7))),
    "TABLE_HIGHLIGHT": _t("TABLE_HIGHLIGHT", "table_highlight", "mapping", "connected_pair",
        (_p("show_mapping", "show_mapping", "建立映射表示意。", 0.6),
         _p("locate_entry", "locate_entry", "定位输入对应的表项。", 0.8),
         _p("resolve_output", "resolve_output", "沿表项找到输出。", 0.9))),
    "PUSH_POP": _t("PUSH_POP", "push_pop", "stack", "connected_pair",
        (_p("show_stack", "show_stack", "建立栈示意。", 0.6),
         _p("push_value", "push_value", "入栈并移动栈顶指针。", 0.9),
         _p("pop_value", "pop_value", "出栈并恢复栈顶指针。", 0.9))),
    "REVEAL_INSIDE": _t(
        "REVEAL_INSIDE", "reveal_inside", "part_whole", "inside_container",
        (
            _p("establish_whole", "show_whole", "先建立整体。", 0.6),
            _p("open_structure", "open_container", "再打开整体内部。", 0.6),
            _p("reveal_part", "reveal_part_inside", "内部组成逐一显现。", 0.75),
            _p("emphasize_part", "emphasize_part", "突出当前组成部分。", 0.5),
        ),
    ),
    "ZOOM_IN_NESTING": _t(
        "ZOOM_IN_NESTING", "zoom_in_nesting", "part_whole", "nested_zoom",
        (
            _p("establish_parent", "show_whole", "先看整体位置。", 0.5),
            _p("focus_child", "focus_child", "聚焦其中的子结构。", 0.6),
            _p("zoom_child", "zoom_into_child", "镜头连续进入内部。", 0.9),
        ),
    ),
    "TREE_EXPAND": _t(
        "TREE_EXPAND", "tree_expand", "hierarchy", "branch_tree",
        (
            _p("show_parent", "show_root", "先建立上位概念。", 0.55),
            _p("expand_children", "expand_children", "再展开下一级概念。", 0.9),
            _p("highlight_structure", "highlight_structure", "强调它们的层次关系。", 0.55),
        ),
    ),
    "CATEGORY_GROUP": _t(
        "CATEGORY_GROUP", "category_embed", "classification", "category_embed",
        (
            _p("establish_supertype", "show_category_space", "先建立更大的概念范围。", 0.65),
            _p("introduce_member", "show_member_outside", "再引入被定义对象。", 0.55),
            _p("embed_member", "move_member_into_category", "对象进入这一概念范围。", 0.9),
            _p("emphasize_membership", "emphasize_membership", "强调它属于这一类。", 0.55),
        ),
        description="IS_A is expressed as membership in a larger semantic space, not a labeled arrow.",
    ),
    "RESOURCE_FLOW": _t(
        "RESOURCE_FLOW", "resource_flow", "flow", "flow_between_objects",
        (
            _p("establish_endpoints", "show_endpoints", "先建立资源流动两端。", 0.5),
            _p("create_payload", "create_flow_token", "把资源或数据具象为可移动对象。", 0.45),
            _p("move_payload", "move_token_between", "资源沿连接流向目标。", 0.9),
            _p("target_response", "emphasize_target", "目标接收到资源。", 0.45),
        ),
    ),
    "TOKEN_ENTER_AND_ACT": _t(
        "TOKEN_ENTER_AND_ACT", "token_enter_and_act", "execution", "execution_entry",
        (
            _p("show_executor", "show_executor", "先建立执行单元。", 0.5),
            _p("show_token", "show_execution_token", "把待执行对象表现为令牌。", 0.45),
            _p("enter_executor", "move_token_into_executor", "令牌进入执行单元。", 0.85),
            _p("activate_executor", "activate_executor", "执行单元被触发并开始工作。", 0.65),
        ),
    ),
    "CONTROL_SIGNAL": _t(
        "CONTROL_SIGNAL", "control_signal", "control", "controller_target",
        (
            _p("show_controller", "show_controller", "先明确控制端。", 0.45),
            _p("show_target", "show_target", "再建立被控制对象。", 0.45),
            _p("emit_signal", "emit_control_pulse", "控制信号从控制端发出。", 0.75),
            _p("target_changes", "target_state_change", "目标响应控制信号。", 0.65),
        ),
    ),
    "HIGHLIGHT_TARGET": _t(
        "HIGHLIGHT_TARGET", "highlight_target", "emphasis", "controller_target",
        (
            _p("show_relation_context", "show_endpoints", "建立作用关系。", 0.4),
            _p("highlight_target", "emphasize_target", "突出被作用对象。", 0.6),
        ),
    ),
    "WRITE_IN": _t(
        "WRITE_IN", "write_in", "storage", "storage_write",
        (
            _p("show_storage", "show_storage", "先建立存储区域。", 0.5),
            _p("show_payload", "show_storage_payload", "准备要保存的数据。", 0.45),
            _p("write_payload", "move_payload_into_storage", "数据写入存储区域。", 0.85),
            _p("persist_payload", "settle_payload_in_storage", "数据留在存储单元中。", 0.45),
        ),
    ),
    "READ_OUT": _t(
        "READ_OUT", "read_out", "storage", "storage_read",
        (
            _p("show_storage", "show_storage", "先建立存储区域。", 0.45),
            _p("select_payload", "select_stored_payload", "定位要读取的数据。", 0.45),
            _p("read_payload", "move_payload_out_of_storage", "数据从存储区域读出。", 0.85),
        ),
    ),
    "MORPH": _t(
        "MORPH", "morph", "transform", "transform_pair",
        (
            _p("show_source", "show_source", "先展示转换前的形式。", 0.45),
            _p("transform", "morph_source_to_target", "源对象逐渐变成目标形式。", 1.0),
            _p("settle_target", "emphasize_target", "突出转换结果。", 0.45),
        ),
    ),
    "PIPELINE_TRANSFORM": _t(
        "PIPELINE_TRANSFORM", "pipeline_transform", "transform", "transform_pipeline",
        (
            _p("show_source", "show_source", "先展示输入形式。", 0.45),
            _p("show_mediator", "show_mediator", "中间转换器出现。", 0.45),
            _p("pass_through", "move_source_through_mediator", "输入经过转换器。", 0.9),
            _p("reveal_target", "reveal_transformed_target", "得到新的表示形式。", 0.65),
        ),
    ),
    "ABSTRACT_TO_CONCRETE": _t(
        "ABSTRACT_TO_CONCRETE", "abstract_to_concrete", "abstraction", "abstract_concrete",
        (
            _p("show_abstraction", "show_abstract_layer", "先建立抽象规范。", 0.55),
            _p("reveal_implementation", "reveal_concrete_below", "再显现具体实现。", 0.75),
            _p("bind_layers", "bind_abstract_to_concrete", "把抽象规范与实现对应起来。", 0.65),
        ),
    ),
    "OVERLAY": _t(
        "OVERLAY", "overlay", "abstraction", "overlay_layers",
        (
            _p("show_base", "show_base_layer", "建立底层对象。", 0.45),
            _p("overlay", "overlay_second_layer", "在其上叠加另一层表示。", 0.75),
            _p("compare_alignment", "highlight_alignment", "强调两层之间的对应。", 0.55),
        ),
    ),
    "INTERFACE_BRIDGE": _t(
        "INTERFACE_BRIDGE", "interface_bridge", "interface", "interface_bridge",
        (
            _p("show_upper", "show_upper_layer", "先建立上层。", 0.45),
            _p("show_lower", "show_lower_layer", "再建立下层。", 0.45),
            _p("insert_interface", "insert_interface_between", "接口出现在两层之间。", 0.8),
            _p("bridge_interaction", "pulse_across_interface", "信息通过接口在两层之间衔接。", 0.75),
        ),
    ),
    "LAYER_HIDE_REVEAL": _t(
        "LAYER_HIDE_REVEAL", "layer_hide_reveal", "abstraction", "layer_stack",
        (
            _p("show_layers", "show_layer_stack", "建立多个层次。", 0.55),
            _p("hide_detail", "dim_lower_detail", "抽象层隐藏底层细节。", 0.65),
            _p("reveal_detail", "reveal_lower_detail", "需要时再逐层揭示。", 0.65),
        ),
    ),
    "FACTOR_TO_METRIC": _t(
        "FACTOR_TO_METRIC", "factor_to_metric", "metric", "factors_to_metric",
        (
            _p("show_metric", "show_metric", "先建立被影响的指标。", 0.45),
            _p("show_factors", "show_factor_sources", "多个因素依次出现。", 0.65),
            _p("flow_to_metric", "flow_factors_to_metric", "因素共同作用到指标。", 0.85),
        ),
    ),
    "METRIC_CHANGE": _t(
        "METRIC_CHANGE", "metric_change", "metric", "metric_change",
        (
            _p("show_metric", "show_metric", "建立指标。", 0.4),
            _p("change_input", "change_factor", "改变影响因素。", 0.55),
            _p("animate_metric", "animate_metric_value", "指标随之变化。", 0.75),
        ),
    ),
    "TRADEOFF_GAUGE": _t(
        "TRADEOFF_GAUGE", "tradeoff_gauge", "metric", "tradeoff",
        (
            _p("show_tradeoff", "show_tradeoff_scale", "建立权衡关系。", 0.55),
            _p("apply_constraint", "apply_constraint", "加入约束条件。", 0.55),
            _p("shift_balance", "shift_tradeoff_balance", "系统设计在约束下重新平衡。", 0.75),
        ),
    ),
    "TIMELINE_TREND": _t(
        "TIMELINE_TREND", "timeline_trend", "metric", "timeline",
        (
            _p("draw_timeline", "draw_timeline", "先建立时间轴。", 0.55),
            _p("grow_trend", "grow_trend_curve", "规律随时间逐步呈现。", 0.95),
        ),
    ),
    "SIDE_BY_SIDE": _t(
        "SIDE_BY_SIDE", "side_by_side", "comparison", "side_by_side",
        (
            _p("show_left", "show_left_side", "先展示一侧对象。", 0.45),
            _p("show_right", "show_right_side", "另一侧对象并列出现。", 0.45),
            _p("compare", "compare_sides", "逐项突出二者差异。", 0.85),
        ),
    ),
    "SPLIT_SCREEN": _t(
        "SPLIT_SCREEN", "split_screen", "comparison", "side_by_side",
        (
            _p("split", "split_screen", "画面分为两个并行区域。", 0.55),
            _p("show_both", "show_both_sides", "两种机制同步展示。", 0.65),
            _p("sync_compare", "synchronized_compare", "同步对比它们的表现。", 0.85),
        ),
    ),
    "MECHANISM_OVERLAY": _t(
        "MECHANISM_OVERLAY", "mechanism_overlay", "mechanism", "mechanism_overlay",
        (
            _p("show_structure", "show_structure", "先建立结构。", 0.5),
            _p("show_property", "overlay_mechanism_property", "把被利用的性质覆盖到结构上。", 0.7),
            _p("show_effect", "animate_mechanism_effect", "展示机制利用这一性质产生的效果。", 0.8),
        ),
    ),
    "MULTILEVEL_CACHE_FALLBACK": _t(
        "MULTILEVEL_CACHE_FALLBACK", "multilevel_cache_fallback", "cache", "multilevel_cache_fallback",
        (
            _p("show_levels", "show_cache_levels", "建立多级缓存访问示意。", 0.7),
            _p("probe_l1", "probe_l1", "请求先查询L1。", 0.8),
            _p("fallback_l2", "fallback_l2", "L1未命中，再查询L2。", 0.8),
            _p("fallback_l3", "fallback_l3", "L2未命中，继续查询L3。", 0.8),
            _p("access_memory", "access_memory", "缓存均未命中，才访问主存。", 0.8),
            _p("show_accounting", "show_cache_accounting", "区分局部缺失率、全局缺失率与累计延迟。", 1.2),
        ),
    ),
    "PARALLEL_FLOW": _t(
        "PARALLEL_FLOW", "parallel_flow", "mechanism", "parallel_lanes",
        (
            _p("show_lanes", "show_parallel_lanes", "建立多条并行通道。", 0.55),
            _p("launch_tokens", "launch_parallel_tokens", "多个任务同时推进。", 0.8),
            _p("emphasize_overlap", "emphasize_parallel_overlap", "突出并行发生。", 0.55),
        ),
    ),
    "PIPELINE_STAGES": _t(
        "PIPELINE_STAGES", "pipeline_stages", "mechanism", "pipeline_stages",
        (
            _p("show_stages", "show_pipeline_stages", "建立流水级。", 0.55),
            _p("move_first", "move_token_through_stages", "第一个任务沿流水级推进。", 0.75),
            _p("overlap_tasks", "launch_overlapping_tokens", "后续任务与前一任务重叠执行。", 0.9),
        ),
    ),
    "EVENT_PROPAGATION": _t(
        "EVENT_PROPAGATION", "event_propagation", "causal", "causal_chain",
        (
            _p("show_trigger", "show_trigger", "先出现触发事件。", 0.45),
            _p("propagate", "propagate_event", "事件沿因果链传播。", 0.9),
            _p("show_consequence", "show_consequence", "最终结果显现。", 0.55),
        ),
    ),
    "PATH_REVEAL": _t(
        "PATH_REVEAL", "path_reveal", "teaching", "path_reveal",
        (
            _p("show_start", "show_path_start", "从当前知识点出发。", 0.45),
            _p("reveal_next", "reveal_path_nodes", "按前置关系逐步点亮后续节点。", 0.9),
        ),
    ),
    "BIT_BUILD": _t(
        "BIT_BUILD", "bit_build", "representation", "bit_build",
        (
            _p("show_bits", "show_bit_cells", "先出现单个0和1。", 0.45),
            _p("assemble_bits", "assemble_bit_string", "位单元拼成位串或字段。", 0.85),
        ),
    ),
    "SEQUENCE_REVEAL": _t(
        "SEQUENCE_REVEAL", "sequence_reveal", "representation", "sequence_reveal",
        (
            _p("show_first", "show_sequence_first", "先显示第一项。", 0.4),
            _p("reveal_rest", "reveal_sequence_items", "后续项按顺序出现。", 0.85),
        ),
    ),
    "HIERARCHY_GRADIENT": _t(
        "HIERARCHY_GRADIENT", "hierarchy_gradient", "structure", "hierarchy_gradient",
        (
            _p("show_levels", "show_hierarchy_levels", "建立层次结构。", 0.55),
            _p("apply_gradient", "apply_hierarchy_gradient", "在层次上叠加速度、容量等梯度。", 0.75),
        ),
    ),
    # Runtime fallbacks referenced by Relation_Animation_Map v0.2 but absent in Animation_Patterns.
    "CONNECT_HIGHLIGHT": _t(
        "CONNECT_HIGHLIGHT", "connect_highlight", "connection", "connected_pair",
        (
            _p("show_endpoints", "show_endpoints", "建立两个对象。", 0.45),
            _p("connect", "draw_semantic_connection", "显示它们之间的连接。", 0.6),
            _p("highlight", "highlight_connection", "强调连接关系。", 0.45),
        ),
        label_mode="optional",
    ),
    "PROCESS_FLOW": _t(
        "PROCESS_FLOW", "process_flow", "flow", "horizontal_flow",
        (
            _p("show_steps", "show_process_steps", "建立处理步骤。", 0.5),
            _p("advance", "advance_process_token", "处理过程依次推进。", 0.85),
        ),
    ),
    "RELATION_LINK": _t(
        "RELATION_LINK", "relation_link", "fallback", "connected_pair",
        (
            _p("show_endpoints", "show_endpoints", "建立相关对象。", 0.4),
            _p("link", "draw_labeled_relation", "显示当前知识关系。", 0.6),
        ),
        label_mode="shown",
    ),
    "FADE_REVEAL": _t(
        "FADE_REVEAL", "fade_reveal", "fallback", "center_focus",
        (_p("reveal", "fade_reveal", "展示当前概念。", 0.6),),
    ),
}


for _pid, _cues in {
    "DEPENDENCY_GATE": ("执行所需条件尚未到位，通路被阻断。", "引入所需条件。", "条件满足后开放通路。", "强调该操作对条件的依赖。"),
    "CAPABILITY_UNLOCK": ("先呈现尚未解锁的能力。", "引入使该能力成为可能的条件。", "解除锁定，开放能力。", "能力成为可能，不表示必然发生。"),
    "CAUSE_CHAIN": ("呈现原因或触发状态。", "引入有证据支持的后果。", "沿因果方向传播状态变化。", "强调后果并保留因果箭头。"),
    "PROBLEM_SOLUTION_BRIDGE": ("先呈现问题或瓶颈。", "引入解决机制。", "建立问题与解决机制之间的桥接。", "强调解决或缓解关系。"),
}.items():
    TEMPLATES[_pid] = _t(
        _pid, _pid.lower(), "causal", "connected_pair",
        tuple(_p(phase, phase, cue, duration) for phase, cue, duration in
              zip(("establish", "prepare", "activate", "settle"), _cues, (0.6, 0.65, 1.1, 0.55))),
    )


for _pid in (
    'CLOCK_EDGE_UPDATE', 'CONTROL_ASSERT', 'FSM_TRANSITION', 'MICROCODE_DISPATCH',
    'DATAPATH_TRACE', 'RESOURCE_REUSE_CYCLE', 'PIPELINE_OVERLAP', 'FORWARDING_BYPASS',
    'STALL_BUBBLE_INSERT', 'PIPELINE_FLUSH', 'BRANCH_PREDICT_RECOVER',
    'MULTI_ISSUE_PACK', 'OOO_SCHEDULE_COMMIT', 'SPECULATE_VALIDATE_ROLLBACK',
):
    TEMPLATES[_pid] = _t(_pid, 'processor_trace', 'execution', 'connected_pair',
        tuple(_p(f'trace_{i}', 'processor_trace',
                 ('建立执行示例。', '展示控制或数据推进。', '展示状态变化。', '观察执行结果。')[i],
                 .8, trace_frame=i) for i in range(4)),
        description='Bounded illustrative processor trace; not a full profile-specific simulator.')


for _pid in (
    'CACHE_ADDRESS_DECODE', 'CACHE_LOOKUP_HIT_MISS', 'CACHE_MISS_REFILL',
    'CACHE_WRITE_POLICY', 'ASSOCIATIVITY_LOOKUP', 'REPLACEMENT_SELECT',
    'ADDRESS_TRANSLATE', 'TLB_LOOKUP_REFILL', 'PAGE_FAULT_SWAP',
    'BANK_INTERLEAVE_TRANSFER', 'LOCALITY_REUSE_TRACE', 'HIERARCHY_DESCENT',
    'PROTECTION_MODE_SWITCH', 'MISS_3C_CLASSIFY',
):
    TEMPLATES[_pid] = _t(_pid, 'memory_trace', 'memory', 'connected_pair',
        tuple(_p(f'trace_{i}', 'memory_trace',
                 ('建立访存示例。', '检查映射及访问条件。', '展示状态变化。', '观察访问结果。')[i],
                 .8, trace_frame=i) for i in range(4)),
        description='Illustrative memory trace; fixed cache geometry and page size are explicitly labeled.')


class AnimationGrammar:
    """Resolve workbook pattern IDs into semantic micro-scene templates."""

    def template_for(self, pattern: str | AnimationPatternSpec) -> SemanticAnimationTemplate:
        pid = pattern.pattern_id if isinstance(pattern, AnimationPatternSpec) else str(pattern)
        if pid in TEMPLATES:
            return TEMPLATES[pid]
        return replace(TEMPLATES["RELATION_LINK"], pattern_id=pid)

    def validate_pattern_ids(self, pattern_ids: set[str]) -> tuple[str, ...]:
        return tuple(sorted(pid for pid in pattern_ids if pid not in TEMPLATES))
