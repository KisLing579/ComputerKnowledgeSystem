from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DataSettings:
    workbook: Path
    nodes_sheet: str = "KG_Nodes"
    relations_sheet: str = "KG_Relations"
    dependencies_sheet: str = "Knowledge_Dependencies"


@dataclass(frozen=True)
class Neo4jSettings:
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = ""
    database: str = "neo4j"


@dataclass(frozen=True)
class ImportSettings:
    batch_size: int = 500
    active_only: bool = True


@dataclass(frozen=True)
class QuerySettings:
    top_k_nodes: int = 8
    seed_nodes: int = 4
    max_hops: int = 4
    paths_per_pair: int = 20
    candidate_path_limit: int = 50


@dataclass(frozen=True)
class ExplanationSettings:
    max_goal_depth: int = 3
    max_plan_depth: int = 5
    max_children: int = 8
    max_segments: int = 40
    relation_neighbor_limit: int = 20
    definition_support_limit: int = 5
    comparison_support_limit: int = 4


@dataclass(frozen=True)
class VisualSettings:
    """Legacy alias retained for the v1 visual pipeline."""
    max_nodes_per_scene: int = 8
    default_scene_seconds: float = 3.0
    transition_seconds: float = 0.6


@dataclass(frozen=True)
class RepresentationSettings:
    prefer_semantic_patterns: bool = True


@dataclass(frozen=True)
class ResourcePlanningSettings:
    max_nodes_per_scene: int = 8
    show_narration: bool = True


@dataclass(frozen=True)
class RenderingSettings:
    safe_width: float = 11.4
    safe_height: float = 5.25


@dataclass(frozen=True)
class ManimSettings:
    quality: str = "l"
    media_dir: str = "media"
    generated_script: str = "generated_explanation.py"


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data: DataSettings
    neo4j: Neo4jSettings
    importer: ImportSettings
    query: QuerySettings
    explanation: ExplanationSettings
    visual: VisualSettings = field(default_factory=VisualSettings)
    representation: RepresentationSettings = field(default_factory=RepresentationSettings)
    resource_planning: ResourcePlanningSettings = field(default_factory=ResourcePlanningSettings)
    rendering: RenderingSettings = field(default_factory=RenderingSettings)
    manim: ManimSettings = field(default_factory=ManimSettings)


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_settings(config_path: str | Path = "config.toml") -> Settings:
    config_file = Path(config_path).expanduser().resolve()
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with config_file.open("rb") as f:
        raw = tomllib.load(f)

    project_root = config_file.parent
    data_raw = raw.get("data", {})
    neo4j_raw = raw.get("neo4j", {})
    import_raw = raw.get("import", {})
    query_raw = raw.get("query", {})
    explanation_raw = raw.get("explanation", {})
    visual_raw = raw.get("visual", {})
    representation_raw = raw.get("representation", {})
    resource_raw = raw.get("resource_planning", {})
    rendering_raw = raw.get("rendering", {})
    manim_raw = raw.get("manim", {})

    data = DataSettings(
        workbook=_resolve_path(project_root, data_raw.get("workbook", "data/computer_core_kg.xlsx")),
        nodes_sheet=data_raw.get("nodes_sheet", "KG_Nodes"),
        relations_sheet=data_raw.get("relations_sheet", "KG_Relations"),
        dependencies_sheet=data_raw.get("dependencies_sheet", "Knowledge_Dependencies"),
    )
    neo4j = Neo4jSettings(
        uri=os.getenv("NEO4J_URI", neo4j_raw.get("uri", "bolt://localhost:7687")),
        user=os.getenv("NEO4J_USER", neo4j_raw.get("user", "neo4j")),
        password=os.getenv("NEO4J_PASSWORD", ""),
        database=os.getenv("NEO4J_DATABASE", neo4j_raw.get("database", "neo4j")),
    )
    importer = ImportSettings(
        batch_size=int(import_raw.get("batch_size", 500)),
        active_only=bool(import_raw.get("active_only", True)),
    )
    query = QuerySettings(
        top_k_nodes=int(query_raw.get("top_k_nodes", 8)),
        seed_nodes=int(query_raw.get("seed_nodes", 4)),
        max_hops=int(query_raw.get("max_hops", 4)),
        paths_per_pair=int(query_raw.get("paths_per_pair", 20)),
        candidate_path_limit=int(query_raw.get("candidate_path_limit", 50)),
    )
    explanation = ExplanationSettings(
        max_goal_depth=int(explanation_raw.get("max_goal_depth", 3)),
        max_plan_depth=int(explanation_raw.get("max_plan_depth", 5)),
        max_children=int(explanation_raw.get("max_children", 8)),
        max_segments=int(explanation_raw.get("max_segments", 40)),
        relation_neighbor_limit=int(explanation_raw.get("relation_neighbor_limit", 20)),
        definition_support_limit=int(explanation_raw.get("definition_support_limit", 5)),
        comparison_support_limit=int(explanation_raw.get("comparison_support_limit", 4)),
    )
    visual = VisualSettings(
        max_nodes_per_scene=int(visual_raw.get("max_nodes_per_scene", 8)),
        default_scene_seconds=float(visual_raw.get("default_scene_seconds", 3.0)),
        transition_seconds=float(visual_raw.get("transition_seconds", 0.6)),
    )
    representation = RepresentationSettings(
        prefer_semantic_patterns=bool(representation_raw.get("prefer_semantic_patterns", True)),
    )
    resource_planning = ResourcePlanningSettings(
        max_nodes_per_scene=int(resource_raw.get("max_nodes_per_scene", visual.max_nodes_per_scene)),
        show_narration=bool(resource_raw.get("show_narration", True)),
    )
    rendering = RenderingSettings(
        safe_width=float(rendering_raw.get("safe_width", 11.4)),
        safe_height=float(rendering_raw.get("safe_height", 5.25)),
    )
    manim = ManimSettings(
        quality=str(manim_raw.get("quality", "l")),
        media_dir=str(manim_raw.get("media_dir", "media")),
        generated_script=str(manim_raw.get("generated_script", "generated_explanation.py")),
    )

    return Settings(
        project_root=project_root,
        data=data,
        neo4j=neo4j,
        importer=importer,
        query=query,
        explanation=explanation,
        visual=visual,
        representation=representation,
        resource_planning=resource_planning,
        rendering=rendering,
        manim=manim,
    )
