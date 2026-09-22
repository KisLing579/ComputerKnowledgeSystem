"""Small, evidence-bound scene rules. No KG IDs or synthetic implementations."""
from .semantic_scene import ScenePattern as P, SemanticScenePlan
from kg.query import relation_layer_priority


def endpoints(rel):
    return (str(rel.get("stored_start_id") or rel.get("traversal_from") or ""),
            str(rel.get("stored_end_id") or rel.get("traversal_to") or ""))


class ScenePatternMatcher:
    """Match a single local evidence group; unknown shapes return None."""

    def match(self, segment, nodes, relations) -> SemanticScenePlan | None:
        rels = [r for r in relations if relation_layer_priority(r) < 2]
        if not rels or len(rels) != len(relations):
            return None
        ids = tuple(dict.fromkeys(n for r in rels for n in endpoints(r) if n))
        if any(n not in nodes for n in ids):
            return None
        names = {n: str(nodes[n].get("name") or nodes[n].get("name_en") or n) for n in ids}
        def make(pattern, focus, roles, claim, layout):
            extra = [r.get("mediated_by") for r in rels if r.get("mediated_by") in nodes]
            return SemanticScenePlan(pattern, tuple(focus),
                tuple(n for n in dict.fromkeys((*ids, *extra)) if n not in focus),
                tuple(str(r["id"]) for r in rels), roles, claim, segment.title, layout)

        candidates = list(dict.fromkeys([segment.root_id, *ids]))
        for focal in candidates:
            if focal not in ids:
                continue
            incident = [r for r in rels if focal in endpoints(r)]
            # Do not assign one interface claim to unrelated edges in a group.
            if len(incident) != len(rels):
                continue
            upper, lower, implementations = [], [], []
            for r in incident:
                a, b = endpoints(r)
                other = b if a == focal else a
                record = nodes[other]
                text = " ".join(str(record.get(k, "")) for k in
                                ("name", "name_en", "semantic_type", "archetype")).lower()
                rt = r.get("type")
                if rt == "IMPLEMENTS" and b == focal:
                    implementations.append(other)
                    lower.append(other)
                elif rt in {"INTERFACES_WITH", "DEPENDS_ON", "REQUIRES", "USES"}:
                    if any(w in text for w in ("software", "program", "软件", "程序", "code_block")):
                        upper.append(other)
                    elif any(w in text for w in ("hardware", "processor", "cpu", "硬件", "处理器", "microarchitecture", "微体系结构")):
                        lower.append(other)
                # DEPENDS_ON has explicit direction even for non-software clients.
                if rt == "DEPENDS_ON" and b == focal and other not in upper:
                    upper.append(other)
            upper = list(dict.fromkeys(upper))
            lower = list(dict.fromkeys(lower))
            implementations = list(dict.fromkeys(implementations))
            interface_cue = any(r.get('type') in {'INTERFACES_WITH', 'IMPLEMENTS'} for r in incident)
            if upper and lower and set(upper).isdisjoint(lower) and interface_cue:
                roles = {"upper_layer": upper[0], "boundary": focal, "lower_layer": lower[0]}
                roles.update({f"upper_layer_{i}": n for i, n in enumerate(upper[1:], 2)})
                roles.update({f"lower_layer_{i}": n for i, n in enumerate(lower[1:], 2)})
                roles.update({f"implementation_{i}": n for i, n in enumerate(implementations, 1)})
                claim = f"{names[focal]}连接{names[upper[0]]}与{names[lower[0]]}，形成接口边界。"
                if implementations:
                    claim += f"其实现侧对应{'、'.join(names[n] for n in implementations)}。"
                return make(P.ABSTRACTION_INTERFACE, (focal,), roles, claim, "abstraction_interface")
            if len(implementations) >= 2:
                return make(P.ONE_ABSTRACTION_MULTI_IMPLEMENTATION, (focal,),
                    {"boundary": focal, **{f"implementation_{i}": n for i, n in enumerate(implementations, 1)}},
                    f"{'、'.join(names[n] for n in implementations)}共同实现{names[focal]}。", "abstraction_interface")

        types = {r.get("type") for r in rels}
        # All relations must participate in the recognized structure.
        if types <= {"PART_OF", "CONTAINS", "HAS_PART"} and len(rels) >= 2:
            pairs = [(a, b) if r.get("type") == "PART_OF" else (b, a)
                     for r in rels for a, b in [endpoints(r)]]
            wholes = {b for a, b in pairs}
            if len(wholes) == 1:
                whole = next(iter(wholes))
                return make(P.HIERARCHICAL_COMPOSITION, (whole,), {"whole": whole},
                    f"{names[whole]}包含{'、'.join(names[n] for n in dict.fromkeys(a for a, b in pairs))}。", "inside_container")
        if types == {"CONTRASTS_WITH"} and len(ids) == 2:
            return make(P.SIDE_BY_SIDE_CONTRAST, ids, {"left": ids[0], "right": ids[1]},
                        f"并列比较{names[ids[0]]}与{names[ids[1]]}。", "side_by_side")
        chain = self._chain(rels)
        if chain and len(rels) >= 2:
            if types <= {"CAUSES", "RESULTS_IN", "ENABLES", "TRIGGERS"}:
                return make(P.CAUSAL_CHAIN, (chain[0],), {"cause": chain[0], "result": chain[-1]},
                    f"从{names[chain[0]]}沿因果与促成关系逐步到达{names[chain[-1]]}。", "horizontal_flow")
            if types <= {"TRANSFORMS_TO", "EXECUTES", "PRECEDES", "NEXT"}:
                return make(P.PROCESS_PIPELINE, (chain[0],), {f"stage_{i}": n for i, n in enumerate(chain, 1)},
                    f"{' → '.join(names[n] for n in chain)}构成连续处理过程。", "transform_pipeline")
            if types <= {"DEPENDS_ON", "BASED_ON"}:
                return make(P.LAYERED_SYSTEM, (chain[0],), {f"layer_{i}": n for i, n in enumerate(chain, 1)},
                    f"{' → '.join(names[n] for n in chain)}形成逐层依赖。", "layered_system")
        if types <= {"MAPS_TO", "CORRESPONDS_TO"}:
            return make(P.MAPPING_CORRESPONDENCE, ids[:1], {},
                        "；".join(f"{names[a]}对应{names[b]}" for a, b in map(endpoints, rels)) + "。", "side_by_side")
        if len(rels) == 1 and types <= {"TRANSITIONS_TO", "CHANGES_TO", "TRANSFORMS_TO"}:
            a, b = endpoints(rels[0])
            if all(str(nodes[n].get("semantic_type", "")).lower() == "state" for n in (a, b)):
                return make(P.STATE_TRANSITION, (a,), {"before": a, "after": b},
                            f"{names[a]}转变为{names[b]}。", "side_by_side")
        return None

    @staticmethod
    def _chain(rels):
        pairs = list(dict.fromkeys(endpoints(r) for r in rels))
        starts = {a for a, b in pairs} - {b for a, b in pairs}
        if len(starts) != 1 or len({a for a, b in pairs}) != len(pairs):
            return None
        node = next(iter(starts))
        chain = [node]
        remaining = dict(pairs)
        while node in remaining:
            node = remaining.pop(node)
            if node in chain:
                return None
            chain.append(node)
        return chain if not remaining else None
