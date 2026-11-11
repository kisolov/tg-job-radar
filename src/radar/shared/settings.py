from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
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
    # предложение своих услуг и резюме — это не спрос (человек продаёт себя, а не ищет исполнителя)
    "#помогу", "#cv", "#услуги", "#ищузаказ", "#ищупроект", "#портфолио",
    "ищу заказ", "ищу проект", "беру заказ", "возьму заказ", "принимаю заказ", "возьму в работу",
    "мои услуги", "наши услуги", "предлагаю свои услуги", "предлагаю услуги",
    # подборки чужих вакансий и «заработок для новичков»
    "подборка вакансий", "для новичков",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    OWNER_TELEGRAM_ID: int = 0  # нужен, только если есть бот
    BOT_TOKEN: str = ""  # пусто — режим «только панель»
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
    RETIRE_AFTER_READ: int = 100  # прочитано столько без единой находки — источник снимается

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
    WEB_SECRET: str = ""  # пусто — выводится из USERBOT_STORE_KEY
    WEB_PASSWORD: str = ""  # вход в панель по паролю; без бота обязателен

    @property
    def bot_enabled(self) -> bool:
        return bool(self.BOT_TOKEN)

    @model_validator(mode="after")
    def _delivery_channel(self) -> "Settings":
        if self.BOT_TOKEN and not self.OWNER_TELEGRAM_ID:
            raise ValueError("С ботом нужен OWNER_TELEGRAM_ID — кому слать находки")
        if not self.BOT_TOKEN:
            if not self.WEB_PORT:
                raise ValueError("Без бота нужна веб-панель: WEB_PORT не может быть 0")
            if not self.WEB_PASSWORD:
                raise ValueError("Без бота вход в панель только по паролю: задайте WEB_PASSWORD")
        return self

    @field_validator("PREFILTER_MARKERS", "PREFILTER_STOPWORDS", "AGGREGATOR_DOMAINS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
