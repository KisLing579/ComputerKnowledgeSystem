"""Workbook-backed multi-representation and semantic animation layer."""

from .models import RepresentationPlan
from .registry import RepresentationRegistry
from .animation_grammar import AnimationGrammar

__all__ = ["RepresentationPlan", "RepresentationRegistry", "AnimationGrammar"]
