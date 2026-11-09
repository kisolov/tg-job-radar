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


def test_bot_is_optional_when_panel_has_password():
    env = {k: v for k, v in MIN_ENV.items() if k not in ("BOT_TOKEN", "OWNER_TELEGRAM_ID")}
    s = Settings(_env_file=None, **env, WEB_PASSWORD="secret-pass")
    assert s.BOT_TOKEN == "" and not s.bot_enabled


def test_without_bot_panel_password_is_required():
    import pytest
    from pydantic import ValidationError

    env = {k: v for k, v in MIN_ENV.items() if k not in ("BOT_TOKEN", "OWNER_TELEGRAM_ID")}
    with pytest.raises(ValidationError, match="WEB_PASSWORD"):
        Settings(_env_file=None, **env)
    with pytest.raises(ValidationError, match="WEB_PORT"):
        Settings(_env_file=None, **env, WEB_PASSWORD="x", WEB_PORT=0)


def test_bot_requires_owner_id():
    import pytest
    from pydantic import ValidationError

    env = {k: v for k, v in MIN_ENV.items() if k != "OWNER_TELEGRAM_ID"}
    with pytest.raises(ValidationError, match="OWNER_TELEGRAM_ID"):
        Settings(_env_file=None, **env)
