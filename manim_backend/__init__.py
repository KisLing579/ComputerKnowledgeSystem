"""Manim backend for rendering visual.ScenePlan without shadowing the third-party `manim` package."""

from .script_generator import ManimScriptGenerator

__all__ = ["ManimScriptGenerator"]
