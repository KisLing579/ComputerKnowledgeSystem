from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from kg.query import ExplanationPath, path_layer_priority

from .models import (
    ExplanationIntent,
    PathScoreBreakdown,
    QuestionAnalysis,
    RankedExplanationPath,
)


# Query-dependent relation value. Values are intentionally interpretable rather
# than trained. The ranker converts them to a normalized relation-fit score.
_RELATION_WEIGHTS: dict[ExplanationIntent, dict[str, float]] = {
    ExplanationIntent.TRANSFORMATION_EXECUTION: {
        "TRANSFORMS_TO": 1.00,
        "EXECUTES": 1.00,
        "RESULTS_IN": 0.90,
        "ENABLES": 0.75,
        "BASED_ON": 0.70,
        "CAUSES": 0.70,
        "REQUIRES": 0.65,
        "HAS_FUNCTION": 0.45,
        "SOLVES": 0.35,
        "MOTIVATED_BY": 0.30,
        "PREVENTS": 0.25,
        "IMPLEMENTS": 0.45,
        "USES": 0.35,
        "INTERFACES_WITH": 0.25,
        "CONTROLS": 0.20,
        "PART_OF": -0.20,
        "IS_A": -0.35,
        "AFFECTS": -0.80,
        "DESCRIBES": -0.75,
        "CONTRASTS_WITH": -0.60,
    },
    ExplanationIntent.COMPOSITION: {
        "PART_OF": 1.00,
        "IS_A": 0.55,
        "REQUIRES": 0.55,
        "BASED_ON": 0.25,
        "ENABLES": 0.25,
        "HAS_FUNCTION": 0.10,
        "INTERFACES_WITH": 0.15,
        "USES": 0.10,
        "AFFECTS": -0.65,
        "TRANSFORMS_TO": -0.55,
        "DESCRIBES": -0.45,
    },
    ExplanationIntent.INTERFACE_ROLE: {
        "INTERFACES_WITH": 1.00,
        "HAS_FUNCTION": 0.95,
        "ENABLES": 0.75,
        "SOLVES": 0.70,
        "BASED_ON": 0.70,
        "REQUIRES": 0.65,
        "MOTIVATED_BY": 0.40,
        "RESULTS_IN": 0.35,
        "PREVENTS": 0.30,
        "CAUSES": 0.20,
        "PART_OF": 0.70,
        "IMPLEMENTS": 0.55,
        "USES": 0.35,
        "IS_A": 0.10,
        "AFFECTS": -0.55,
        "DESCRIBES": -0.40,
        "TRIGGERS": -0.45,
    },
    ExplanationIntent.ROLE_FUNCTION: {
        "HAS_FUNCTION": 1.00,
        "SOLVES": 0.95,
        "ENABLES": 0.90,
        "PREVENTS": 0.80,
        "BASED_ON": 0.75,
        "RESULTS_IN": 0.75,
        "REQUIRES": 0.70,
        "MOTIVATED_BY": 0.70,
        "CAUSES": 0.55,
        "CONTROLS": 1.00,
        "MANAGES": 1.00,
        "INTERFACES_WITH": 0.90,
        "EXECUTES": 0.90,
        "TRANSFORMS_TO": 0.90,
        "IMPLEMENTS": 0.80,
        "USES": 0.65,
        "STORES": 0.55,
        "PART_OF": 0.10,
        "IS_A": -0.20,
        "AFFECTS": -0.30,
    },
    ExplanationIntent.RELATION_STRUCTURE: {
        "REQUIRES": 0.80,
        "BASED_ON": 0.75,
        "ENABLES": 0.70,
        "HAS_FUNCTION": 0.60,
        "SOLVES": 0.55,
        "RESULTS_IN": 0.50,
        "CAUSES": 0.45,
        "PREVENTS": 0.40,
        "MOTIVATED_BY": 0.35,
        "PART_OF": 1.00,
        "CONTROLS": 0.95,
        "MANAGES": 0.95,
        "INTERFACES_WITH": 0.90,
        "USES": 0.75,
        "EXECUTES": 0.75,
        "STORES": 0.75,
        "IS_A": 0.55,
        "CONTRASTS_WITH": 0.55,
        "AFFECTS": 0.20,
    },
    ExplanationIntent.CAUSAL_MECHANISM: {
        "CAUSES": 1.00,
        "RESULTS_IN": 0.95,
        "ENABLES": 0.90,
        "PREVENTS": 0.90,
        "SOLVES": 0.90,
        "MOTIVATED_BY": 0.85,
        "REQUIRES": 0.85,
        "BASED_ON": 0.80,
        "HAS_FUNCTION": 0.55,
        "TRIGGERS": 1.00,
        "CONTROLS": 0.90,
        "EXECUTES": 0.85,
        "TRANSFORMS_TO": 0.80,
        "IMPLEMENTS": 0.70,
        "EXPLOITS": 0.70,
        "USES": 0.45,
        "INTERFACES_WITH": 0.30,
        "PART_OF": 0.10,
        "IS_A": -0.35,
        "CONTRASTS_WITH": -0.25,
    },
    ExplanationIntent.PERFORMANCE: {
        "CAUSES": 0.95,
        "RESULTS_IN": 0.95,
        "PREVENTS": 0.90,
        "SOLVES": 0.80,
        "ENABLES": 0.75,
        "MOTIVATED_BY": 0.65,
        "BASED_ON": 0.60,
        "REQUIRES": 0.55,
        "HAS_FUNCTION": 0.45,
        "AFFECTS": 1.00,
        "CONSTRAINS": 0.90,
        "EXPLOITS": 0.70,
        "DESCRIBES": 0.65,
        "USES": 0.30,
        "IMPLEMENTS": 0.25,
        "IS_A": -0.25,
    },
    ExplanationIntent.COMPARISON: {
        "BASED_ON": 0.45,
        "HAS_FUNCTION": 0.35,
        "CAUSES": 0.35,
        "RESULTS_IN": 0.35,
        "SOLVES": 0.30,
        "ENABLES": 0.30,
        "PREVENTS": 0.30,
        "REQUIRES": 0.25,
        "MOTIVATED_BY": 0.20,
        "CONTRASTS_WITH": 1.00,
        "IS_A": 0.40,
        "PART_OF": 0.25,
        "DESCRIBES": 0.25,
        "AFFECTS": 0.10,
        "TRANSFORMS_TO": -0.35,
        "TRIGGERS": -0.35,
    },
    ExplanationIntent.DEFINITION: {
        "BASED_ON": 0.85,
        "HAS_FUNCTION": 0.80,
        "REQUIRES": 0.55,
        "ENABLES": 0.50,
        "MOTIVATED_BY": 0.35,
        "SOLVES": 0.30,
        "RESULTS_IN": 0.30,
        "PREVENTS": 0.20,
        "CAUSES": 0.15,
        "IS_A": 0.90,
        "PART_OF": 0.75,
        "INTERFACES_WITH": 0.55,
        "USES": 0.35,
        "IMPLEMENTS": 0.30,
        "AFFECTS": -0.35,
        "TRIGGERS": -0.35,
    },
    ExplanationIntent.GENERAL: {
        "CAUSES": 0.85,
        "RESULTS_IN": 0.85,
        "ENABLES": 0.80,
        "SOLVES": 0.80,
        "HAS_FUNCTION": 0.75,
        "REQUIRES": 0.75,
        "PREVENTS": 0.75,
        "BASED_ON": 0.75,
        "MOTIVATED_BY": 0.70,
        "PART_OF": 0.45,
        "USES": 0.45,
        "INTERFACES_WITH": 0.50,
        "IMPLEMENTS": 0.55,
        "TRANSFORMS_TO": 0.65,
        "EXECUTES": 0.65,
        "CONTROLS": 0.55,
        "TRIGGERS": 0.70,
        "AFFECTS": 0.25,
        "IS_A": 0.20,
    },
}


# Small relation-order bonuses for paths that form a readable explanatory
# chain. Relation fit remains the dominant ranking signal.
_EXPLANATORY_SEQUENCE_BONUSES: dict[tuple[str, str], float] = {
    ("MOTIVATED_BY", "SOLVES"): 0.12,
    ("SOLVES", "RESULTS_IN"): 0.12,
    ("BASED_ON", "ENABLES"): 0.10,
    ("REQUIRES", "RESULTS_IN"): 0.10,
    ("CAUSES", "RESULTS_IN"): 0.10,
    ("MOTIVATED_BY", "CAUSES"): 0.08,
    ("CAUSES", "PREVENTS"): 0.08,
}


_IDEAL_HOPS: dict[ExplanationIntent, tuple[int, int]] = {
    ExplanationIntent.TRANSFORMATION_EXECUTION: (3, 5),
    ExplanationIntent.COMPOSITION: (1, 3),
    ExplanationIntent.INTERFACE_ROLE: (2, 4),
    ExplanationIntent.ROLE_FUNCTION: (1, 3),
    ExplanationIntent.RELATION_STRUCTURE: (1, 4),
    ExplanationIntent.CAUSAL_MECHANISM: (2, 5),
    ExplanationIntent.PERFORMANCE: (1, 4),
    ExplanationIntent.COMPARISON: (1, 3),
    ExplanationIntent.DEFINITION: (1, 3),
    ExplanationIntent.GENERAL: (2, 5),
}


# Frequent high-level taxonomy edges are useful for navigation but often form
# explanatory detours. Penalty is intent-dependent through relation_fit; these
# generic node ids add only a light extra detour penalty.
_GENERIC_BRIDGE_NAMES = {
    "程序", "program", "软件", "software", "硬件", "hardware", "计算机系统", "computer system"
}


class ExplanationPathRanker:
    """Re-rank graph candidates by explanation quality, not just graph distance."""

    def rank(
        self,
        analysis: QuestionAnalysis,
        paths: Iterable[ExplanationPath],
    ) -> list[RankedExplanationPath]:
        ranked: list[RankedExplanationPath] = []
        for path in paths:
            if path_layer_priority(path) == 2:
                continue
            ranked.append(self._score_path(analysis, path))

        ranked.sort(
            key=lambda rp: (
                -rp.breakdown.anchor_coverage,
                -rp.breakdown.focus_coverage,
                path_layer_priority(rp.path),
                -rp.explanation_score,
                rp.path.hop_count,
                rp.path.node_ids,
            )
        )
        return [replace(rp, rank=i) for i, rp in enumerate(ranked, 1)]

    def _score_path(self, analysis: QuestionAnalysis, path: ExplanationPath) -> RankedExplanationPath:
        anchor = self._anchor_coverage(analysis, path)
        focus = self._focus_coverage(analysis, path)
        relation_fit = self._relation_fit(analysis, path)
        coherence = self._semantic_coherence(analysis, path)
        length_fit = self._path_length_fit(analysis.intent, path.hop_count)
        animation = self._animation_coverage(path)
        confidence = self._edge_confidence(path)
        detour = self._detour_penalty(analysis, path)

        # Graph score came from kg.query candidate generation. Compress it into
        # [0, 100] as a weak prior; explanation semantics should dominate.
        graph_score = max(0.0, min(100.0, float(path.score or 0.0)))

        # Explanation score components sum to 1.00 before the penalty.
        raw = (
            0.24 * anchor
            + 0.12 * focus
            + 0.24 * relation_fit
            + 0.15 * coherence
            + 0.09 * length_fit
            + 0.06 * animation
            + 0.06 * confidence
            + 0.04 * (graph_score / 100.0)
        )
        score = max(0.0, min(1.0, raw - 0.16 * detour)) * 100.0

        breakdown = PathScoreBreakdown(
            anchor_coverage=round(anchor * 100, 2),
            focus_coverage=round(focus * 100, 2),
            relation_fit=round(relation_fit * 100, 2),
            semantic_coherence=round(coherence * 100, 2),
            path_length_fit=round(length_fit * 100, 2),
            animation_coverage=round(animation * 100, 2),
            edge_confidence=round(confidence * 100, 2),
            detour_penalty=round(detour * 100, 2),
            graph_score=round(graph_score, 2),
            explanation_score=round(score, 2),
        )
        return RankedExplanationPath(path=path, breakdown=breakdown)

    @staticmethod
    def _anchor_coverage(analysis: QuestionAnalysis, path: ExplanationPath) -> float:
        ids = set(path.node_ids)
        source_hit = 1.0 if any(x in ids for x in analysis.source_ids) else 0.0
        target_hit = 1.0 if any(x in ids for x in analysis.target_ids) else 0.0
        if analysis.source_ids and analysis.target_ids:
            return (source_hit + target_hit) / 2.0
        if analysis.source_ids:
            return source_hit
        if analysis.target_ids:
            return target_hit
        return 0.5

    @staticmethod
    def _focus_coverage(analysis: QuestionAnalysis, path: ExplanationPath) -> float:
        if not analysis.focus_ids:
            return 1.0
        ids = set(path.node_ids)
        return sum(1 for x in analysis.focus_ids if x in ids) / len(analysis.focus_ids)

    @staticmethod
    def _relation_fit(analysis: QuestionAnalysis, path: ExplanationPath) -> float:
        if not path.relationships:
            return 0.0
        weights = _RELATION_WEIGHTS[analysis.intent]
        values = [weights.get(str(r.get("type", "")), 0.0) for r in path.relationships]
        # Map mean [-1, 1] to [0, 1], then slightly reward having at least one
        # highly diagnostic relation such as TRANSFORMS_TO/EXECUTES.
        mean = sum(values) / len(values)
        best = max(values)
        normalized = (mean + 1.0) / 2.0
        if best >= 0.85:
            normalized += 0.08
        return max(0.0, min(1.0, normalized))

    def _semantic_coherence(self, analysis: QuestionAnalysis, path: ExplanationPath) -> float:
        types = [str(r.get("type", "")) for r in path.relationships]
        if not types:
            return 0.0
        if len(types) == 1:
            return max(0.55, self._relation_fit(analysis, path))

        weights = _RELATION_WEIGHTS[analysis.intent]
        values = [weights.get(t, 0.0) for t in types]
        transitions: list[float] = []
        for a, b in zip(values, values[1:]):
            # Positive explanatory relations chaining together are coherent.
            if a > 0 and b > 0:
                transitions.append(1.0 - min(abs(a - b), 1.0) * 0.25)
            elif a < 0 and b < 0:
                transitions.append(0.15)
            else:
                transitions.append(0.40)

        score = sum(transitions) / len(transitions)

        # Strong sequence priors for the first intended validation scenario and
        # other process explanations. These are semantic patterns, not node ids.
        if analysis.intent == ExplanationIntent.TRANSFORMATION_EXECUTION:
            joined = ">".join(types)
            if "TRANSFORMS_TO>TRANSFORMS_TO" in joined:
                score += 0.12
            if "EXECUTES" in types and "TRANSFORMS_TO" in types:
                score += 0.10
            if types.count("IS_A") >= 2:
                score -= 0.20
            if "AFFECTS" in types:
                score -= 0.25

        # Prefer rhetorical chains such as MOTIVATED_BY -> SOLVES ->
        # RESULTS_IN over paths that are merely graph-connected.
        sequence_bonus = sum(
            _EXPLANATORY_SEQUENCE_BONUSES.get(pair, 0.0)
            for pair in zip(types, types[1:])
        )
        score += min(0.20, sequence_bonus)

        return max(0.0, min(1.0, score))

    @staticmethod
    def _path_length_fit(intent: ExplanationIntent, hops: int) -> float:
        lo, hi = _IDEAL_HOPS[intent]
        if lo <= hops <= hi:
            return 1.0
        if hops < lo:
            distance = lo - hops
            return max(0.15, 1.0 - 0.35 * distance)
        distance = hops - hi
        return max(0.10, math.exp(-0.45 * distance))

    @staticmethod
    def _animation_coverage(path: ExplanationPath) -> float:
        if not path.relationships:
            return 0.0
        covered = sum(1 for r in path.relationships if r.get("default_animation_pattern"))
        return covered / len(path.relationships)

    @staticmethod
    def _edge_confidence(path: ExplanationPath) -> float:
        if not path.relationships:
            return 0.0
        vals = [float(r.get("confidence", 1.0) or 1.0) for r in path.relationships]
        return max(0.0, min(1.0, sum(vals) / len(vals)))

    def _detour_penalty(self, analysis: QuestionAnalysis, path: ExplanationPath) -> float:
        types = [str(r.get("type", "")) for r in path.relationships]
        weights = _RELATION_WEIGHTS[analysis.intent]
        negative_rel = sum(1 for t in types if weights.get(t, 0.0) <= -0.30)

        # Internal generic taxonomy nodes can create graph-theoretically short
        # but pedagogically vague routes (Program -> Software -> Hardware...).
        generic_internal = 0
        for name in path.node_names[1:-1]:
            n = str(name).strip().lower()
            if n in _GENERIC_BRIDGE_NAMES:
                generic_internal += 1

        penalty = 0.18 * negative_rel + 0.10 * generic_internal

        # Missing focus concepts is an explanatory detour/omission, but keep it
        # separate from the positive focus_coverage component for observability.
        if analysis.focus_ids and self._focus_coverage(analysis, path) == 0:
            penalty += 0.20

        return max(0.0, min(1.0, penalty))
