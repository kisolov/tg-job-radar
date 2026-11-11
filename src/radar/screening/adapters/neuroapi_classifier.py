"""NeuroAPI (OpenAI-совместимый /chat/completions): пакетная классификация в JSON."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from radar.findings.entities import Classification
from radar.screening.ports import LlmUnavailable, Usage

logger = logging.getLogger(__name__)

ATTEMPTS = 2  # исходный запрос + один повтор

INSTRUCTION = """\
Ты фильтруешь сообщения из Telegram-чатов для одного разработчика, который ищет работу и заказы.
Ниже его требования.

Подходит (relevant=true) только СПРОС: автор сообщения сам ищет исполнителя и готов ему платить —
работодатель нанимает (vacancy, «предложение о работе», «откликнуться») или заказчик ищет, кто сделает
задачу (project), — и задача подходит по требованиям. Обычная вакансия компании — это спрос.

Не подходит (relevant=false), даже если стек и тема совпадают:
- САМОРЕКЛАМА — автор продаёт свою работу или работу своей команды/компании: «сделаю», «делаем под ключ»,
  «разрабатываю ботов», «беру заказы», «готов выполнить», «Нужен сайт? Сделаем!», портфолио, прайс, отзывы
  клиентов. Вопрос «Нужен бот?» в собственной рекламе — это самореклама, а не спрос;
- резюме и поиск работы самим кандидатом: описание своего опыта, «рассматриваю предложения», ожидания по
  зарплате, «ищу работу», #cv, #резюме;
- подборки и дайджесты нескольких чужих вакансий со ссылками, без прямого контакта нанимающего;
- реклама, курсы, «заработок/удалёнка для новичков», выплаты за счета/карты/задания, крипто-схемы;
- обсуждения, вопросы, новости.

Проверка: кто кому платит? Платит автор — спрос. Автор хочет получить деньги за свою работу — самореклама.
Компания, студия или агентство, которые сами нанимают («в студию требуется», «ищем в команду», «нужен
разработчик на проект») — это спрос: платят они. Слова «студия», «агентство», «команда» сами по себе
не делают сообщение рекламой и не означают офис — решает, кто кого ищет.

Порядок решения: 1) спрос ли это (side); 2) если спрос — сверь с требованиями: подходит всё, что
перечислено в «Присылать», если оно не попадает под «Не присылать». Формат работы (офис/гибрид/удалёнка)
бери только из текста: если явно не сказано «офис» или «гибрид», не считай вакансию офисной.

Ответь строго JSON-объектом:
{"items": [{"id": "<id из входа>",
"who": "кто автор и кого он ищет — одной фразой",
"side": "demand" (автор ищет исполнителя и платит) | "self_promo" (автор продаёт свою работу/услуги, резюме) | "other",
"relevant": true|false (true только при side = "demand" и подходящих требованиях), "kind": "vacancy"|"project"|null,
"summary": "суть в 1–3 строки: что сделать, стек", "money": "деньги, если указаны, иначе null",
"format": "удалёнка/частичная занятость и т.п., если указано, иначе null",
"contact": "@username или t.me-ссылка автора из текста, иначе null",
"reason": "одна строка: почему подходит или нет"}]}
Верни ровно по одному элементу на КАЖДЫЙ входной id — и для подходящих, и для неподходящих
(у неподходящих relevant=false). Ничего не пропускай. Пиши по-русски.

Требования:
"""


def _parse_item(raw: Any) -> tuple[str, Classification] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("relevant"), bool):
        return None
    kind = raw.get("kind") if raw.get("kind") in ("vacancy", "project") else None

    def opt(key: str) -> str | None:
        v = raw.get(key)
        return v.strip() if isinstance(v, str) and v.strip() and v.strip().lower() != "null" else None

    return raw["id"], Classification(
        relevant=raw["relevant"], kind=kind, summary=opt("summary") or "", money=opt("money"),
        work_format=opt("format"), contact=opt("contact"), reason=opt("reason") or "",
    )


class NeuroApiClassifier:
    def __init__(self, base_url: str, key: str, model: str, max_chars: int = 1500, timeout: float = 60,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model, self._max_chars = model, max_chars
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport,
                                         headers={"Authorization": f"Bearer {key}"})

    async def classify(self, items: list[tuple[str, str]], requirements: str, *, model: str | None = None,
                       max_chars: int | None = None) -> tuple[dict[str, Classification], Usage]:
        limit = max_chars or self._max_chars
        payload = {
            "model": model or self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": INSTRUCTION + requirements},
                {"role": "user", "content": json.dumps(
                    [{"id": i, "text": t[:limit]} for i, t in items], ensure_ascii=False)},
            ],
        }
        wanted = {i for i, _ in items}
        spent = Usage()
        bad_output = False
        last_error = "unknown"
        for _ in range(ATTEMPTS):
            try:
                resp = await self._client.post(self._url, json=payload)
                resp.raise_for_status()
                body = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("NeuroAPI недоступен: %s", last_error)
                continue
            u = body.get("usage") or {}
            spent = spent + Usage(int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0))
            try:
                content = json.loads(body["choices"][0]["message"]["content"])
                raw_items = content["items"]
                if not isinstance(raw_items, list):
                    raise TypeError("items is not a list")
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = f"невалидный ответ: {type(exc).__name__}"
                bad_output = True
                logger.warning("NeuroAPI вернул невалидный JSON (%s)", last_error)
                continue
            results = {}
            for raw in raw_items:
                parsed = _parse_item(raw)
                if parsed and parsed[0] in wanted:
                    results[parsed[0]] = parsed[1]
            return results, spent
        raise LlmUnavailable(last_error, spent, bad_output)

    async def list_models(self) -> list[str]:
        resp = await self._client.get(self._url.removesuffix("/chat/completions") + "/models")
        resp.raise_for_status()
        return sorted(m["id"] for m in resp.json().get("data", []))

    async def aclose(self) -> None:
        await self._client.aclose()
