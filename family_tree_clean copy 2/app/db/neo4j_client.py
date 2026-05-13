"""
Neo4j client.

Same shape as the original but reads configuration from a single source
(core.config) instead of scattered os.getenv calls. Behaviour is unchanged:
a long-lived driver opened at startup, closed at shutdown, used via a session
per query.
"""
import time
from typing import Optional

from neo4j import Driver, GraphDatabase

from app.core.config import config
from app.utill.LoggingHandler import LoggingHandler

logger = LoggingHandler.get_logger(__name__)


class Neo4jClient:
    def __init__(self):
        self._driver: Optional[Driver] = None

    def connect(self):
        logger.info(f"neo4j.connect | uri={config.neo4j_uri} | user={config.neo4j_user}")
        try:
            self._driver = GraphDatabase.driver(
                config.neo4j_uri,
                auth=(config.neo4j_user, config.neo4j_password),
            )
            logger.info("neo4j.connect.ok")
        except Exception:
            logger.exception(f"neo4j.connect.failed | uri={config.neo4j_uri}")
            raise

    def close(self):
        if self._driver:
            logger.info("neo4j.close")
            self._driver.close()
            self._driver = None

    def run(self, cypher: str, params: dict = None, db: Optional[str] = None):
        if self._driver is None:
            logger.info("neo4j.run | driver not initialised — connecting lazily")
            self.connect()
        database = db or config.neo4j_db
        param_keys = list((params or {}).keys())
        logger.info(
            f"neo4j.run.start | db={database} | param_keys={param_keys} | cypher_len={len(cypher)}"
        )
        start = time.perf_counter()
        try:
            with self._driver.session(database=database) as session:
                result = list(session.run(cypher, params or {}))
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                f"neo4j.run.failed | db={database} | duration_ms={duration_ms:.2f}"
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            f"neo4j.run.ok | db={database} | rows={len(result)} | duration_ms={duration_ms:.2f}"
        )
        return result


neo4j_client = Neo4jClient()
