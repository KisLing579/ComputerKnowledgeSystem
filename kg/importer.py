from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from typing import Any, Iterable

import pandas as pd

from .config import Settings, load_settings
from .neo4j_client import Neo4jClient

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

NODE_ID_COL = "node_id:ID"
NODE_LABELS_COL = "labels:LABEL"
REL_START_COL = ":START_ID"
REL_END_COL = ":END_ID"
REL_TYPE_COL = ":TYPE"


class ImportValidationError(ValueError):
    pass


def _none_if_nan(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _normalize_property_key(column: str) -> str:
    """Convert Neo4j-import-style Excel headers to normal property keys."""
    return column.split(":", 1)[0] if ":" in column and not column.startswith(":") else column


def _clean_record(row: dict[str, Any], *, excluded: set[str]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for key, raw_value in row.items():
        if key in excluded:
            continue
        value = _none_if_nan(raw_value)
        if value is None:
            continue
        prop_key = _normalize_property_key(key)
        if isinstance(value, str):
            value = value.strip()
        props[prop_key] = value
    return props


def _parse_labels(raw: Any) -> tuple[str, ...]:
    text = str(_none_if_nan(raw) or "KnowledgeNode")
    labels = [x.strip() for x in text.split(";") if x.strip()]
    if "KnowledgeNode" not in labels:
        labels.insert(0, "KnowledgeNode")

    for label in labels:
        if not _SAFE_IDENTIFIER.fullmatch(label):
            raise ImportValidationError(f"Unsafe Neo4j label: {label!r}")
    return tuple(dict.fromkeys(labels))


def _validate_rel_type(rel_type: str) -> str:
    rel_type = rel_type.strip().upper()
    if not _SAFE_IDENTIFIER.fullmatch(rel_type):
        raise ImportValidationError(f"Unsafe relationship type: {rel_type!r}")
    return rel_type


def _chunks(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def load_excel(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    workbook = settings.data.workbook
    if not workbook.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook}")

    nodes = pd.read_excel(workbook, sheet_name=settings.data.nodes_sheet)
    relations = pd.read_excel(workbook, sheet_name=settings.data.relations_sheet)

    required_node_cols = {NODE_ID_COL, "name", NODE_LABELS_COL}
    required_rel_cols = {"rel_id", REL_START_COL, REL_END_COL, REL_TYPE_COL}

    missing_nodes = required_node_cols - set(nodes.columns)
    missing_rels = required_rel_cols - set(relations.columns)
    if missing_nodes:
        raise ImportValidationError(f"KG_Nodes missing columns: {sorted(missing_nodes)}")
    if missing_rels:
        raise ImportValidationError(f"KG_Relations missing columns: {sorted(missing_rels)}")

    # Older workbooks have no teaching dependency layer. Preserve the public
    # two-frame API and validate IDs/endpoints across both relationship sheets.
    with pd.ExcelFile(workbook) as excel:
        if settings.data.dependencies_sheet in excel.sheet_names:
            dependencies = pd.read_excel(excel, sheet_name=settings.data.dependencies_sheet)
            required = {"dependency_id", REL_START_COL, REL_END_COL, REL_TYPE_COL}
            missing = required - set(dependencies.columns)
            if missing:
                raise ImportValidationError(
                    f"{settings.data.dependencies_sheet} missing columns: {sorted(missing)}"
                )
            if settings.importer.active_only and "status" in dependencies.columns:
                dependencies = dependencies[
                    dependencies["status"].fillna("").str.lower() == "active"
                ].copy()
            for row in dependencies.to_dict(orient="records"):
                if _validate_rel_type(str(row[REL_TYPE_COL])) != "PREREQUISITE_OF":
                    raise ImportValidationError("Dependency type must be PREREQUISITE_OF")
                if str(row[REL_START_COL]).strip() == str(row[REL_END_COL]).strip():
                    raise ImportValidationError("A node cannot be its own prerequisite")
            dependencies["rel_id"] = dependencies["dependency_id"]
            dependencies["relation_layer"] = "teaching"
            # A missing status should mean active, including when the fact
            # sheet supplies a status column during concatenation.
            if "status" not in dependencies.columns:
                dependencies["status"] = "active"
            if "status" not in relations.columns:
                relations["status"] = "active"
            relations = pd.concat([relations, dependencies], ignore_index=True)

    if settings.importer.active_only:
        if "status" in nodes.columns:
            nodes = nodes[nodes["status"].fillna("").str.lower() == "active"]
        if "status" in relations.columns:
            relations = relations[relations["status"].fillna("").str.lower() == "active"]

    return nodes.copy(), relations.copy()


def _prepare_nodes(df: pd.DataFrame) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)

    seen_ids: set[str] = set()
    for raw_row in df.to_dict(orient="records"):
        node_id = str(_none_if_nan(raw_row.get(NODE_ID_COL)) or "").strip()
        if not node_id:
            raise ImportValidationError("Node row has empty node_id")
        if node_id in seen_ids:
            raise ImportValidationError(f"Duplicate node_id: {node_id}")
        seen_ids.add(node_id)

        labels = _parse_labels(raw_row.get(NODE_LABELS_COL))
        props = _clean_record(raw_row, excluded={NODE_ID_COL, NODE_LABELS_COL})
        props["id"] = node_id
        groups[labels].append({"id": node_id, "props": props})

    return groups


def _prepare_relations(df: pd.DataFrame, node_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_rel_ids: set[str] = set()

    for raw_row in df.to_dict(orient="records"):
        rel_id = str(_none_if_nan(raw_row.get("rel_id")) or "").strip()
        start_id = str(_none_if_nan(raw_row.get(REL_START_COL)) or "").strip()
        end_id = str(_none_if_nan(raw_row.get(REL_END_COL)) or "").strip()
        rel_type = _validate_rel_type(str(_none_if_nan(raw_row.get(REL_TYPE_COL)) or ""))

        if not rel_id or not start_id or not end_id or not rel_type:
            raise ImportValidationError(f"Invalid relationship row: {raw_row}")
        if rel_id in seen_rel_ids:
            raise ImportValidationError(f"Duplicate rel_id: {rel_id}")
        seen_rel_ids.add(rel_id)

        missing = [node_id for node_id in (start_id, end_id) if node_id not in node_ids]
        if missing:
            raise ImportValidationError(
                f"Relationship {rel_id} references missing node(s): {missing}"
            )

        props = _clean_record(
            raw_row,
            excluded={"rel_id", REL_START_COL, REL_END_COL, REL_TYPE_COL},
        )
        props["id"] = rel_id
        groups[rel_type].append(
            {
                "id": rel_id,
                "start_id": start_id,
                "end_id": end_id,
                "props": props,
            }
        )

    return groups


def import_nodes(client: Neo4jClient, df: pd.DataFrame, batch_size: int) -> int:
    groups = _prepare_nodes(df)
    imported = 0

    for labels, rows in groups.items():
        labels_cypher = "".join(f":{label}" for label in labels)
        cypher = f"""
        UNWIND $rows AS row
        MERGE (n:KnowledgeNode {{id: row.id}})
        SET n += row.props
        SET n{labels_cypher}
        RETURN count(n) AS imported
        """
        for batch in _chunks(rows, batch_size):
            result = client.write(cypher, {"rows": batch})
            imported += int(result[0]["imported"]) if result else 0

    return imported


def import_relationships(
    client: Neo4jClient,
    df: pd.DataFrame,
    node_ids: set[str],
    batch_size: int,
) -> int:
    groups = _prepare_relations(df, node_ids)
    imported = 0

    for rel_type, rows in groups.items():
        cypher = f"""
        UNWIND $rows AS row
        MATCH (a:KnowledgeNode {{id: row.start_id}})
        MATCH (b:KnowledgeNode {{id: row.end_id}})
        MERGE (a)-[r:{rel_type} {{id: row.id}}]->(b)
        SET r += row.props
        RETURN count(r) AS imported
        """
        for batch in _chunks(rows, batch_size):
            result = client.write(cypher, {"rows": batch})
            imported += int(result[0]["imported"]) if result else 0

    return imported


def import_workbook(settings: Settings, *, reset: bool = False, dry_run: bool = False) -> dict[str, int]:
    nodes_df, relations_df = load_excel(settings)
    node_ids = set(nodes_df[NODE_ID_COL].astype(str).str.strip())

    # Validate before touching Neo4j.
    _prepare_nodes(nodes_df)
    _prepare_relations(relations_df, node_ids)

    if dry_run:
        return {
            "nodes": len(nodes_df),
            "relationships": len(relations_df),
        }

    with Neo4jClient(settings.neo4j) as client:
        if reset:
            client.clear_database()
        client.create_schema()

        imported_nodes = import_nodes(client, nodes_df, settings.importer.batch_size)
        imported_rels = import_relationships(
            client,
            relations_df,
            node_ids,
            settings.importer.batch_size,
        )
        counts = client.counts()

    return {
        "imported_nodes": imported_nodes,
        "imported_relationships": imported_rels,
        "database_nodes": counts["nodes"],
        "database_relationships": counts["relationships"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import Computer Core KG Excel into Neo4j")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all existing nodes/relationships in the configured Neo4j database first",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate Excel and report row counts without connecting to Neo4j",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    settings = load_settings(args.config)
    result = import_workbook(settings, reset=args.reset, dry_run=args.dry_run)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
