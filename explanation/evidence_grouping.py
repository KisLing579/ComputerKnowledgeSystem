"""Partition evidence into bounded scene groups, retaining every edge once."""
from dataclasses import dataclass

from .models import ExplanationSegment
from .scene_pattern_matcher import ScenePatternMatcher, endpoints
from .semantic_scene import SemanticScenePlan


@dataclass(frozen=True)
class EvidenceGroup:
    relations: tuple[dict, ...]
    focal_node_id: str
    scene_plan: SemanticScenePlan | None = None


def group_related_evidence(relations, nodes, *, title, intent, focal_ids=(), max_nodes=8):
    """Known local patterns first; unmatched evidence retains the fact fallback."""
    matcher = ScenePatternMatcher()
    remaining = list(relations)
    groups = []

    def match(rels, focal):
        ids = set(n for r in rels for n in endpoints(r))
        ids.update(r['mediated_by'] for r in rels if r.get('mediated_by'))
        if len(ids) > max_nodes:
            return None
        segment = ExplanationSegment('group', 'evidence_group', 'fusion', title, intent, root_id=focal)
        return matcher.match(segment, nodes, rels)

    def take(rels, focal, plan):
        groups.append(EvidenceGroup(tuple(rels), focal, plan))
        selected = {r['id'] for r in rels}
        remaining[:] = [r for r in remaining if r['id'] not in selected]

    interface_types = {'INTERFACES_WITH', 'IMPLEMENTS', 'DEPENDS_ON', 'HAS_FUNCTION',
                       'ENABLES', 'BASED_ON', 'REQUIRES', 'USES'}
    degree = {n: sum(n in endpoints(r) for r in remaining) for n in nodes}
    order = list(dict.fromkeys((*focal_ids, *sorted(nodes, key=lambda n: (-degree[n], n)))))
    for focal in order:
        star = [r for r in remaining if focal in endpoints(r) and r.get('type') in interface_types]
        # Keep the interface nucleus ahead of purpose/background support.
        star.sort(key=lambda r: r.get('type') not in {'INTERFACES_WITH', 'IMPLEMENTS', 'DEPENDS_ON'})
        chunk = []
        for r in star:
            ids = {n for x in [*chunk, r] for n in endpoints(x)}
            ids.update(x['mediated_by'] for x in [*chunk, r] if x.get('mediated_by'))
            if len(ids) <= max_nodes:
                chunk.append(r)
        plan = match(chunk, focal) if chunk else None
        if plan and plan.scene_pattern in {'ABSTRACTION_INTERFACE', 'ONE_ABSTRACTION_MULTI_IMPLEMENTATION'}:
            take(chunk, focal, plan)

    families = ({'PART_OF', 'CONTAINS', 'HAS_PART'}, {'CAUSES', 'RESULTS_IN', 'ENABLES', 'TRIGGERS'},
                {'TRANSFORMS_TO', 'EXECUTES', 'PRECEDES', 'NEXT'}, {'DEPENDS_ON', 'BASED_ON'},
                {'MAPS_TO', 'CORRESPONDS_TO'}, {'CONTRASTS_WITH'}, {'TRANSITIONS_TO', 'CHANGES_TO'})
    for family in families:
        pending = [r for r in remaining if r.get('type') in family]
        while pending:
            chunk = [pending.pop(0)]
            ids = set(endpoints(chunk[0]))
            changed = True
            while changed:
                changed = False
                for r in list(pending):
                    linked = set(endpoints(r))
                    if ids & linked and len(ids | linked) <= max_nodes:
                        chunk.append(r)
                        ids |= linked
                        pending.remove(r)
                        changed = True
            focal = next((n for n in focal_ids if n in ids), endpoints(chunk[0])[0])
            plan = match(chunk, focal)
            if plan:
                take(chunk, focal, plan)
    for rel in remaining:
        focal = endpoints(rel)[0]
        groups.append(EvidenceGroup((rel,), focal, match([rel], focal)))
    return groups
