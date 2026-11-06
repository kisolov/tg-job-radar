import pytest

from radar.shared.runtime import InMemoryOverridesStore, SqlAlchemyOverridesStore


@pytest.fixture
def store(backend, request):
    if backend == "memory":
        return InMemoryOverridesStore()
    return SqlAlchemyOverridesStore(request.getfixturevalue("pg_sessionmaker"))


async def test_set_overwrite_delete(store):
    assert await store.all() == {}
    await store.set("LLM_BATCH_SIZE", "5")
    await store.set("LLM_BATCH_SIZE", "7")
    await store.set("DELIVERY_PAUSED", "1")
    assert await store.all() == {"LLM_BATCH_SIZE": "7", "DELIVERY_PAUSED": "1"}
    await store.delete("LLM_BATCH_SIZE")
    await store.delete("NOPE")
    assert await store.all() == {"DELIVERY_PAUSED": "1"}
