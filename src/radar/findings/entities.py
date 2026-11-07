from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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


class FindingStatus(str, Enum):
    pending = "pending"  # ждёт LLM
    rejected = "rejected"
    accepted = "accepted"  # подходит, ждёт доставки
    delivering = "delivering"  # claim: отправка идёт
    delivered = "delivered"
    failed = "failed"  # LLM так и не смог классифицировать (I4)


@dataclass
class Finding:
    """Кластер дублей одной вакансии/заказа (корень, R1). Текст и ссылка — снимок первой копии."""

    id: int
    fingerprint: str
    shingles: bytes
    text_snapshot: str
    link_snapshot: str
    sender_username: str | None
    sender_id: int | None
    sender_is_user: bool
    status: FindingStatus
    classification: Classification | None
    requirements_version: int | None
    claimed_at: datetime | None
    delivered_at: datetime | None
    bot_message_id: int | None
    created_at: datetime
    llm_attempts: int = 0  # неудачных попыток LLM; после MAX — failed (I4)


@dataclass(frozen=True)
class Copy:
    finding_id: int
    source_id: int
    message_id: int
    link: str
    source_title: str | None
