from __future__ import annotations

import sys
import types

# The unit tests exercise deterministic planner logic only.  Provide a tiny
# import stub when the Neo4j driver is not installed in the test environment.
if "neo4j" not in sys.modules:
    neo4j_stub = types.ModuleType("neo4j")
    class _GraphDatabase:
        @staticmethod
        def driver(*args, **kwargs):
            raise RuntimeError("Neo4j driver stub: integration DB access is not part of this unit test")
    class _ManagedTransaction:
        pass
    neo4j_stub.GraphDatabase = _GraphDatabase
    neo4j_stub.ManagedTransaction = _ManagedTransaction
    sys.modules["neo4j"] = neo4j_stub

import unittest
from pathlib import Path

from explanation.evidence import EvidenceContext
from explanation.evidence_router import EvidenceStrategyRouter
from explanation.models import ExplanationGoal, ExplanationIntent, QuestionAnalysis
from explanation.path_ranker import ExplanationPathRanker
from explanation.planner import ExplanationPlanner
from explanation.structurer import ExplanationStructurer
from kg.config import (
    DataSettings,
    ExplanationSettings,
    ImportSettings,
    Neo4jSettings,
    QuerySettings,
    Settings,
)
from kg.query import GraphNeighbor, NodeMatch


class FakeDefinitionQueryService:
    def __init__(self):
        self.path_called = False
        self.isa = NodeMatch(
            id="CO035",
            name="指令集体系结构 / ISA",
            name_en="Instruction Set Architecture / ISA",
            semantic_type="abstraction",
            core_level="core",
            definition="软件与硬件之间可见的接口抽象。",
            score=108.0,
        )

    def find_related_nodes(self, question, limit=20):
        return [self.isa]

    def find_relation_neighbors(self, root_id, relation_types, *, limit=20):
        self.assert_root = root_id
        return [
            GraphNeighbor(
                id="CO034",
                name="抽象",
                name_en="Abstraction",
                semantic_type="concept",
                core_level="core",
                definition="",
                relationship={
                    "type": "IS_A",
                    "stored_start_id": "CO035",
                    "stored_end_id": "CO034",
                    "traversal_from": "CO035",
                    "traversal_to": "CO034",
                    "confidence": 1.0,
                    "default_animation_pattern": "ABSTRACT_TO_CONCRETE",
                },
            ),
            GraphNeighbor(
                id="CO020",
                name="指令集",
                name_en="Instruction Set",
                semantic_type="concept",
                core_level="core",
                definition="",
                relationship={
                    "type": "PART_OF",
                    "stored_start_id": "CO020",
                    "stored_end_id": "CO035",
                    "traversal_from": "CO035",
                    "traversal_to": "CO020",
                    "confidence": 1.0,
                    "default_animation_pattern": "REVEAL_INSIDE",
                },
            ),
            GraphNeighbor(
                id="CO021",
                name="硬件",
                name_en="Hardware",
                semantic_type="concept",
                core_level="core",
                definition="",
                relationship={
                    "type": "INTERFACES_WITH",
                    "stored_start_id": "CO035",
                    "stored_end_id": "CO021",
                    "traversal_from": "CO035",
                    "traversal_to": "CO021",
                    "confidence": 1.0,
                    "default_animation_pattern": "INTERFACE_BRIDGE",
                },
            ),
        ]

    def find_paths_between(self, *args, **kwargs):
        self.path_called = True
        raise AssertionError("definition strategy must not call path search")

    def generate_candidate_paths(self, *args, **kwargs):
        self.path_called = True
        raise AssertionError("definition strategy must not call generic candidate paths")


class EvidenceRouterTests(unittest.TestCase):
    def settings(self):
        return Settings(
            project_root=Path("."),
            data=DataSettings(Path("dummy.xlsx")),
            neo4j=Neo4jSettings(),
            importer=ImportSettings(),
            query=QuerySettings(),
            explanation=ExplanationSettings(),
        )

    def test_all_intents_have_explicit_strategy(self):
        router = EvidenceStrategyRouter()
        for intent in ExplanationIntent:
            strategy = router.route(intent)
            self.assertTrue(getattr(strategy, "name", ""))

    def test_definition_is_zero_or_one_hop_and_builds_definition_segment(self):
        isa = NodeMatch(
            id="CO035",
            name="指令集体系结构 / ISA",
            name_en="Instruction Set Architecture / ISA",
            semantic_type="abstraction",
            core_level="core",
            definition="软件与硬件之间可见的接口抽象。",
            score=108.0,
        )
        analysis = QuestionAnalysis(
            question="什么是ISA？",
            intent=ExplanationIntent.DEFINITION,
            source_ids=("CO035",),
            target_ids=(),
            direct_mention_ids=("CO035",),
            confidence=1.0,
        )
        goal = ExplanationGoal("G001", "什么是ISA？", analysis)
        query = FakeDefinitionQueryService()
        router = EvidenceStrategyRouter()
        evidence = router.route(ExplanationIntent.DEFINITION).collect(
            EvidenceContext(
                goal=goal,
                matches=(isa,),
                query_service=query,
                ranker=ExplanationPathRanker(),
                settings=self.settings(),
            )
        )
        self.assertEqual(evidence.evidence_type, "definition")
        self.assertEqual(evidence.root.id, "CO035")
        self.assertEqual(evidence.definition_text, isa.definition)
        self.assertFalse(query.path_called)
        self.assertLessEqual(len(evidence.neighbors), self.settings().explanation.definition_support_limit)

        segment = ExplanationStructurer.segment_from_evidence(
            segment_id="S.G001",
            goal=goal,
            evidence=evidence,
        )
        self.assertEqual(segment.segment_type, "definition")
        self.assertEqual(segment.root_id, "CO035")
        self.assertEqual(segment.metadata["max_support_hops"], 1)
        self.assertIn("软件与硬件", segment.metadata["core_statement"])
        # A definition should have a core statement and local support, not an empty plan.
        self.assertGreaterEqual(len(segment.children), 2)


    def test_definition_end_to_end_planner_does_not_emit_path_diagnostics(self):
        query = FakeDefinitionQueryService()
        planner = ExplanationPlanner(query, self.settings())
        result = planner.explain("什么是ISA？")
        self.assertEqual(result.analysis.intent, ExplanationIntent.DEFINITION)
        self.assertEqual(result.selected_plan.root_segment.segment_type, "definition")
        self.assertEqual(result.selected_plan.root_segment.root_id, "CO035")
        self.assertEqual(result.ranked_paths, ())
        self.assertFalse(query.path_called)
        self.assertTrue(result.selected_plan.validation.valid)



if __name__ == "__main__":
    unittest.main()
