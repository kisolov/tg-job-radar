from radar.shared.settings import Settings

MIN_ENV = dict(
    DATABASE_URL="postgresql+asyncpg://x", OWNER_TELEGRAM_ID=1, BOT_TOKEN="t",
    USERBOT_STORE_KEY="k", NEUROAPI_BASE_URL="u", NEUROAPI_KEY="k", NEUROAPI_MODEL="m",
)


def test_defaults():
    s = Settings(_env_file=None, **MIN_ENV)
    assert (s.JOIN_DAILY_MIN, s.JOIN_DAILY_MAX) == (25, 30)
    assert (s.JOIN_INTERVAL_MIN_S, s.JOIN_INTERVAL_MAX_S) == (300, 600)
    assert s.LLM_BATCH_WAIT_S == 60 and s.LLM_BATCH_SIZE == 10
    assert "hh.ru" in s.AGGREGATOR_DOMAINS
    assert s.MEMBERSHIP_CAP == 500 and s.THROTTLE_MAX_FACTOR == 8.0


def test_list_from_env_comma_separated(monkeypatch):
    monkeypatch.setenv("AGGREGATOR_DOMAINS", "a.ru, b.ru")
    s = Settings(_env_file=None, **MIN_ENV)
    assert s.AGGREGATOR_DOMAINS == ["a.ru", "b.ru"]
