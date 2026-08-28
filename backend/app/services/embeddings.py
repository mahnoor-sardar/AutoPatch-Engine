import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Symbol

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 1536
VECTOR_TABLE = "symbol_vectors"

NEAREST_SYMBOL_SQL = f"""
SELECT s.id
FROM symbols s
JOIN {VECTOR_TABLE} v ON v.symbol_id = s.id
WHERE s.run_id = :run_id
ORDER BY v.embedding <=> CAST(:query AS vector)
LIMIT :limit
"""


def ensure_pgvector(bind) -> bool:
    def _create(conn) -> bool:
        available = conn.execute(
            text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        ).scalar()
        if not available:
            return False
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {VECTOR_TABLE} (
                    symbol_id INTEGER PRIMARY KEY
                        REFERENCES symbols(id) ON DELETE CASCADE,
                    embedding vector({EMBEDDING_DIMENSIONS}) NOT NULL
                )
                """
            )
        )
        return True

    try:
        if hasattr(bind, "connect"):
            with bind.begin() as conn:
                return _create(conn)
        return _create(bind)
    except Exception:
        logger.warning("pgvector is not available; skipping vector storage")
        return False


def pgvector_is_ready(db: Session) -> bool:
    try:
        installed = db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        if not installed:
            return False
        names = inspect(db.get_bind()).get_table_names()
        return VECTOR_TABLE in names
    except Exception:
        db.rollback()
        return False


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not settings.llm_api_key or not texts:
        return [[] for _ in texts]

    from litellm import embedding

    kwargs: dict = {
        "model": settings.embedding_model,
        "input": texts,
        "api_key": settings.llm_api_key,
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
    response = embedding(**kwargs)
    return [item["embedding"] for item in response.data]


def store_symbol_embeddings(db: Session, run_id: int) -> None:
    if not ensure_pgvector(db.get_bind()) or not pgvector_is_ready(db):
        return
    symbols = db.query(Symbol).filter(Symbol.run_id == run_id).all()
    if not symbols:
        return
    vectors = embed_texts(
        [f"{row.path}:{row.name}:{row.kind}" for row in symbols]
    )
    for row, vector in zip(symbols, vectors):
        if not vector or len(vector) != EMBEDDING_DIMENSIONS:
            continue
        db.execute(
            text(
                f"""
                INSERT INTO {VECTOR_TABLE} (symbol_id, embedding)
                VALUES (:symbol_id, CAST(:embedding AS vector))
                ON CONFLICT (symbol_id) DO UPDATE
                SET embedding = EXCLUDED.embedding
                """
            ),
            {
                "symbol_id": row.id,
                "embedding": "[" + ",".join(str(value) for value in vector) + "]",
            },
        )
        row.embedding = None
    db.commit()


def similar_symbols(
    db: Session,
    run_id: int,
    query: str,
    limit: int = 5,
) -> list[Symbol]:
    if not pgvector_is_ready(db):
        return []
    query_vectors = embed_texts([query])
    query_vec = query_vectors[0] if query_vectors else []
    if not query_vec or len(query_vec) != EMBEDDING_DIMENSIONS:
        return []
    rows = db.execute(
        text(NEAREST_SYMBOL_SQL),
        {
            "run_id": run_id,
            "query": "[" + ",".join(str(value) for value in query_vec) + "]",
            "limit": limit,
        },
    ).fetchall()
    ids = [row[0] for row in rows]
    if not ids:
        return []
    found = db.query(Symbol).filter(Symbol.id.in_(ids)).all()
    order = {symbol_id: index for index, symbol_id in enumerate(ids)}
    found.sort(key=lambda item: order.get(item.id, 0))
    return found
