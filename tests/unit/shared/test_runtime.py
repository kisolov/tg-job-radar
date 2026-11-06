import pytest

from radar.shared.runtime import EDITABLE, InMemoryOverridesStore, RuntimeConfig, UnknownSetting
from radar.shared.settings import Settings
from tests.unit.shared.test_settings import MIN_ENV


def make():
    store = InMemoryOverridesStore()
    return RuntimeConfig(Settings(_env_file=None, **MIN_ENV), store), store


async def test_defaults_from_settings():
    rc, _ = make()
    await rc.load()
    assert rc.get("LLM_BATCH_SIZE") == 10 and rc.get("NEUROAPI_MODEL") == "m"
    assert not await rc.paused()


async def test_set_overrides_and_persists():
    rc, store = make()
    await rc.load()
    await rc.set("LLM_BATCH_SIZE", "3")
    await rc.set("NEUROAPI_MODEL", "gpt-4.1-mini")
    assert rc.get("LLM_BATCH_SIZE") == 3 and rc.get("NEUROAPI_MODEL") == "gpt-4.1-mini"
    rc2 = RuntimeConfig(rc.settings, store)
    await rc2.load()
    assert rc2.get("LLM_BATCH_SIZE") == 3


async def test_set_rejects_unknown_key_and_bad_value():
    rc, _ = make()
    await rc.load()
    with pytest.raises(UnknownSetting):
        await rc.set("BOT_TOKEN", "x")
    with pytest.raises(ValueError):
        await rc.set("LLM_BATCH_SIZE", "много")
    with pytest.raises(ValueError):
        await rc.set("LLM_BATCH_SIZE", "0")


async def test_pause_resume():
    rc, _ = make()
    await rc.load()
    await rc.set_paused(True)
    assert await rc.paused()
    await rc.set_paused(False)
    assert not await rc.paused()


def test_editable_keys_match_plan():
    assert set(EDITABLE) == {"LLM_BATCH_SIZE", "LLM_BATCH_WAIT_S", "LLM_MAX_CHARS", "LLM_DAILY_TOKEN_LIMIT",
                             "NEUROAPI_MODEL", "PREFILTER_MIN_LEN"}
