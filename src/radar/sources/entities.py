from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

AddedBy = Literal["seed", "discovery", "owner"]


class SourceKind(str, Enum):
    channel = "channel"
    group = "group"


class SourceStatus(str, Enum):
    candidate = "candidate"
    resolving = "resolving"
    active = "active"
    dead = "dead"
    rejected = "rejected"


@dataclass
class Source:
    id: int
    username: str | None
    invite_hash: str | None
    peer_id: int | None
    access_hash: int | None
    kind: SourceKind | None
    title: str | None
    status: SourceStatus
    assigned_account_id: UUID | None
    joined: bool
    last_message_id: int
    found_count: int
    relay_score: float
    added_by: AddedBy
    priority: int
    version: int = 0
    last_polled_at: datetime | None = None
    read_count: int = 0
    passed_count: int = 0
    activated_at: datetime | None = None
    hash_account_id: UUID | None = None  # access_hash выдан этому аккаунту; другим он не годится (C2)

    @property
    def needs_membership(self) -> bool:
        """Читать можно только изнутри: группа (live-апдейты) или любой чат по инвайту (приватный). Занимает слот R4."""
        return self.kind is SourceKind.group or self.invite_hash is not None

    @property
    def ref(self) -> str:
        return self.username or self.invite_hash or f"id{self.peer_id}"
