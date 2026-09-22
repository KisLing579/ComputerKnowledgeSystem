from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from kg.query import NodeMatch
from kg.aliases import aliases_for

from .models import ExplanationIntent, QuestionAnalysis


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[\s\-—_，。！？、；：,.!?;:()（）\[\]{}<>《》/]+", "", text)


def _variants(match: NodeMatch) -> list[str]:
    return aliases_for(match.name, match.name_en)


@dataclass(frozen=True)
class _Mention:
    node: NodeMatch
    start: int
    end: int
    variant: str


_INTENT_PROFILES: dict[ExplanationIntent, tuple[tuple[str, ...], tuple[str, ...]]] = {
    ExplanationIntent.TRANSFORMATION_EXECUTION: (
        ("TRANSFORMS_TO", "EXECUTES", "USES", "IMPLEMENTS", "INTERFACES_WITH"),
        ("AFFECTS", "DESCRIBES", "CONTRASTS_WITH"),
    ),
    ExplanationIntent.COMPOSITION: (
        ("PART_OF", "IS_A", "CONTAINS"),
        ("AFFECTS", "DESCRIBES", "TRANSFORMS_TO"),
    ),
    ExplanationIntent.INTERFACE_ROLE: (
        ("INTERFACES_WITH", "PART_OF", "IMPLEMENTS", "USES"),
        ("AFFECTS", "DESCRIBES", "TRIGGERS"),
    ),
    ExplanationIntent.ROLE_FUNCTION: (
        ("CONTROLS", "MANAGES", "INTERFACES_WITH", "EXECUTES", "TRANSFORMS_TO", "IMPLEMENTS", "USES", "STORES"),
        ("AFFECTS", "DESCRIBES", "CONTRASTS_WITH"),
    ),
    ExplanationIntent.RELATION_STRUCTURE: (
        ("PART_OF", "CONTROLS", "MANAGES", "INTERFACES_WITH", "USES", "EXECUTES", "STORES", "IS_A", "CONTRASTS_WITH"),
        ("AFFECTS", "DESCRIBES"),
    ),
    ExplanationIntent.CAUSAL_MECHANISM: (
        ("TRIGGERS", "CONTROLS", "EXECUTES", "USES", "IMPLEMENTS", "EXPLOITS", "TRANSFORMS_TO"),
        ("IS_A", "CONTRASTS_WITH"),
    ),
    ExplanationIntent.PERFORMANCE: (
        ("AFFECTS", "CONSTRAINS", "EXPLOITS", "DESCRIBES", "USES"),
        ("IS_A",),
    ),
    ExplanationIntent.COMPARISON: (
        ("CONTRASTS_WITH", "IS_A", "PART_OF", "DESCRIBES"),
        ("TRANSFORMS_TO", "TRIGGERS"),
    ),
    ExplanationIntent.DEFINITION: (
        ("IS_A", "PART_OF", "INTERFACES_WITH", "USES"),
        ("AFFECTS", "TRIGGERS"),
    ),
    ExplanationIntent.GENERAL: (
        ("PART_OF", "USES", "INTERFACES_WITH", "IMPLEMENTS", "TRANSFORMS_TO", "EXECUTES"),
        (),
    ),
}


class QuestionAnalyzer:
    """Deterministic question analyzer for the first KG-validation loop.

    It detects a coarse intent and anchors from the already entity-linked node
    candidates. The goal is observability: every decision has a simple rationale
    and can later be replaced by embeddings/LLM classification.
    """

    def analyze(self, question: str, matches: list[NodeMatch]) -> QuestionAnalysis:
        intent, intent_reason = self._detect_intent(question)
        mentions = self._find_direct_mentions(question, matches)

        source_ids, target_ids, focus_ids, anchor_reason = self._select_anchors(
            question=question,
            intent=intent,
            matches=matches,
            mentions=mentions,
        )

        preferred, discouraged = _INTENT_PROFILES[intent]
        confidence = self._confidence(intent, mentions, source_ids, target_ids)
        rationale = tuple([intent_reason, *anchor_reason])

        return QuestionAnalysis(
            question=question,
            intent=intent,
            source_ids=tuple(source_ids),
            target_ids=tuple(target_ids),
            focus_ids=tuple(focus_ids),
            preferred_relations=preferred,
            discouraged_relations=discouraged,
            direct_mention_ids=tuple(m.node.id for m in mentions),
            confidence=round(confidence, 3),
            rationale=rationale,
        )

    def _detect_intent(self, question: str) -> tuple[ExplanationIntent, str]:
        q = _norm(question)

        # Specific patterns before generic "为什么" mechanism questions.
        transformation_words = (
            "变成", "转换成", "转化成", "翻译成", "编译成", "生成", "形成", "如何执行", "怎样执行", "怎么执行"
        )
        if any(w in q for w in transformation_words) or ("执行" in q and "指令" in q):
            return ExplanationIntent.TRANSFORMATION_EXECUTION, "检测到转换/执行类问法"

        if any(w in q for w in ("由哪些", "由什么", "包含什么", "包括什么", "组成", "结构是什么")):
            return ExplanationIntent.COMPOSITION, "检测到组成/结构类问法"

        if any(w in q for w in ("性能", "快", "慢", "吞吐", "延迟", "效率", "提高速度", "为什么更快")):
            return ExplanationIntent.PERFORMANCE, "检测到性能/效率类问法"

        if any(w in q for w in ("区别", "不同", "相比", "比较", " versus ", "vs")):
            return ExplanationIntent.COMPARISON, "检测到比较类问法"

        if any(w in q for w in ("分别起什么作用", "起什么作用", "作用是什么", "有什么作用", "负责什么")):
            return ExplanationIntent.ROLE_FUNCTION, "检测到角色/功能类问法"

        if any(w in q for w in ("之间是什么关系", "之间有何关系", "是什么关系", "处在什么位置", "位于哪里", "经过哪些层", "有哪些层")):
            return ExplanationIntent.RELATION_STRUCTURE, "检测到关系结构/层次位置类问法"

        if "接口" in q or "interface" in q:
            return ExplanationIntent.INTERFACE_ROLE, "检测到接口/边界角色类问法"

        if any(w in q for w in ("为什么", "为何", "原因", "怎么工作", "如何工作", "机制", "过程")):
            return ExplanationIntent.CAUSAL_MECHANISM, "检测到原因/机制类问法"

        if any(w in q for w in ("是什么", "什么是", "定义", "指什么")):
            return ExplanationIntent.DEFINITION, "检测到定义类问法"

        return ExplanationIntent.GENERAL, "未命中特定意图，使用通用解释模式"

    def _find_direct_mentions(self, question: str, matches: list[NodeMatch]) -> list[_Mention]:
        q = _norm(question)
        mentions: list[_Mention] = []
        for match in matches:
            best: _Mention | None = None
            for variant in _variants(match):
                vn = _norm(variant)
                if not vn:
                    continue
                pos = q.find(vn)
                if pos >= 0:
                    candidate = _Mention(match, pos, pos + len(vn), variant)
                    if best is None or len(vn) > len(_norm(best.variant)):
                        best = candidate
            if best:
                mentions.append(best)
        mentions.sort(key=lambda x: (x.start, -len(_norm(x.variant)), -x.node.score))
        return mentions

    def _select_anchors(
        self,
        *,
        question: str,
        intent: ExplanationIntent,
        matches: list[NodeMatch],
        mentions: list[_Mention],
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        rationale: list[str] = []
        q = _norm(question)
        direct = [m.node for m in mentions]
        direct_ids = {m.id for m in direct}

        source: list[str] = []
        target: list[str] = []
        focus: list[str] = []

        # Special but generalizable execution grammar: "CPU ... 执行 ... 指令".
        processor_matches = [
            m for m in direct
            if m.semantic_type in {"structure", "system"}
            and any(k in _norm(f"{m.name}{m.name_en}") for k in ("cpu", "processor", "处理器"))
        ]
        instruction_matches = [
            m for m in direct
            if "指令" in _norm(f"{m.name}{m.name_en}") or "instruction" in _norm(f"{m.name}{m.name_en}")
        ]

        if intent == ExplanationIntent.TRANSFORMATION_EXECUTION:
            # Source: first directly-mentioned program/code/data concept if possible.
            source_candidates = [
                m.node for m in mentions
                if m.node.semantic_type in {"artifact", "concept"}
                and any(k in _norm(f"{m.node.name}{m.node.name_en}") for k in ("程序", "program", "代码", "code", "语言", "language"))
            ]
            if source_candidates:
                source.append(source_candidates[0].id)
                rationale.append(f"源锚点选择直接提及的程序/代码概念 {source_candidates[0].id}")

            if processor_matches and instruction_matches and "执行" in q:
                target.append(processor_matches[0].id)
                focus.append(instruction_matches[0].id)
                rationale.append(f"检测到执行语义：目标锚点={processor_matches[0].id}，必经/关注节点={instruction_matches[0].id}")
            else:
                # For A -> B conversion wording, use first mention after the verb as target.
                verb_positions = [q.find(v) for v in ("变成", "转换成", "转化成", "翻译成", "编译成", "生成") if q.find(v) >= 0]
                cut = min(verb_positions) if verb_positions else -1
                if cut >= 0:
                    after = [m.node for m in mentions if m.start > cut and m.node.id not in source]
                    if after:
                        target.append(after[0].id)
                        rationale.append(f"目标锚点选择转换词之后的直接提及概念 {after[0].id}")

        elif intent == ExplanationIntent.COMPOSITION:
            # Whole concept is usually the first/strongest direct mention.
            if direct:
                source.append(direct[0].id)
                rationale.append(f"组成类问题以被询问整体 {direct[0].id} 为源锚点")

        elif intent == ExplanationIntent.INTERFACE_ROLE:
            # Interface questions are centered on an interface/abstraction node,
            # not on an arbitrary source-target pair. Prefer a directly mentioned
            # concept whose name/definition itself denotes an interface.
            interface_candidates = []
            for m in direct:
                text = _norm(f"{m.name}{m.name_en}{m.definition}")
                if any(k in text for k in ("接口", "interface", "isa", "abi")):
                    interface_candidates.append(m)
            if interface_candidates:
                source.append(interface_candidates[0].id)
                rationale.append(f"接口类问题以接口概念 {interface_candidates[0].id} 为中心锚点")
            elif direct:
                source.append(direct[0].id)
                rationale.append(f"未识别专门接口节点，使用直接提及概念 {direct[0].id} 为中心锚点")

            # Directly mentioned software/hardware concepts are useful context,
            # but are not forced into source/target anchors; the structurer will
            # verify actual INTERFACES_WITH neighbors from the KG.
            contextual = [
                m.id for m in direct
                if any(k in _norm(f"{m.name}{m.name_en}") for k in ("软件", "software", "硬件", "hardware"))
            ]
            focus.extend(contextual[:3])
            if contextual:
                rationale.append("检测到软/硬件上下文，将其作为接口解释的关注节点")

        elif intent == ExplanationIntent.ROLE_FUNCTION:
            if direct:
                source.append(direct[0].id)
                focus.extend(m.id for m in direct[1:])
                rationale.append(f"角色/功能问题以 {direct[0].id} 为中心概念")

        elif intent == ExplanationIntent.RELATION_STRUCTURE:
            # Explicit “从A到B” wording is stronger than mention order.
            from_pos = q.find("从")
            to_pos = q.find("到", from_pos + 1) if from_pos >= 0 else -1
            from_mention = next((m.node for m in mentions if from_pos >= 0 and m.start > from_pos), None)
            to_mention = next((m.node for m in mentions if to_pos >= 0 and m.start > to_pos), None)
            if from_mention is not None and to_mention is not None and from_mention.id != to_mention.id:
                source.append(from_mention.id)
                target.append(to_mention.id)
                focus.extend(m.id for m in direct if m.id not in {from_mention.id, to_mention.id})
                rationale.append(f"检测到从A到B层次问法：{from_mention.id} -> {to_mention.id}")
            elif direct:
                source.append(direct[0].id)
                focus.extend(m.id for m in direct[1:])
                rationale.append(f"关系结构问题以首个直接概念 {direct[0].id} 为局部根，其余直接概念作为关注节点")

        elif intent == ExplanationIntent.PERFORMANCE:
            perf = [m for m in direct if "性能" in _norm(f"{m.name}{m.name_en}") or "performance" in _norm(f"{m.name}{m.name_en}")]
            non_perf = [m for m in direct if m not in perf]
            if non_perf:
                source.append(non_perf[0].id)
            if perf:
                target.append(perf[0].id)
            if source or target:
                rationale.append("性能类问题优先建立影响因素→性能指标的锚点")

        elif intent == ExplanationIntent.COMPARISON:
            if len(direct) >= 2:
                source.append(direct[0].id)
                target.append(direct[1].id)
                rationale.append(f"比较类问题使用两个直接提及概念 {direct[0].id}/{direct[1].id}")

        else:
            if len(direct) >= 2:
                source.append(direct[0].id)
                target.append(direct[-1].id)
                rationale.append(f"通用机制问题使用首尾直接提及概念 {direct[0].id}/{direct[-1].id}")
            elif direct:
                source.append(direct[0].id)
                rationale.append(f"仅检测到一个直接概念，使用 {direct[0].id} 作为锚点")

        # Fallbacks from top entity matches if direct mentions were insufficient.
        if not source and matches:
            source.append(matches[0].id)
            rationale.append(f"未找到可靠源锚点，回退到最高匹配节点 {matches[0].id}")

        # Some intents are naturally one-root / neighborhood questions rather
        # than source-to-target path questions. Do not invent a target for them.
        target_optional_intents = {
            ExplanationIntent.COMPOSITION,
            ExplanationIntent.INTERFACE_ROLE,
            ExplanationIntent.DEFINITION,
            ExplanationIntent.ROLE_FUNCTION,
            ExplanationIntent.RELATION_STRUCTURE,
        }
        if not target and intent not in target_optional_intents:
            for m in matches:
                if m.id not in set(source) and m.id not in direct_ids.intersection(set(focus)):
                    target.append(m.id)
                    rationale.append(f"未找到可靠目标锚点，回退到高匹配节点 {m.id}")
                    break

        # Keep path anchors concise, but relation-set questions may legitimately
        # mention several concepts. They do not trigger pairwise path explosion.
        source = list(dict.fromkeys(source))[:2]
        target = list(dict.fromkeys(target))[:2]
        focus_limit = 8 if intent == ExplanationIntent.RELATION_STRUCTURE else 3
        focus = [x for x in dict.fromkeys(focus) if x not in source and x not in target][:focus_limit]
        return source, target, focus, rationale

    @staticmethod
    def _confidence(
        intent: ExplanationIntent,
        mentions: list[_Mention],
        source_ids: list[str],
        target_ids: list[str],
    ) -> float:
        score = 0.35
        if intent != ExplanationIntent.GENERAL:
            score += 0.20
        if mentions:
            score += 0.15
        if source_ids:
            score += 0.15
        if target_ids:
            score += 0.15
        return min(score, 1.0)
