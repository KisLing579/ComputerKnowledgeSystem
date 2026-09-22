from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .models import (
    AnimationPattern,
    NodeVisualBinding,
    RelationAnimationBinding,
    VisualProfile,
)


def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _split(value) -> tuple[str, ...]:
    text = _clean(value)
    if not text:
        return ()
    return tuple(x.strip() for x in text.replace(",", ";").split(";") if x.strip())


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = _clean(value).lower()
    return text in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class RegistryValidation:
    valid: bool
    warnings: tuple[str, ...] = ()


class VisualRegistry:
    """Workbook-backed visual ontology and animation grammar.

    The workbook remains the source of truth for visual profiles and relation
    animation mappings.  This class intentionally does not modify the workbook.
    """

    FALLBACK_PATTERNS = {
        # Relation_Animation_Map currently references these two IDs although the
        # v0.2 Animation_Patterns sheet does not define them. Keep rendering
        # deterministic and report the inconsistency via validate().
        "CONNECT_HIGHLIGHT": AnimationPattern(
            pattern_id="CONNECT_HIGHLIGHT",
            definition="连接两个对象并高亮关系",
            category="fallback",
        ),
        "PROCESS_FLOW": AnimationPattern(
            pattern_id="PROCESS_FLOW",
            definition="沿处理步骤依次推进",
            category="fallback",
        ),
        "RELATION_LINK": AnimationPattern(
            pattern_id="RELATION_LINK",
            definition="通用关系连线与高亮",
            category="fallback",
        ),
        "FADE_REVEAL": AnimationPattern(
            pattern_id="FADE_REVEAL",
            definition="通用淡入展示",
            category="fallback",
        ),
    }

    def __init__(self, workbook: str | Path):
        self.workbook = Path(workbook).expanduser().resolve()
        if not self.workbook.exists():
            raise FileNotFoundError(f"Visual workbook not found: {self.workbook}")

        self.node_names: dict[str, str] = {}
        self.profiles: dict[str, VisualProfile] = {}
        self.bindings_by_node: dict[str, list[NodeVisualBinding]] = {}
        self.patterns: dict[str, AnimationPattern] = {}
        self.relation_bindings: dict[str, list[RelationAnimationBinding]] = {}
        self._load()

    def _read(self, sheet: str) -> pd.DataFrame:
        df = pd.read_excel(self.workbook, sheet_name=sheet, dtype=object)
        return df.where(pd.notna(df), "")

    def _load(self) -> None:
        nodes = self._read("KG_Nodes")
        for _, row in nodes.iterrows():
            node_id = _clean(row.get("node_id:ID"))
            if node_id:
                self.node_names[node_id] = _clean(row.get("name")) or node_id

        profiles = self._read("Visual_Profiles")
        for _, row in profiles.iterrows():
            pid = _clean(row.get("profile_id:ID"))
            if not pid or _clean(row.get("status")).lower() not in {"", "active"}:
                continue
            try:
                detail_level = int(float(row.get("detail_level:int") or 0))
            except Exception:
                detail_level = 0
            self.profiles[pid] = VisualProfile(
                profile_id=pid,
                profile_name=_clean(row.get("profile_name")) or pid,
                visual_archetype=_clean(row.get("visual_archetype")) or "functional_block",
                detail_level=detail_level,
                use_cases=_split(row.get("use_cases")),
                description=_clean(row.get("description")),
                render_requirements=_split(row.get("render_requirements")),
                status=_clean(row.get("status")) or "active",
            )

        bindings = self._read("Node_Visual_Bindings")
        for _, row in bindings.iterrows():
            node_id = _clean(row.get(":START_ID"))
            profile_id = _clean(row.get(":END_ID"))
            if not node_id or not profile_id or _clean(row.get("status")).lower() not in {"", "active"}:
                continue
            binding = NodeVisualBinding(
                binding_id=_clean(row.get("binding_id")) or f"{node_id}:{profile_id}",
                node_id=node_id,
                profile_id=profile_id,
                is_default=_bool(row.get("is_default:boolean")),
                selection_condition=_clean(row.get("selection_condition")),
                status=_clean(row.get("status")) or "active",
            )
            self.bindings_by_node.setdefault(node_id, []).append(binding)

        patterns = self._read("Animation_Patterns")
        for _, row in patterns.iterrows():
            pid = _clean(row.get("pattern_id:ID"))
            if not pid:
                continue
            self.patterns[pid] = AnimationPattern(
                pattern_id=pid,
                definition=_clean(row.get("definition")),
                related_relation_types=_split(row.get("related_relation_types")),
                typical_use=_clean(row.get("typical_use")),
                category=_clean(row.get("category")) or "generic",
            )

        relmap = self._read("Relation_Animation_Map")
        for _, row in relmap.iterrows():
            relation_type = _clean(row.get("relation_type"))
            pattern_id = _clean(row.get("animation_pattern_id"))
            if not relation_type or not pattern_id:
                continue
            binding = RelationAnimationBinding(
                relation_type=relation_type,
                animation_pattern_id=pattern_id,
                is_default=_bool(row.get("is_default:boolean")),
                binding_role=_clean(row.get("binding_role")) or "candidate",
            )
            self.relation_bindings.setdefault(relation_type, []).append(binding)

    def validate(self) -> RegistryValidation:
        warnings: list[str] = []
        for node_id, bindings in self.bindings_by_node.items():
            for binding in bindings:
                if binding.profile_id not in self.profiles:
                    warnings.append(
                        f"Node {node_id} binds missing visual profile {binding.profile_id}."
                    )
        for relation_type, bindings in self.relation_bindings.items():
            for binding in bindings:
                if binding.animation_pattern_id not in self.patterns:
                    warnings.append(
                        f"Relation {relation_type} maps to undefined animation pattern "
                        f"{binding.animation_pattern_id}; runtime fallback will be used."
                    )
        return RegistryValidation(valid=not any("missing visual profile" in x for x in warnings), warnings=tuple(warnings))

    def node_name(self, node_id: str) -> str:
        return self.node_names.get(node_id, node_id)

    def profiles_for_node(self, node_id: str) -> tuple[tuple[NodeVisualBinding, VisualProfile], ...]:
        pairs: list[tuple[NodeVisualBinding, VisualProfile]] = []
        for binding in self.bindings_by_node.get(node_id, []):
            profile = self.profiles.get(binding.profile_id)
            if profile is not None:
                pairs.append((binding, profile))
        return tuple(pairs)

    def default_profile(self, node_id: str) -> VisualProfile:
        pairs = self.profiles_for_node(node_id)
        for binding, profile in pairs:
            if binding.is_default:
                return profile
        if pairs:
            return pairs[0][1]
        return VisualProfile(
            profile_id=f"VP_{node_id}_SYNTHETIC",
            profile_name=f"{self.node_name(node_id)}-通用视图",
            visual_archetype="functional_block",
            detail_level=1,
            use_cases=("default",),
            description="No workbook profile was available; generic visual fallback.",
            status="synthetic",
        )

    def choose_profile(self, node_id: str, context_tags: Iterable[str]) -> VisualProfile:
        """Choose a workbook profile using use-case tags, with deterministic fallback."""
        tags = {str(x).strip().lower() for x in context_tags if str(x).strip()}
        pairs = self.profiles_for_node(node_id)
        if not pairs:
            return self.default_profile(node_id)

        scored: list[tuple[float, int, str, VisualProfile]] = []
        for binding, profile in pairs:
            use_cases = {x.lower() for x in profile.use_cases}
            overlap = len(tags & use_cases)
            condition = binding.selection_condition.lower()
            condition_hits = sum(1 for tag in tags if tag and tag.replace("_", " ") in condition)
            score = overlap * 20.0 + condition_hits * 8.0
            if binding.is_default:
                score += 3.0
            # Prefer the least detailed profile that satisfies the same context.
            scored.append((score, -profile.detail_level, profile.profile_id, profile))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        return scored[0][3]

    def pattern(self, pattern_id: str) -> AnimationPattern:
        if pattern_id in self.patterns:
            return self.patterns[pattern_id]
        return self.FALLBACK_PATTERNS.get(pattern_id, self.FALLBACK_PATTERNS["RELATION_LINK"])

    def choose_animation_pattern(
        self,
        relation_type: str,
        *,
        requested: str = "",
        context_tags: Iterable[str] = (),
    ) -> AnimationPattern:
        if requested:
            return self.pattern(requested)
        bindings = self.relation_bindings.get(relation_type, [])
        if bindings:
            default = next((x for x in bindings if x.is_default), bindings[0])
            return self.pattern(default.animation_pattern_id)
        return self.FALLBACK_PATTERNS["RELATION_LINK"]
