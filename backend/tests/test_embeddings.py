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


def test_embed_texts_batches_and_preserves_order(monkeypatch):
    from app.services import embeddings
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_api_base", "")
    sizes = []

    def fake_embedding(**kwargs):
        chunk = kwargs["input"]
        assert len(chunk) <= embeddings.EMBED_BATCH_SIZE
        sizes.append(len(chunk))
        data = [{"embedding": [float(len(text))]} for text in chunk]
        return SimpleNamespace(data=data)

    monkeypatch.setattr("litellm.embedding", fake_embedding)

    def run(n: int) -> None:
        sizes.clear()
        texts = [f"t{i}" for i in range(n)]
        result = embeddings.embed_texts(texts)
        assert [v[0] for v in result] == [float(len(t)) for t in texts]
        assert max(sizes) <= 100
        expected_calls = (n + 99) // 100
        assert len(sizes) == expected_calls
        if n % 100:
            assert sizes[-1] == n % 100
        else:
            assert sizes[-1] == 100

    run(99)
    run(100)
    run(101)
    run(524)


def test_embed_texts_omits_api_base_for_gemini_embedding_models(monkeypatch):
    from app.services import embeddings
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(
        settings,
        "llm_api_base",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    seen = []

    def fake_embedding(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(data=[{"embedding": [0.0]}])

    monkeypatch.setattr("litellm.embedding", fake_embedding)

    monkeypatch.setattr(settings, "embedding_model", "gemini/gemini-embedding-001")
    embeddings.embed_texts(["symbol"])
    assert seen
    assert "api_base" not in seen[0]
    assert seen[0]["model"] == "gemini/gemini-embedding-001"

    seen.clear()
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-3-small")
    embeddings.embed_texts(["symbol"])
    assert seen
    assert seen[0]["api_base"] == (
        "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    assert seen[0]["model"] == "text-embedding-3-small"


def test_embed_texts_requests_1536_dimensions(monkeypatch):
    from app.services import embeddings
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_api_base", "")
    seen = []

    def fake_embedding(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(data=[{"embedding": [0.0]}])

    monkeypatch.setattr("litellm.embedding", fake_embedding)
    embeddings.embed_texts(["symbol"])
    assert seen
    assert seen[0]["dimensions"] == embeddings.EMBEDDING_DIMENSIONS
    assert seen[0]["dimensions"] == 1536


def test_embed_texts_empty_without_key(monkeypatch):
    from app.services import embeddings
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "")
    assert embeddings.embed_texts(["a"]) == [[]]


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
