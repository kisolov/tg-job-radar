import json

import httpx
import pytest

from radar.screening.adapters.neuroapi_classifier import NeuroApiClassifier
from radar.screening.ports import LlmUnavailable

REQ = "Присылать: Python-бэкенд, удалёнка."


def ok_body(items, prompt=120, completion=40):
    return {"choices": [{"message": {"content": json.dumps({"items": items}, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


ITEM = {"id": "a", "relevant": True, "kind": "vacancy", "summary": "Python dev, FastAPI", "money": "250к",
        "format": "удалёнка", "contact": "@hr_anna", "reason": "Python-бэкенд, удалёнка"}


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, httpx.Response):
            return r
        return httpx.Response(200, json=r)


def make(rec: Recorder, max_chars=1500) -> NeuroApiClassifier:
    return NeuroApiClassifier("https://neuroapi.test/v1", "key", "gpt-4o-mini", max_chars=max_chars,
                              transport=httpx.MockTransport(rec))


async def test_parses_items():
    rec = Recorder(ok_body([ITEM, {**ITEM, "id": "b", "relevant": False, "kind": None, "money": None}]))
    results, usage = await make(rec).classify([("a", "текст а"), ("b", "текст б")], REQ)
    assert set(results) == {"a", "b"}
    a = results["a"]
    assert (a.relevant, a.kind, a.summary, a.money, a.work_format, a.contact) == (
        True, "vacancy", "Python dev, FastAPI", "250к", "удалёнка", "@hr_anna")
    assert results["b"].relevant is False and results["b"].kind is None
    assert (usage.prompt_tokens, usage.completion_tokens) == (120, 40)
    sent = rec.requests[0]
    assert sent["model"] == "gpt-4o-mini" and sent["temperature"] == 0
    assert sent["response_format"] == {"type": "json_object"}
    assert REQ in sent["messages"][0]["content"]
    assert json.loads(sent["messages"][1]["content"]) == [{"id": "a", "text": "текст а"}, {"id": "b", "text": "текст б"}]


async def test_malformed_response_keeps_pending():
    garbage = {"choices": [{"message": {"content": "не json"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    rec = Recorder(garbage, {"choices": [{"message": {"content": '{"nope": 1}'}}]})
    with pytest.raises(LlmUnavailable):
        await make(rec).classify([("a", "x")], REQ)
    assert len(rec.requests) == 2  # ровно один повтор


async def test_retry_succeeds_after_garbage():
    garbage = {"choices": [{"message": {"content": "не json"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
    rec = Recorder(garbage, ok_body([ITEM]))
    results, usage = await make(rec).classify([("a", "x")], REQ)
    assert set(results) == {"a"} and usage.prompt_tokens == 130  # расход обеих попыток


async def test_http_errors_and_timeout_unavailable():
    rec = Recorder(httpx.Response(502), httpx.ReadTimeout("slow"))
    with pytest.raises(LlmUnavailable):
        await make(rec).classify([("a", "x")], REQ)


async def test_missing_ids_stay_pending():
    rec = Recorder(ok_body([ITEM, {**ITEM, "id": "zzz"}, {"id": "b", "relevant": "yes?"}]))
    results, _ = await make(rec).classify([("a", "x"), ("b", "y")], REQ)
    assert set(results) == {"a"}  # чужой id и невалидный элемент отброшены, b остаётся pending


async def test_text_truncated():
    rec = Recorder(ok_body([ITEM]))
    await make(rec, max_chars=100).classify([("a", "я" * 5000)], REQ)
    sent = json.loads(rec.requests[0]["messages"][1]["content"])
    assert len(sent[0]["text"]) <= 100


async def test_model_override_per_call():
    rec = Recorder(ok_body([ITEM]))
    await make(rec).classify([("a", "x")], REQ, model="gpt-4.1-mini")
    assert rec.requests[0]["model"] == "gpt-4.1-mini"
