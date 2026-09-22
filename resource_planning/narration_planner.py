from __future__ import annotations

from representation.models import RepresentationNode, RepresentationRelation


class NarrationPlanner:
    """Deterministic, KG-grounded narration for visual beats.

    This is intentionally modest: it never invents domain facts.  It uses the
    node definition stored in KG_Nodes plus the relation semantics already in
    the ExplanationPlan.  A later LLM narration layer can replace this without
    changing StoryPlan or rendering interfaces.
    """

    def definition_sentence(self, node: RepresentationNode) -> str:
        if node.definition:
            return f"{node.name}：{node.definition}"
        return f"先看{node.name}这个概念。"

    def relation_sentence(
        self,
        rel: RepresentationRelation,
        nodes_by_id: dict[str, RepresentationNode],
    ) -> str:
        src = nodes_by_id.get(rel.source_node_id)
        dst = nodes_by_id.get(rel.target_node_id)
        stored_src = nodes_by_id.get(rel.stored_source_node_id)
        stored_dst = nodes_by_id.get(rel.stored_target_node_id)
        s = src.name if src else rel.source_node_id
        d = dst.name if dst else rel.target_node_id
        ss = stored_src.name if stored_src else rel.stored_source_node_id
        sd = stored_dst.name if stored_dst else rel.stored_target_node_id
        mediator = nodes_by_id.get(rel.mediator_node_id) if rel.mediator_node_id else None
        m = mediator.name if mediator else ""
        rt = rel.relation_type

        if rt == "IS_A":
            return f"{ss}属于{sd}这一更大的概念范围。"
        if rt == "PART_OF":
            return f"{ss}是{sd}的一部分。"
        if rt == "CONTAINS":
            return f"{ss}包含{sd}。"
        if rt == "TRANSFORMS_TO":
            return f"{ss}经过{m}转换为{sd}。" if m else f"{ss}转换为{sd}。"
        if rt == "EXECUTES":
            return f"{ss}执行{sd}。"
        if rt == "CONTROLS":
            return f"{ss}向{sd}发出控制信号，并决定它怎样工作。"
        if rt == "MANAGES":
            return f"{ss}负责管理{sd}。"
        if rt == "STORES":
            return f"{ss}用于存放{sd}。"
        if rt == "USES":
            return f"{ss}使用{sd}来完成当前功能。"
        if rt == "INTERFACES_WITH":
            return f"{s}和{d}通过接口关系衔接。"
        if rt == "IMPLEMENTS":
            return f"{ss}实现了{sd}所规定的抽象或规范。"
        if rt == "AFFECTS":
            return f"{ss}会影响{sd}。"
        if rt == "EXPLOITS":
            return f"{ss}利用{sd}这一性质或机制。"
        if rt == "CONSTRAINS":
            return f"{ss}会约束{sd}的设计空间。"
        if rt == "DESCRIBES":
            return f"{ss}描述了{sd}的变化规律。"
        if rt == "CONTRASTS_WITH":
            return f"把{s}和{d}并列起来比较，更容易看出差异。"
        if rt == "CONNECTS":
            return f"{ss}连接{sd}。"
        if rt == "TRIGGERS":
            return f"{ss}会触发{sd}。"
        if rt == "PREREQUISITE_OF":
            return f"理解{ss}是继续学习{sd}的前提。"
        verbs = {
            "CAUSES": "导致", "RESULTS_IN": "带来", "ENABLES": "支持",
            "REQUIRES": "需要", "BASED_ON": "基于", "HAS_FUNCTION": "具有功能：",
            "SOLVES": "解决", "MOTIVATED_BY": "源于", "PREVENTS": "防止",
            "DEPENDS_ON": "依赖", "PRODUCES": "产生", "READS": "读取",
            "WRITES": "写入", "TRANSFERS_TO": "传送到",
        }
        if rt in verbs:
            return f"{ss}{verbs[rt]}{sd}。"
        return f"{ss}与{sd}存在关联。"

    def phase_sentence(
        self,
        rel: RepresentationRelation,
        phase_id: str,
        nodes_by_id: dict[str, RepresentationNode],
        cue: str,
    ) -> str:
        # Keep the current KG fact visible throughout its animation phases.
        return self.relation_sentence(rel, nodes_by_id)
