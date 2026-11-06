from collections.abc import Callable

from radar.findings.entities import Classification
from radar.screening.ports import LlmUnavailable, Usage


def keyword_rule(text: str) -> Classification:
    """Простая детерминированная «модель» для тестов: подходит, если упомянут Python или фронтенд."""
    low = text.lower()
    ok = "python" in low or "фронтенд" in low or "vue" in low
    kind = "project" if ("бот" in low or "заказ" in low) else "vacancy"
    return Classification(relevant=ok, kind=kind if ok else None, summary=text[:80], money=None,
                          work_format=None, contact=None, reason="ключевое слово" if ok else "не по профилю")


class FakeClassifier:
    def __init__(self, rule: Callable[[str], Classification] = keyword_rule) -> None:
        self.rule = rule
        self.calls: list[list[tuple[str, str]]] = []
        self.fail_next = 0

    async def classify(self, items, requirements, *, model=None, max_chars=None):
        self.calls.append(list(items))
        if self.fail_next:
            self.fail_next -= 1
            raise LlmUnavailable("fake outage")
        return {i: self.rule(t) for i, t in items}, Usage(10 * len(items), 5 * len(items))
