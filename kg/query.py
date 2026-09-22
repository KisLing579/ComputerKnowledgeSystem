from __future__ import annotations

import argparse
import itertools
import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from typing import Any

from .config import Settings, load_settings
from .neo4j_client import Neo4jClient
from .aliases import aliases_for


@dataclass(frozen=True)
class NodeMatch:
    id: str
    name: str
    name_en: str
    semantic_type: str
    core_level: str
    definition: str
    score: float


@dataclass(frozen=True)
class ExplanationPath:
    node_ids: tuple[str, ...]
    node_names: tuple[str, ...]
    relationships: tuple[dict[str, Any], ...]
    score: float

    @property
    def hop_count(self) -> int:
        return len(self.relationships)




@dataclass(frozen=True)
class GraphRelation:
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    relationship: dict[str, Any]

@dataclass(frozen=True)
class GraphNeighbor:
    id: str
    name: str
    name_en: str
    semantic_type: str
    core_level: str
    definition: str
    relationship: dict[str, Any]


def relationship_key(rel: dict[str, Any]) -> tuple[str, ...]:
    """Identify a stored edge independently of its traversal direction."""
    return tuple(str(rel.get(k) or "") for k in (
        "id", "element_id", "stored_start_id", "stored_end_id", "type", "relation_layer"
    ))


def relation_layer_priority(rel: dict[str, Any]) -> int:
    """Explanation first, semantic support second; teaching is context only."""
    layer = str(rel.get("relation_layer") or "semantic").strip().lower()
    if rel.get("type") == "PREREQUISITE_OF" or layer == "teaching":
        return 2
    return 0 if layer in ("explan", "explanation", "explanatory") else 1


def path_layer_priority(path: ExplanationPath) -> int:
    priorities = [relation_layer_priority(r) for r in path.relationships]
    if 2 in priorities:
        return 2
    return 0 if 0 in priorities else 1


_LAYER_ORDER = "CASE toLower(trim(coalesce(r.relation_layer, 'semantic'))) WHEN 'explan' THEN 0 WHEN 'explanation' THEN 0 WHEN 'explanatory' THEN 0 ELSE 1 END"
_FACT_FILTER = "type(r) <> 'PREREQUISITE_OF' AND toLower(trim(coalesce(r.relation_layer, 'semantic'))) <> 'teaching'"


def path_key(path: ExplanationPath) -> tuple:
    edges = tuple(relationship_key(r) for r in path.relationships)
    forward = (path.node_ids, edges)
    backward = (tuple(reversed(path.node_ids)), tuple(reversed(edges)))
    return min(forward, backward)


def _norm(text: Any) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[\s\-—_，。！？、；：,.!?;:()（）\[\]{}<>《》/]+", "", text)


def _name_variants(name: str, name_en: str) -> list[str]:
    return aliases_for(name, name_en)


def _char_bigrams(text: str) -> set[str]:
    text = _norm(text)
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class KGQueryService:
    """v0.x query service: lexical entity linking + bounded path discovery.

    This intentionally avoids embeddings and LLMs so the first end-to-end graph
    loop can be tested deterministically. The entity linker can later be swapped
    for embeddings without changing the path-search interface.

    Fact queries prioritize explanation relations and retain semantic support.
    Teaching dependencies are retrieved separately by student_model.
    """

    def __init__(self, client: Neo4jClient, settings: Settings):
        self.client = client
        self.settings = settings

    def _all_active_nodes(self) -> list[dict[str, Any]]:
        return self.client.read(
            """
            MATCH (n:KnowledgeNode)
            WHERE coalesce(n.status, 'active') = 'active'
            RETURN n.id AS id,
                   coalesce(n.name, '') AS name,
                   coalesce(n.name_en, '') AS name_en,
                   coalesce(n.semantic_type, '') AS semantic_type,
                   coalesce(n.core_level, '') AS core_level,
                   coalesce(n.definition, '') AS definition
            ORDER BY n.id
            """
        )

    def find_related_nodes(self, question: str, limit: int | None = None) -> list[NodeMatch]:
        """Return node candidates relevant to a natural-language question.

        Current strategy is deterministic and intentionally simple:
        - exact/alias occurrence in the question gets a strong boost;
        - character bigram overlap with name+definition provides soft recall;
        - SequenceMatcher adds a small similarity signal.
        """
        limit = limit or self.settings.query.top_k_nodes
        q_norm = _norm(question)
        q_bigrams = _char_bigrams(question)

        matches: list[NodeMatch] = []
        for row in self._all_active_nodes():
            name = row["name"] or ""
            name_en = row["name_en"] or ""
            definition = row["definition"] or ""

            score = 0.0
            variants = _name_variants(name, name_en)
            for variant in variants:
                v_norm = _norm(variant)
                if not v_norm:
                    continue
                if v_norm in q_norm:
                    score = max(score, 100.0 + min(len(v_norm), 20))
                elif q_norm and q_norm in v_norm:
                    score = max(score, 70.0)

            searchable = f"{name} {name_en} {definition}"
            overlap = _jaccard(q_bigrams, _char_bigrams(searchable))
            seq = SequenceMatcher(None, q_norm, _norm(name)).ratio() if name else 0.0
            score += overlap * 30.0 + seq * 10.0

            if row.get("core_level") == "core":
                score += 1.0

            matches.append(
                NodeMatch(
                    id=row["id"],
                    name=name,
                    name_en=name_en,
                    semantic_type=row["semantic_type"] or "",
                    core_level=row["core_level"] or "",
                    definition=definition,
                    score=round(score, 4),
                )
            )

        matches.sort(key=lambda m: (-m.score, m.id))
        return matches[:limit]

    def find_components(self, whole_id: str, *, limit: int = 20) -> list[GraphNeighbor]:
        """Return direct components of a whole concept across all relation layers.

        Composition is not a shortest-path problem. A KG commonly stores
        `part-[:PART_OF]->whole`, while an explanation such as "CPU由哪些部分组成"
        should be narrated from the whole outward to all direct parts.

        This query therefore understands the semantic direction of both:
          - part -[:PART_OF]-> whole
          - whole -[:CONTAINS]-> part

        but returns a common traversal direction: whole -> part.
        """
        if not (1 <= int(limit) <= 200):
            raise ValueError("limit must be between 1 and 200")

        cypher = f"""
        MATCH (whole:KnowledgeNode {{id: $whole_id}})-[r]-(part:KnowledgeNode)
        WHERE coalesce(part.status, 'active') = 'active'
          AND {_FACT_FILTER}
          AND (
                (type(r) = 'PART_OF' AND endNode(r) = whole)
             OR (type(r) = 'CONTAINS' AND startNode(r) = whole)
          )
        RETURN
          part.id AS id,
          coalesce(part.name, '') AS name,
          coalesce(part.name_en, '') AS name_en,
          coalesce(part.semantic_type, '') AS semantic_type,
          coalesce(part.core_level, '') AS core_level,
          coalesce(part.definition, '') AS definition,
          {{
              id: r.id,
              relation_layer: coalesce(r.relation_layer, 'semantic'),
              type: type(r),
              stored_start_id: startNode(r).id,
              stored_end_id: endNode(r).id,
              traversal_from: whole.id,
              traversal_to: part.id,
              confidence: coalesce(r.confidence, 1.0),
              default_animation_pattern: coalesce(r.default_animation_pattern, ''),
              animation_candidates: coalesce(r.animation_candidates, '')
          }} AS relationship
        ORDER BY
          {_LAYER_ORDER},
          CASE coalesce(part.core_level, '')
            WHEN 'core' THEN 0
            WHEN 'bridge' THEN 1
            ELSE 2
          END,
          part.id
        LIMIT {int(limit)}
        """

        rows = self.client.read(cypher, {"whole_id": whole_id})
        return [
            GraphNeighbor(
                id=str(row.get("id", "")),
                name=str(row.get("name", "")),
                name_en=str(row.get("name_en", "")),
                semantic_type=str(row.get("semantic_type", "")),
                core_level=str(row.get("core_level", "")),
                definition=str(row.get("definition", "")),
                relationship=dict(row.get("relationship") or {}),
            )
            for row in rows
            if row.get("id")
        ]

    def find_relation_neighbors(
        self,
        root_id: str,
        relation_types: tuple[str, ...] | list[str],
        *,
        limit: int = 20,
    ) -> list[GraphNeighbor]:
        """Return neighbors of selected relation types across all relation layers.

        The KG fact direction is preserved in stored_start_id/stored_end_id,
        while traversal_from/traversal_to is normalized to root -> neighbor for
        explanation structuring. This is useful for interface-role explanations
        where the same concept may connect to multiple surrounding layers.
        """
        if not (1 <= int(limit) <= 200):
            raise ValueError("limit must be between 1 and 200")

        allowed = tuple(dict.fromkeys(str(x).strip().upper() for x in relation_types if str(x).strip()))
        if not allowed:
            return []
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", x) for x in allowed):
            raise ValueError("relation_types contain an invalid Neo4j relationship type")

        cypher = f"""
        MATCH (root:KnowledgeNode {{id: $root_id}})-[r]-(neighbor:KnowledgeNode)
        WHERE coalesce(neighbor.status, 'active') = 'active'
          AND {_FACT_FILTER}
          AND type(r) IN $relation_types
        RETURN
          neighbor.id AS id,
          coalesce(neighbor.name, '') AS name,
          coalesce(neighbor.name_en, '') AS name_en,
          coalesce(neighbor.semantic_type, '') AS semantic_type,
          coalesce(neighbor.core_level, '') AS core_level,
          coalesce(neighbor.definition, '') AS definition,
          {{
              id: r.id,
              relation_layer: coalesce(r.relation_layer, 'semantic'),
              type: type(r),
              stored_start_id: startNode(r).id,
              stored_end_id: endNode(r).id,
              traversal_from: root.id,
              traversal_to: neighbor.id,
              confidence: coalesce(r.confidence, 1.0),
              default_animation_pattern: coalesce(r.default_animation_pattern, ''),
              animation_candidates: coalesce(r.animation_candidates, '')
          }} AS relationship
        ORDER BY
          {_LAYER_ORDER},
          CASE coalesce(neighbor.core_level, '')
            WHEN 'core' THEN 0
            WHEN 'bridge' THEN 1
            ELSE 2
          END,
          neighbor.id
        LIMIT {int(limit)}
        """

        rows = self.client.read(
            cypher,
            {"root_id": root_id, "relation_types": list(allowed)},
        )
        return [
            GraphNeighbor(
                id=str(row.get("id", "")),
                name=str(row.get("name", "")),
                name_en=str(row.get("name_en", "")),
                semantic_type=str(row.get("semantic_type", "")),
                core_level=str(row.get("core_level", "")),
                definition=str(row.get("definition", "")),
                relationship=dict(row.get("relationship") or {}),
            )
            for row in rows
            if row.get("id")
        ]

    def find_relations_among(
        self,
        node_ids: tuple[str, ...] | list[str],
        *,
        limit: int = 100,
    ) -> list[GraphRelation]:
        """Return direct relationships whose two endpoints are in node_ids.

        This is the preferred evidence source for questions such as
        "A、B、C之间是什么关系". It avoids inventing a long path merely to
        connect concepts that already have local relations in any layer.
        """
        ids = list(dict.fromkeys(str(x) for x in node_ids if str(x)))
        if len(ids) < 2:
            return []
        if not (1 <= int(limit) <= 500):
            raise ValueError("limit must be between 1 and 500")

        cypher = f"""
        MATCH (a:KnowledgeNode)-[r]->(b:KnowledgeNode)
        WHERE a.id IN $node_ids
          AND b.id IN $node_ids
          AND {_FACT_FILTER}
          AND coalesce(a.status, 'active') = 'active'
          AND coalesce(b.status, 'active') = 'active'
        RETURN
          a.id AS source_id,
          coalesce(a.name, '') AS source_name,
          b.id AS target_id,
          coalesce(b.name, '') AS target_name,
          {{
              id: r.id,
              relation_layer: coalesce(r.relation_layer, 'semantic'),
              type: type(r),
              stored_start_id: a.id,
              stored_end_id: b.id,
              traversal_from: a.id,
              traversal_to: b.id,
              confidence: coalesce(r.confidence, 1.0),
              default_animation_pattern: coalesce(r.default_animation_pattern, ''),
              animation_candidates: coalesce(r.animation_candidates, ''),
              mediated_by: coalesce(r.mediated_by, '')
          }} AS relationship
        ORDER BY {_LAYER_ORDER}, coalesce(r.confidence, 1.0) DESC, a.id, b.id
        LIMIT {int(limit)}
        """
        rows = self.client.read(cypher, {"node_ids": ids})
        return [
            GraphRelation(
                source_id=str(row.get("source_id", "")),
                source_name=str(row.get("source_name", "")),
                target_id=str(row.get("target_id", "")),
                target_name=str(row.get("target_name", "")),
                relationship=dict(row.get("relationship") or {}),
            )
            for row in rows
            if row.get("source_id") and row.get("target_id")
        ]

    def find_connecting_hubs(
        self,
        node_ids: tuple[str, ...] | list[str],
        *,
        relation_types: tuple[str, ...] | list[str] = ("PART_OF", "CONTAINS"),
        limit: int = 10,
    ) -> list[GraphNeighbor]:
        """Find a one-hop hub that structurally connects several named nodes.

        Example: CPU, Memory and I/O System may all connect to Hardware. This
        supports "where do these sit?" questions without forcing a long path.
        """
        ids = list(dict.fromkeys(str(x) for x in node_ids if str(x)))
        if len(ids) < 2:
            return []
        allowed = tuple(dict.fromkeys(str(x).strip().upper() for x in relation_types if str(x).strip()))
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", x) for x in allowed):
            raise ValueError("relation_types contain an invalid Neo4j relationship type")
        cypher = f"""
        MATCH (named:KnowledgeNode)-[r]-(hub:KnowledgeNode)
        WHERE named.id IN $node_ids
          AND NOT hub.id IN $node_ids
          AND {_FACT_FILTER}
          AND type(r) IN $relation_types
          AND coalesce(hub.status, 'active') = 'active'
        WITH hub, collect(DISTINCT named.id) AS covered, collect(DISTINCT r) AS rels
        WHERE size(covered) >= 2
        RETURN
          hub.id AS id,
          coalesce(hub.name, '') AS name,
          coalesce(hub.name_en, '') AS name_en,
          coalesce(hub.semantic_type, '') AS semantic_type,
          coalesce(hub.core_level, '') AS core_level,
          coalesce(hub.definition, '') AS definition,
          covered,
          size(covered) AS coverage,
          {{
              id: '', type: 'CONNECTING_HUB', stored_start_id: '', stored_end_id: '',
              traversal_from: hub.id, traversal_to: '', confidence: 1.0,
              default_animation_pattern: '', animation_candidates: '',
              covered_ids: covered
          }} AS relationship
        ORDER BY coverage DESC, hub.id
        LIMIT {int(limit)}
        """
        rows = self.client.read(cypher, {"node_ids": ids, "relation_types": list(allowed)})
        return [
            GraphNeighbor(
                id=str(row.get("id", "")),
                name=str(row.get("name", "")),
                name_en=str(row.get("name_en", "")),
                semantic_type=str(row.get("semantic_type", "")),
                core_level=str(row.get("core_level", "")),
                definition=str(row.get("definition", "")),
                relationship=dict(row.get("relationship") or {}),
            )
            for row in rows
            if row.get("id")
        ]

    def find_mediated_relations(
        self,
        mediator_id: str,
        *,
        limit: int = 20,
    ) -> list[GraphRelation]:
        """Return KG relations that explicitly name mediator_id in r.mediated_by.

        This makes concepts such as Compiler useful even when the compiler is
        modeled as the mediator of High-level Program -> Assembly Program rather
        than as an endpoint of that TRANSFORMS_TO edge.
        """
        if not (1 <= int(limit) <= 200):
            raise ValueError("limit must be between 1 and 200")
        cypher = f"""
        MATCH (a:KnowledgeNode)-[r]->(b:KnowledgeNode)
        WHERE coalesce(r.mediated_by, '') = $mediator_id
          AND {_FACT_FILTER}
        RETURN
          a.id AS source_id, coalesce(a.name, '') AS source_name,
          b.id AS target_id, coalesce(b.name, '') AS target_name,
          {{
              id: r.id, relation_layer: coalesce(r.relation_layer, 'semantic'), type: type(r), stored_start_id: a.id, stored_end_id: b.id,
              traversal_from: a.id, traversal_to: b.id,
              confidence: coalesce(r.confidence, 1.0),
              default_animation_pattern: coalesce(r.default_animation_pattern, ''),
              animation_candidates: coalesce(r.animation_candidates, ''),
              mediated_by: coalesce(r.mediated_by, '')
          }} AS relationship
        ORDER BY {_LAYER_ORDER}, coalesce(r.confidence, 1.0) DESC
        LIMIT {int(limit)}
        """
        rows = self.client.read(cypher, {"mediator_id": mediator_id})
        return [
            GraphRelation(
                source_id=str(row.get("source_id", "")),
                source_name=str(row.get("source_name", "")),
                target_id=str(row.get("target_id", "")),
                target_name=str(row.get("target_name", "")),
                relationship=dict(row.get("relationship") or {}),
            )
            for row in rows
            if row.get("source_id") and row.get("target_id")
        ]

    def find_paths_between(
        self,
        source_id: str,
        target_id: str,
        *,
        max_hops: int | None = None,
        limit: int | None = None,
    ) -> list[ExplanationPath]:
        """Find bounded simple-ish paths between two KG nodes.

        Relationships are traversed in either direction because explanation paths
        may need to read a stored relation backwards (e.g. Processor-[:EXECUTES]->Instruction
        can be narrated as Instruction -> Processor). Stored direction is returned
        separately from traversal direction.
        """
        max_hops = max_hops or self.settings.query.max_hops
        limit = self.settings.query.paths_per_pair if limit is None else limit

        if not (1 <= int(max_hops) <= 8):
            raise ValueError("max_hops must be between 1 and 8")
        if int(limit) < 1:
            raise ValueError("limit must be positive")

        # Cypher does not allow a parameter for the upper bound of a variable-length pattern.
        # max_hops is validated above before interpolation.
        cypher = f"""
        MATCH p=(a:KnowledgeNode {{id: $source_id}})-[*1..{int(max_hops)}]-(b:KnowledgeNode {{id: $target_id}})
        WITH p, nodes(p) AS ns, relationships(p) AS rs
        WHERE all(r IN rs WHERE {_FACT_FILTER})
        RETURN
          [n IN ns | {{
              id: n.id,
              name: coalesce(n.name, ''),
              name_en: coalesce(n.name_en, ''),
              semantic_type: coalesce(n.semantic_type, ''),
              core_level: coalesce(n.core_level, '')
          }}] AS nodes,
          [i IN range(0, size(rs)-1) | {{
              id: rs[i].id,
              element_id: elementId(rs[i]),
              mediated_by: coalesce(rs[i].mediated_by, ''),
              relation_layer: coalesce(rs[i].relation_layer, 'semantic'),
              type: type(rs[i]),
              stored_start_id: startNode(rs[i]).id,
              stored_end_id: endNode(rs[i]).id,
              traversal_from: ns[i].id,
              traversal_to: ns[i+1].id,
              confidence: coalesce(rs[i].confidence, 1.0),
              default_animation_pattern: coalesce(rs[i].default_animation_pattern, ''),
              animation_candidates: coalesce(rs[i].animation_candidates, '')
          }}] AS rels
        ORDER BY CASE WHEN any(r IN rs WHERE toLower(trim(coalesce(r.relation_layer, 'semantic'))) IN ['explan', 'explanation', 'explanatory']) THEN 0 ELSE 1 END,
          length(p) ASC, [n IN ns | n.id], [r IN rs | elementId(r)]
        LIMIT {int(limit)}
        """

        rows = self.client.read(cypher, {"source_id": source_id, "target_id": target_id})
        output: list[ExplanationPath] = []
        seen: set[tuple] = set()

        for row in rows:
            nodes = row.get("nodes", [])
            rels = row.get("rels", [])
            ids = tuple(str(n.get("id", "")) for n in nodes)
            key = path_key(ExplanationPath(ids, (), tuple(rels), 0.0))
            if not ids or key in seen:
                continue
            seen.add(key)
            names = tuple(str(n.get("name", n.get("id", ""))) for n in nodes)
            output.append(
                ExplanationPath(
                    node_ids=ids,
                    node_names=names,
                    relationships=tuple(rels),
                    score=0.0,
                )
            )

        return output

    def generate_candidate_paths(self, question: str, *, limit: int | None = None, max_hops: int | None = None) -> tuple[list[NodeMatch], list[ExplanationPath]]:
        """Discover paths, score their evidence, then apply intent before truncation."""
        candidate_limit = self.settings.query.candidate_path_limit if limit is None else int(limit)
        if candidate_limit < 1:
            raise ValueError("limit must be positive")
        matches = self.find_related_nodes(question)
        seeds = matches[: self.settings.query.seed_nodes]
        score_by_id = {m.id: m.score for m in matches}
        # Retrieval budget must not collapse to the final answer limit.
        retrieval_limit = max(candidate_limit, self.settings.query.paths_per_pair)

        candidates: list[ExplanationPath] = []
        seen_paths: set[tuple] = set()

        for left, right in itertools.combinations(seeds, 2):
            paths = self.find_paths_between(
                left.id,
                right.id,
                max_hops=max_hops if max_hops is not None else self.settings.query.max_hops,
                limit=retrieval_limit,
            )
            for path in paths:
                # Preserve parallel edges, but deduplicate reverse traversals.
                canonical = path_key(path)
                if canonical in seen_paths:
                    continue
                seen_paths.add(canonical)

                rel_conf = [float(r.get("confidence", 1.0) or 1.0) for r in path.relationships]
                mean_conf = sum(rel_conf) / len(rel_conf) if rel_conf else 0.0
                animation_coverage = (
                    sum(1 for r in path.relationships if r.get("default_animation_pattern"))
                    / max(1, len(path.relationships))
                )
                covered_seed_scores = [score_by_id[nid] for nid in path.node_ids if nid in score_by_id]
                endpoint_relevance = (
                    (score_by_id.get(path.node_ids[0], 0.0) + score_by_id.get(path.node_ids[-1], 0.0)) / 2.0
                )
                seed_coverage = len(covered_seed_scores) / max(1, len(seeds))
                length_penalty = max(0, path.hop_count - 2) * 5.0

                score = (
                    0.50 * endpoint_relevance
                    + 20.0 * mean_conf
                    + 12.0 * seed_coverage
                    + 8.0 * animation_coverage
                    - length_penalty
                )

                candidates.append(
                    ExplanationPath(
                        node_ids=path.node_ids,
                        node_names=path.node_names,
                        relationships=path.relationships,
                        score=round(score, 4),
                    )
                )

        # Local imports avoid the models' module-level dependency on kg.query.
        from explanation.question_analyzer import QuestionAnalyzer
        from explanation.path_ranker import ExplanationPathRanker
        analysis = QuestionAnalyzer().analyze(question, matches)
        interface_paths = []
        if analysis.intent.value == 'interface_role':
            # The main pipeline consumes candidates directly rather than invoking
            # ExplanationPlanner; route interface evidence here as well.
            from explanation.evidence.interface import InterfaceEvidenceStrategy
            from explanation.evidence.base import EvidenceContext, graph_score_path
            from explanation.models import ExplanationGoal
            evidence = InterfaceEvidenceStrategy().collect(EvidenceContext(
                ExplanationGoal('retrieval', question, analysis), tuple(matches),
                self, ExplanationPathRanker(), self.settings))
            if evidence.root:
                by_id = {m.id: m for m in matches}
                for neighbor in (*evidence.neighbors, *evidence.components):
                    by_id.setdefault(neighbor.id, NodeMatch(neighbor.id, neighbor.name,
                        neighbor.name_en, neighbor.semantic_type, neighbor.core_level,
                        neighbor.definition, 0.0))
                    rel = dict(neighbor.relationship)
                    rel.update(traversal_from=evidence.root.id, traversal_to=neighbor.id)
                    p = ExplanationPath((evidence.root.id, neighbor.id),
                        (evidence.root.name, neighbor.name), (rel,), 0.0)
                    if path_key(p) not in {path_key(x) for x in interface_paths}:
                        interface_paths.append(graph_score_path(p, tuple(matches)))
                matches = list(by_id.values())
        ranked = ExplanationPathRanker().rank(analysis, candidates)
        # Direct interface tiers reserve the local nucleus before unrelated paths.
        ordered = {path_key(p): p for p in interface_paths}
        for item in ranked:
            ordered.setdefault(path_key(item.path), item.path)
        return matches, list(ordered.values())[:candidate_limit]


def _format_path(path: ExplanationPath) -> str:
    parts: list[str] = [path.node_names[0]]
    for i, rel in enumerate(path.relationships):
        rel_type = rel.get("type", "?")
        arrow = "→" if rel.get("stored_start_id") == rel.get("traversal_from") else "←"
        parts.append(f" -[{rel_type}]{arrow} {path.node_names[i+1]}")
    return "".join(parts)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the Computer Core Neo4j knowledge graph")
    parser.add_argument("question", nargs="?", help="Natural-language question")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--source-id")
    parser.add_argument("--target-id")
    parser.add_argument("--max-hops", type=int)
    parser.add_argument("--limit", type=int, default=10, help="Maximum candidate paths to retain and print (overrides config limits)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    settings = load_settings(args.config)

    with Neo4jClient(settings.neo4j) as client:
        service = KGQueryService(client, settings)

        if args.source_id and args.target_id:
            paths = service.find_paths_between(
                args.source_id,
                args.target_id,
                max_hops=args.max_hops,
                limit=args.limit,
            )
            if args.as_json:
                print(json.dumps([asdict(p) for p in paths], ensure_ascii=False, indent=2))
                return
            for i, path in enumerate(paths, 1):
                print(f"{i:02d}. {_format_path(path)}")
            return

        if not args.question:
            raise SystemExit("Provide a question, or both --source-id and --target-id")

        matches, paths = service.generate_candidate_paths(args.question, limit=args.limit, max_hops=args.max_hops)

        if args.as_json:
            print(
                json.dumps(
                    {
                        "question": args.question,
                        "matched_nodes": [asdict(m) for m in matches],
                        "candidate_paths": [asdict(p) for p in paths[: args.limit]],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        print("\nMatched nodes")
        print("-------------")
        for m in matches:
            print(f"{m.id:>6}  {m.score:8.3f}  {m.name} / {m.name_en}")

        print("\nCandidate paths")
        print("---------------")
        for i, path in enumerate(paths[: args.limit], 1):
            print(f"{i:02d}. score={path.score:8.3f} hops={path.hop_count}  {_format_path(path)}")


if __name__ == "__main__":
    main()
