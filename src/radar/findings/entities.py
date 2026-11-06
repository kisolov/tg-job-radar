from dataclasses import dataclass
from typing import Literal

FindingKind = Literal["vacancy", "project"]


@dataclass(frozen=True)
class Classification:
    relevant: bool
    kind: FindingKind | None
    summary: str
    money: str | None
    work_format: str | None
    contact: str | None
    reason: str
