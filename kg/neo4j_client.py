from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from neo4j import GraphDatabase, ManagedTransaction

from .config import Neo4jSettings

T = TypeVar("T")


class Neo4jClient:
    """Small Neo4j driver wrapper shared by importer and query services."""

    def __init__(self, settings: Neo4jSettings):
        if not settings.password:
            raise ValueError(
                "NEO4J_PASSWORD is not set. Set it in your shell/environment; "
                "do not commit it into config.toml."
            )

        self.settings = settings
        self.driver = GraphDatabase.driver(
            settings.uri,
            auth=(settings.user, settings.password),
        )

    def __enter__(self) -> "Neo4jClient":
        self.verify_connectivity()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def verify_connectivity(self) -> None:
        self.driver.verify_connectivity()

    def close(self) -> None:
        self.driver.close()

    def execute_read(self, work: Callable[[ManagedTransaction], T]) -> T:
        with self.driver.session(database=self.settings.database) as session:
            return session.execute_read(work)

    def execute_write(self, work: Callable[[ManagedTransaction], T]) -> T:
        with self.driver.session(database=self.settings.database) as session:
            return session.execute_write(work)

    def read(self, cypher: str, parameters: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        params = dict(parameters or {})

        def _work(tx: ManagedTransaction) -> list[dict[str, Any]]:
            return [record.data() for record in tx.run(cypher, params)]

        return self.execute_read(_work)

    def write(self, cypher: str, parameters: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        params = dict(parameters or {})

        def _work(tx: ManagedTransaction) -> list[dict[str, Any]]:
            return [record.data() for record in tx.run(cypher, params)]

        return self.execute_write(_work)

    def create_schema(self) -> None:
        """Create the minimal schema needed by the v0.x knowledge graph."""
        self.write(
            """
            CREATE CONSTRAINT knowledge_node_id IF NOT EXISTS
            FOR (n:KnowledgeNode)
            REQUIRE n.id IS UNIQUE
            """
        )

    def clear_database(self) -> None:
        """Delete all nodes and relationships in the configured database.

        Use only for a local/dev database dedicated to this project.
        """
        self.write("MATCH (n) DETACH DELETE n")

    def counts(self) -> dict[str, int]:
        rows = self.read(
            """
            MATCH (n:KnowledgeNode)
            WITH count(n) AS nodes
            OPTIONAL MATCH ()-[r]->()
            RETURN nodes, count(r) AS relationships
            """
        )
        if not rows:
            return {"nodes": 0, "relationships": 0}
        return {
            "nodes": int(rows[0].get("nodes", 0)),
            "relationships": int(rows[0].get("relationships", 0)),
        }
