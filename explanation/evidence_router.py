from __future__ import annotations

from .evidence import (
    ComparisonEvidenceStrategy,
    CompositionEvidenceStrategy,
    DefinitionEvidenceStrategy,
    InterfaceEvidenceStrategy,
    PathEvidenceStrategy,
    RelationStructureEvidenceStrategy,
    RoleFunctionEvidenceStrategy,
)
from .models import ExplanationIntent


class EvidenceStrategyRouter:
    """Map one atomic explanation intent to its KG evidence-retrieval strategy."""

    def __init__(self):
        self.definition = DefinitionEvidenceStrategy()
        self.composition = CompositionEvidenceStrategy()
        self.interface = InterfaceEvidenceStrategy()
        self.role_function = RoleFunctionEvidenceStrategy()
        self.relation_structure = RelationStructureEvidenceStrategy()
        self.comparison = ComparisonEvidenceStrategy()
        self.path = PathEvidenceStrategy()

    def route(self, intent: ExplanationIntent):
        mapping = {
            ExplanationIntent.DEFINITION: self.definition,
            ExplanationIntent.COMPOSITION: self.composition,
            ExplanationIntent.INTERFACE_ROLE: self.interface,
            ExplanationIntent.ROLE_FUNCTION: self.role_function,
            ExplanationIntent.RELATION_STRUCTURE: self.relation_structure,
            ExplanationIntent.COMPARISON: self.comparison,
            ExplanationIntent.TRANSFORMATION_EXECUTION: self.path,
            ExplanationIntent.CAUSAL_MECHANISM: self.path,
            ExplanationIntent.PERFORMANCE: self.path,
            ExplanationIntent.GENERAL: self.path,
        }
        return mapping[intent]
