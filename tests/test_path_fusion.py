from __future__ import annotations

import unittest

from test_representation_v2 import WORKBOOK
from explanation.path_fusion import PathFusionPlanner
from kg.query import ExplanationPath, KGQueryService, path_key
from kg.config import load_settings
from representation.registry import RepresentationRegistry
from resource_planning.binder import RepresentationBinder
from resource_planning.story_planner import VisualStoryPlanner


def path(ids, *relations, score=80.0):
    return ExplanationPath(tuple(ids), tuple(ids), tuple(relations), score)


def edge(rid, source, target, kind="USES", **extra):
    return dict(id=rid, type=kind, stored_start_id=source,
                stored_end_id=target, traversal_from=source,
                traversal_to=target, **extra)


class PathFusionTests(unittest.TestCase):
    def test_intent_ranking_precedes_limit_and_keeps_parallel_part_of(self):
        from kg.query import NodeMatch
        settings = load_settings()
        class Query(KGQueryService):
            def find_related_nodes(self, question):
                return [NodeMatch("A", "CPU", "CPU", "", "core", "", 120),
                        NodeMatch("B", "部件", "", "", "core", "", 100)]
            def find_paths_between(self, source, target, **kwargs):
                self.retrieval_limit = kwargs["limit"]
                return [path(("A", "B"), edge("perf", "A", "B", "AFFECTS",
                                             default_animation_pattern="METRIC_CHANGE")),
                        path(("A", "B"), edge("part1", "B", "A", "PART_OF")),
                        path(("A", "B"), edge("part2", "B", "A", "PART_OF"))][:kwargs["limit"]]
        query = Query(None, settings)
        _, selected = query.generate_candidate_paths("CPU由哪些部分组成？", limit=1)
        self.assertEqual(selected[0].relationships[0]["type"], "PART_OF")
        self.assertGreaterEqual(query.retrieval_limit, settings.query.paths_per_pair)
        _, selected = query.generate_candidate_paths("CPU由哪些部分组成？", limit=2)
        self.assertEqual({p.relationships[0]["id"] for p in selected}, {"part1", "part2"})

    def test_parallel_edges_and_reverse_duplicates(self):
        first = path(("A", "B"), edge("r1", "A", "B"))
        reverse = path(("B", "A"), dict(first.relationships[0],
                       traversal_from="B", traversal_to="A"), score=20)
        others = [path(("A", "B"), edge("r2", "A", "B", "CONTROLS")),
                  path(("A", "B"), edge("r3", "A", "B")),
                  path(("A", "B"), edge("r4", "B", "A"))]
        self.assertEqual(path_key(first), path_key(reverse))
        result = PathFusionPlanner().fuse("test", [], [first, reverse, *others])
        self.assertEqual(len(result.candidate_paths), 4)
        self.assertEqual(len(result.answer_graph["edges"]), 4)
        self.assertIn(first, result.candidate_paths)
        self.assertTrue(result.plan.validation.valid)

    def test_shared_edges_keep_path_membership(self):
        ab = edge("ab", "A", "B")
        result = PathFusionPlanner().fuse("test", [], [
            path(("A", "B", "C"), ab, edge("bc", "B", "C")),
            path(("A", "B", "D"), ab, edge("bd", "B", "D")),
        ])
        self.assertEqual(len(result.answer_graph["nodes"]), 4)
        self.assertEqual(len(result.plan.root_segment.children), 3)
        shared = next(e for e in result.answer_graph["edges"]
                      if e["relationship"]["id"] == "ab")
        self.assertEqual(len(shared["source_path_ids"]), 2)

    def test_query_preserves_parallel_relationships(self):
        class Client:
            def read(self, cypher, params):
                assert "mediated_by" in cypher
                assert "elementId(rs[i])" in cypher
                return [dict(nodes=[dict(id="A"), dict(id="B")],
                             rels=[edge(rid, "A", "B")]) for rid in ("r1", "r2", "r1")]
        service = KGQueryService(Client(), load_settings())
        self.assertEqual(len(service.find_paths_between("A", "B")), 2)

    def test_fused_relations_reach_animation_binding(self):
        result = PathFusionPlanner().fuse("高级语言怎么编译？", [], [
            path(("CO011", "CO012"), edge("compile", "CO011", "CO012",
                 "TRANSFORMS_TO", mediated_by="CO008")),
            path(("CO011", "CO012"), edge("uses", "CO011", "CO012", "USES")),
        ])
        rep = RepresentationBinder(RepresentationRegistry(WORKBOOK)).bind(result.plan)
        relations = [r for s in rep.root_segment.children for r in s.relations]
        self.assertEqual(len(relations), 2)
        transform = next(r for r in relations if r.relation_type == "TRANSFORMS_TO")
        self.assertEqual(transform.mediator_node_id, "CO008")
        self.assertEqual(transform.grammar_template_id, "pipeline_transform")
        self.assertEqual(transform.metadata["kg_relation_id"], "compile")
        self.assertEqual(len(transform.metadata["source_path_ids"]), 1)
        story = VisualStoryPlanner().plan(rep)
        self.assertEqual(len(story.scenes), 2)
        for scene in story.scenes:
            self.assertTrue(all(b.narration == scene.narration_summary for b in scene.beats))
            self.assertNotIn("TRANSFORMS_TO", scene.narration_summary)


if __name__ == "__main__":
    unittest.main()
