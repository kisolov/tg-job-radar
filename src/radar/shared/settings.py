from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]

DEFAULT_AGGREGATORS = [
    "hh.ru", "career.habr.com", "getmatch.ru", "superjob.ru", "rabota.ru",
    "zarplata.ru", "trudvsem.ru", "geekjob.ru", "careerspace.app",
]
DEFAULT_MARKERS = [
    "ищем", "ищу разработчик", "ищу программист", "нужен", "нужна", "нужны", "требуется",
    "вакансия", "ваканси", "заказ", "проект", "тз", "техзадан", "бюджет", "оплата", "ставка",
    "зп", "з/п", "оклад", "фриланс", "подряд", "сделать бота", "разработать", "доработать",
    "удалён", "remote",
]
DEFAULT_STOPWORDS = [
    "ищу работу", "#резюме", "#ищуработу", "резюме кандидата", "курс", "обучение с нуля",
    "вебинар", "работа без опыта", "без опыта и вложений", "пассивный доход", "арбитраж", "p2p", "заработок от", "казино",
    "ставки на спорт",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    OWNER_TELEGRAM_ID: int
    BOT_TOKEN: str
    USERBOT_STORE_KEY: str
    TELEGRAM_API_ID: int | None = None
    TELEGRAM_API_HASH: str | None = None
    USERBOT_DEVICE_PROFILE: str = "default"

    JOIN_DAILY_MIN: int = 25
    JOIN_DAILY_MAX: int = 30
    JOIN_INTERVAL_MIN_S: int = 300
    JOIN_INTERVAL_MAX_S: int = 600
    RESOLVE_INTERVAL_S: int = 60
    RESOLVE_DAILY_MIN: int = 150  # ResolveUsername у Telegram лимитирован (~200 в сутки)
    RESOLVE_DAILY_MAX: int = 180
    THROTTLE_FACTOR: float = 1.5
    THROTTLE_MAX_FACTOR: float = 8.0
    THROTTLE_LIMIT_STEP: int = 5
    THROTTLE_LIMIT_FLOOR: int = 5
    THROTTLE_RECOVERY_DAYS: int = 3
    MEMBERSHIP_CAP: int = 500
    CHANNEL_POLL_INTERVAL_S: int = 300

    NEUROAPI_BASE_URL: str
    NEUROAPI_KEY: str
    NEUROAPI_MODEL: str
    LLM_BATCH_SIZE: int = 10
    LLM_BATCH_WAIT_S: int = 60
    LLM_MAX_CHARS: int = 1500
    LLM_DAILY_TOKEN_LIMIT: int = 2_000_000
    LLM_PRICE_PER_1K_PROMPT: float = 0.0
    LLM_PRICE_PER_1K_COMPLETION: float = 0.0

    PREFILTER_MIN_LEN: int = 60
    PREFILTER_MARKERS: CsvList = DEFAULT_MARKERS
    PREFILTER_STOPWORDS: CsvList = DEFAULT_STOPWORDS
    AGGREGATOR_DOMAINS: CsvList = DEFAULT_AGGREGATORS

    DEDUP_WINDOW_DAYS: int = 7
    DEDUP_JACCARD: float = 0.6
    CLAIM_STALE_S: int = 600
    MESSAGES_RETENTION_DAYS: int = 7

    WEB_HOST: str = "127.0.0.1"
    WEB_PORT: int = 8080  # 0 — панель выключена
    WEB_BASE_URL: str = "http://localhost:8080"  # адрес, который бот вставляет в ссылку /web
    WEB_SECRET: str = ""  # пусто — выводится из BOT_TOKEN

    @field_validator("PREFILTER_MARKERS", "PREFILTER_STOPWORDS", "AGGREGATOR_DOMAINS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
