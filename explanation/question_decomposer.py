from __future__ import annotations

import re
from collections.abc import Callable

from kg.query import NodeMatch

from .models import ExplanationGoal
from .question_analyzer import QuestionAnalyzer


class QuestionDecomposer:
    """Rule-based v0.4 decomposition of compound explanation questions.

    The decomposer creates a goal tree. It does *not* traverse the KG. Each leaf
    goal is later planned with the evidence strategy appropriate to its own
    intent (path, neighborhood, relation-set, interface, etc.).
    """

    _ROLE_SUFFIXES = (
        "分别起什么作用",
        "分别有什么作用",
        "分别负责什么",
    )

    def __init__(self, analyzer: QuestionAnalyzer | None = None, *, max_depth: int = 3):
        self.analyzer = analyzer or QuestionAnalyzer()
        self.max_depth = max_depth

    def decompose(
        self,
        question: str,
        match_provider: Callable[[str], list[NodeMatch]],
    ) -> ExplanationGoal:
        counter = [0]

        def make_goal(text: str, depth: int, purpose: str = "explain") -> ExplanationGoal:
            counter[0] += 1
            goal_id = f"G{counter[0]:03d}"
            matches = match_provider(text)
            analysis = self.analyzer.analyze(text, matches)

            children: list[ExplanationGoal] = []
            if depth < self.max_depth:
                parts = self._split_compound(text)
                if len(parts) > 1:
                    children = [make_goal(p, depth + 1, "subgoal") for p in parts]
                else:
                    expanded = self._expand_role_enumeration(text)
                    if len(expanded) > 1:
                        children = [make_goal(p, depth + 1, "role_subgoal") for p in expanded]

            return ExplanationGoal(
                goal_id=goal_id,
                text=text.strip(),
                analysis=analysis,
                depth=depth,
                purpose=purpose,
                children=tuple(children),
                metadata={
                    "decomposed": bool(children),
                    "child_count": len(children),
                },
            )

        return make_goal(question.strip(), 0, "root")

    @staticmethod
    def _split_compound(text: str) -> list[str]:
        """Split only where separate explanatory acts are explicit.

        We intentionally avoid blindly splitting every comma: that would break
        phrases such as "CPU、存储器和I/O之间是什么关系" into nonsense.
        """
        primary = [x.strip(" ，,？?；;。") for x in re.split(r"[？?；;。]+", text) if x.strip()]
        output: list[str] = []
        cue_re = re.compile(
            r"(哪些层|有哪些层|起什么作用|有什么作用|负责什么|处在什么位置|位于哪里|"
            r"是什么关系|有什么关系|为什么|为何|怎么|如何|由哪些|由什么|区别|不同)"
        )
        for chunk in primary:
            comma_parts = [p.strip() for p in re.split(r"[，,]+", chunk) if p.strip()]
            if len(comma_parts) > 1:
                strong = [p for p in comma_parts if cue_re.search(p)]
                # Split only when at least two comma-separated pieces each look
                # like an independent explanatory request.
                if len(strong) >= 2:
                    output.extend(comma_parts)
                    continue
            output.append(chunk)
        return output if len(output) > 1 else [text.strip()]

    def _expand_role_enumeration(self, text: str) -> list[str]:
        clean = text.strip(" ，,？?；;。")
        suffix = next((s for s in self._ROLE_SUFFIXES if s in clean), None)
        if suffix is None:
            return [text.strip()]
        prefix = clean.split(suffix, 1)[0].strip(" ，,")
        names = [x.strip() for x in re.split(r"[、]|和|与", prefix) if x.strip()]
        if len(names) < 2 or len(names) > 6:
            return [text.strip()]
        return [f"{name}起什么作用？" for name in names]
