"""Входы в отбор: проба модели (выбор модели NeuroAPI), пакетная классификация (Task 10)."""
import json
from dataclasses import dataclass, field
from importlib import resources

from radar.screening.ports import LlmClassifier, RequirementsRepository, Usage


def load_probe_samples() -> list[dict]:
    return json.loads(resources.files("radar.screening").joinpath("probe_samples.json").read_text("utf-8"))


@dataclass
class ProbeResult:
    model: str
    correct: int
    total: int
    wrong: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class ProbeModel:
    """6 эталонных сообщений (3 подходят, 3 нет) одним пакетом — как в бою."""

    def __init__(self, classifier: LlmClassifier, requirements: RequirementsRepository) -> None:
        self._classifier, self._requirements = classifier, requirements

    async def execute(self, model: str) -> ProbeResult:
        samples = load_probe_samples()
        _, req = await self._requirements.current()
        results, usage = await self._classifier.classify([(s["id"], s["text"]) for s in samples], req, model=model)
        wrong = [s["id"] for s in samples if s["id"] not in results or results[s["id"]].relevant != s["relevant"]]
        return ProbeResult(model, len(samples) - len(wrong), len(samples), wrong, usage)
