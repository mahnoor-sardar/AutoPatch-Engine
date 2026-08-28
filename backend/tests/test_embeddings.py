from types import SimpleNamespace

from app.services.embeddings import (
    NEAREST_SYMBOL_SQL,
    similar_symbols,
    store_symbol_embeddings,
)


def test_similarity_query_uses_native_pgvector_operator():
    assert "<=>" in NEAREST_SYMBOL_SQL
    assert "CAST(:query AS vector)" in NEAREST_SYMBOL_SQL
    from app.services import embeddings

    assert not hasattr(embeddings, "_cosine")


def test_similar_symbols_is_empty_without_pgvector(monkeypatch):
    from app.services import embeddings

    monkeypatch.setattr(embeddings, "pgvector_is_ready", lambda db: False)
    result = similar_symbols(SimpleNamespace(), 1, "calculate")
    assert result == []


def test_store_embeddings_skips_without_pgvector(monkeypatch):
    from app.services import embeddings

    monkeypatch.setattr(embeddings, "ensure_pgvector", lambda bind: False)

    class DB:
        def get_bind(self):
            return None

        def query(self, *args, **kwargs):
            raise AssertionError("must not load symbols when pgvector is unavailable")

    store_symbol_embeddings(DB(), 1)


def test_store_embeddings_writes_vector_not_json(monkeypatch):
    from app.services import embeddings
    from app.models import Symbol

    executed = []

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [
                Symbol(
                    id=9,
                    run_id=1,
                    path="a.py",
                    name="fn",
                    kind="function",
                    start_line=1,
                    embedding="should-not-stay-json",
                )
            ]

    class DB:
        def get_bind(self):
            return "bind"

        def query(self, model):
            assert model is Symbol
            return Query()

        def execute(self, statement, params=None):
            executed.append((str(statement), params))

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(embeddings, "ensure_pgvector", lambda bind: True)
    monkeypatch.setattr(embeddings, "pgvector_is_ready", lambda db: True)
    monkeypatch.setattr(
        embeddings,
        "embed_texts",
        lambda texts: [[0.1] * embeddings.EMBEDDING_DIMENSIONS],
    )
    store_symbol_embeddings(DB(), 1)
    assert executed
    sql, params = executed[0]
    assert "symbol_vectors" in sql
    assert "CAST(:embedding AS vector)" in sql
    assert params["symbol_id"] == 9
    assert not params["embedding"].startswith("{")
    assert params["embedding"].startswith("[")
