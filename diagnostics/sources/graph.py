"""Neo4j access for the network: sites, their detectors (BELONG_TO) and approach links (EGRESS).

The Cypher text lives in the schema (graph.*), parameterised with $region and $sites.
"""
from __future__ import annotations

from .base import DataUnavailable


class GraphReader:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        if not password:
            raise DataUnavailable("Neo4j is not configured: set NEO4J_PASSWORD (and NEO4J_URI / NEO4J_USER).")
        from neo4j import GraphDatabase
        self._driver = GraphDatabase.driver(uri, auth=(user, password), max_connection_lifetime=300)
        self._database = database
        self.queries: list[tuple[str, dict]] = []

    def rows(self, cypher: str, params: dict) -> list[dict]:
        self.queries.append((cypher, {k: (v if not isinstance(v, list) else f"<{len(v)} values>") for k, v in params.items()}))
        try:
            with self._driver.session(database=self._database) as session:
                return session.execute_read(lambda tx: [r.data() for r in tx.run(cypher, params)])
        except Exception as exc:  # noqa: BLE001
            raise DataUnavailable(f"Neo4j query failed ({type(exc).__name__}: {str(exc)[:200]})") from exc

    def close(self) -> None:
        self._driver.close()
