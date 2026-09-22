import unittest

from kg.config import load_settings
from kg.query import ExplanationPath, KGQueryService
from explanation.models import ExplanationIntent, QuestionAnalysis
from explanation.path_ranker import ExplanationPathRanker


def path(layer, ids=("A", "B"), kind="CAUSES"):
    return ExplanationPath(ids, ids, tuple(
        {"type": kind, "relation_layer": layer} for _ in ids[1:]), 80)


class RelationLayerPriorityTests(unittest.TestCase):
    def test_explanatory_priority_with_semantic_support_and_teaching_exclusion(self):
        analysis = QuestionAnalysis("why", ExplanationIntent.GENERAL, ("A",), ("B",))
        semantic = path("semantic")
        explanatory = path("explan", ("A", "C", "B"))
        mixed = ExplanationPath(("A", "D", "B"), ("A", "D", "B"),
                                (explanatory.relationships[0], semantic.relationships[0]), 80)
        ranked = ExplanationPathRanker().rank(analysis, [
            semantic, path("teaching"), path("semantic", kind="PREREQUISITE_OF"),
            explanatory, mixed])
        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[-1].path, semantic)
        self.assertEqual({r.path.node_ids for r in ranked[:2]}, {mixed.node_ids, explanatory.node_ids})
        self.assertEqual(ExplanationPathRanker().rank(analysis, [semantic])[0].path, semantic)

    def test_anchor_coverage_precedes_layer_preference(self):
        analysis = QuestionAnalysis("why", ExplanationIntent.GENERAL, ("A",), ("B",))
        semantic = path("semantic")
        unrelated = path("explanation", ("C", "D"))
        self.assertEqual(ExplanationPathRanker().rank(analysis, [unrelated, semantic])[0].path, semantic)

    def test_database_filters_teaching_and_orders_before_limit(self):
        class Client:
            def read(self, cypher, params):
                self.cypher = cypher
                return []
        client = Client()
        query = KGQueryService(client, load_settings())
        calls = [lambda: query.find_paths_between("A", "B", limit=1),
                 lambda: query.find_components("A", limit=1),
                 lambda: query.find_relation_neighbors("A", ["CAUSES"], limit=1),
                 lambda: query.find_relations_among(["A", "B"], limit=1),
                 lambda: query.find_mediated_relations("A", limit=1)]
        for call in calls:
            call()
            self.assertIn("<> 'teaching'", client.cypher)
            self.assertIn("relation_layer:", client.cypher)
            self.assertIn("explan", client.cypher[client.cypher.index("ORDER BY"):])
            self.assertLess(client.cypher.index("ORDER BY"), client.cypher.index("LIMIT"))
