from radar.screening.adapters.fake_classifier import FakeClassifier
from radar.screening.adapters.memory_repos import InMemoryRequirementsRepository
from radar.screening.usecases import ProbeModel, load_probe_samples


def test_samples_balanced():
    samples = load_probe_samples()
    assert len(samples) == 12 and sum(s["relevant"] for s in samples) == 5


async def test_probe_counts_correct_answers():
    # фейковая «модель» считает подходящим всё с Python/Vue: s1, s3 верно, s2 (бот без слова Python) — ошибка,
    # s4 (резюме с Python) — ошибка; s7–s9 (предложение услуг и резюме со словами Python/Vue) — тоже ошибки:
    # ключевые слова не отличают спрос от предложения, это и проверяет проба настоящей модели
    result = await ProbeModel(FakeClassifier(), InMemoryRequirementsRepository()).execute("fake-model")
    assert result.model == "fake-model" and result.total == 12
    assert result.correct == 7
    assert sorted(result.wrong) == ["s2", "s4", "s7", "s8", "s9"]
    assert result.usage.prompt_tokens == 120


async def test_cli_probe_continues_after_a_failing_model(capsys):
    """Ошибка одной модели (500 у провайдера) не обрывает пробу остальных."""
    from dependency_injector import providers

    from radar.bootstrap.cli import run
    from radar.bootstrap.di import Container
    from radar.screening.adapters.fake_classifier import FakeClassifier
    from radar.screening.adapters.memory_repos import InMemoryRequirementsRepository
    from radar.screening.ports import LlmUnavailable
    from radar.shared.settings import Settings
    from tests.unit.shared.test_settings import MIN_ENV

    class FlakyByModel(FakeClassifier):
        async def classify(self, items, requirements, *, model=None, max_chars=None):
            if model == "broken":
                raise LlmUnavailable("HTTPStatusError: 500")
            return await super().classify(items, requirements, model=model, max_chars=max_chars)

    c = Container()
    c.settings.override(providers.Object(Settings(_env_file=None, **{**MIN_ENV, "BOT_TOKEN": "42:TESTTOKEN"})))
    c.classifier.override(providers.Object(FlakyByModel()))
    c.requirements_repo.override(providers.Object(InMemoryRequirementsRepository()))
    code = await run(["llm", "probe", "broken", "good"], c)
    out = capsys.readouterr().out
    assert "broken: ошибка" in out and "good:" in out and code in (0, 1)
