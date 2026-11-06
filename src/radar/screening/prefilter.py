"""Дешёвый предфильтр без LLM. Чистые функции: текст + конфиг → вердикт."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from typing import Literal
from urllib.parse import urlparse

PrefilterVerdict = Literal["pass", "empty", "short", "not_russian", "no_marker", "stopword", "aggregator_only"]

_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w.-]+\.(?:ru|com|app|io|me|org|net)/\S*", re.IGNORECASE)
_MENTION = re.compile(r"@\w{3,}")
_TG_LINK = re.compile(r"(?:https?://)?(?:t|telegram)\.me/\S+", re.IGNORECASE)
_HASHTAG = re.compile(r"#\w+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_CYR = re.compile(r"[а-яё]", re.IGNORECASE)
_LAT = re.compile(r"[a-z]", re.IGNORECASE)
AGGREGATOR_REMAINDER_MIN = 200


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def _word_pattern(words: list[str]) -> re.Pattern[str]:
    """Слово совпадает с начала слова; короткие (≤3 символа: «тз», «зп») — только целиком."""
    parts = []
    for w in words:
        w = _norm(w.strip())
        if not w:
            continue
        tail = r"(?!\w)" if len(w) <= 3 else ""
        parts.append(rf"(?<!\w){re.escape(w)}{tail}")
    return re.compile("|".join(parts) or r"(?!x)x")


@dataclass(frozen=True)
class PrefilterConfig:
    min_len: int
    markers: list[str]
    stopwords: list[str]
    aggregator_domains: list[str]

    @classmethod
    def from_settings(cls, s) -> PrefilterConfig:
        return cls(min_len=s.PREFILTER_MIN_LEN, markers=list(s.PREFILTER_MARKERS),
                   stopwords=list(s.PREFILTER_STOPWORDS), aggregator_domains=list(s.AGGREGATOR_DOMAINS))

    @cached_property
    def _markers_re(self) -> re.Pattern[str]:
        return _word_pattern(self.markers)

    @cached_property
    def _stop_re(self) -> re.Pattern[str]:
        return _word_pattern(self.stopwords)


def is_russian(text: str) -> bool:
    """Доля кириллицы среди букв ≥ 0.5; ссылки и @упоминания не считаются."""
    clean = _MENTION.sub(" ", _URL.sub(" ", text))
    cyr, lat = len(_CYR.findall(clean)), len(_LAT.findall(clean))
    return cyr > 0 and cyr / (cyr + lat) >= 0.5


def _host_matches(url: str, domains: list[str]) -> bool:
    raw = url if "://" in url else "http://" + url
    host = (urlparse(raw).hostname or "").lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in domains)


def is_aggregator_only(text: str, domains: list[str]) -> bool:
    """Есть ссылка на агрегатор, и без неё сообщение пустое: остаток (без ссылок, хэштегов, эмодзи)
    короче 200 символов или в нём нет контакта (@username / t.me-ссылки)."""
    if not any(_host_matches(m.group(0), domains) for m in _URL.finditer(text)):
        return False
    remainder = _EMOJI.sub("", _HASHTAG.sub("", _URL.sub("", text)))
    remainder = re.sub(r"\s+", " ", remainder).strip()
    has_contact = bool(_MENTION.search(text) or _TG_LINK.search(text))
    return len(remainder) < AGGREGATOR_REMAINDER_MIN or not has_contact


def prefilter(text: str | None, cfg: PrefilterConfig) -> PrefilterVerdict:
    if not text or not text.strip():
        return "empty"
    if is_aggregator_only(text, cfg.aggregator_domains):
        return "aggregator_only"
    if len(text.strip()) < cfg.min_len:
        return "short"
    if not is_russian(text):
        return "not_russian"
    norm = _norm(text)
    if cfg._stop_re.search(norm):
        return "stopword"
    if not cfg._markers_re.search(norm):
        return "no_marker"
    return "pass"
