"""Adapt bound evidence to the shared scene matcher without replacing binding."""
from explanation.models import ExplanationSegment
from explanation.scene_pattern_matcher import ScenePatternMatcher


class SemanticScenePlanner:
    def __init__(self):
        self.matcher = ScenePatternMatcher()

    def build(self, segment, nodes, relations):
        if segment.semantic_scene_plan is not None:
            return segment.semantic_scene_plan
        root = next((n.knowledge_node_id for n in segment.nodes
                     if n.representation_id == segment.root_representation_id), None)
        source = ExplanationSegment(segment.segment_id, segment.segment_type, '',
                                    segment.title, segment.intent, root_id=root)
        catalog = {n.knowledge_node_id: {"name": n.name, "archetype": n.archetype,
                    "semantic_type": n.metadata.get('semantic_type', '')} for n in nodes}
        evidence = [dict(id=r.relation_id, type=r.relation_type,
                        stored_start_id=r.stored_source_node_id,
                        stored_end_id=r.stored_target_node_id,
                        mediated_by=r.mediator_node_id,
                        relation_layer=r.metadata.get('relation_layer', 'semantic')) for r in relations]
        return self.matcher.match(source, catalog, evidence)
