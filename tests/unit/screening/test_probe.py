from radar.screening.adapters.fake_classifier import FakeClassifier
from radar.screening.adapters.memory_repos import InMemoryRequirementsRepository
from radar.screening.usecases import ProbeModel, load_probe_samples


def test_samples_balanced():
    samples = load_probe_samples()
    assert len(samples) == 6 and sum(s["relevant"] for s in samples) == 3


async def test_probe_counts_correct_answers():
    # фейковая «модель» считает подходящим всё с Python/Vue: s1, s3 верно, s2 (бот без слова Python) — ошибка,
    # s4 (резюме с Python) — ошибка
    result = await ProbeModel(FakeClassifier(), InMemoryRequirementsRepository()).execute("fake-model")
    assert result.model == "fake-model" and result.total == 6
    assert result.correct == 4
    assert sorted(result.wrong) == ["s2", "s4"]
    assert result.usage.prompt_tokens == 60
