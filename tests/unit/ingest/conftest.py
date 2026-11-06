import random
from dataclasses import dataclass, field

import pytest

from radar.accounts.adapters.alerts import RecordingAlertSink
from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.accounts.service import AccountService
from radar.ingest.adapters.fake_gateway import FakeTelegram
from radar.ingest.adapters.memory_log import InMemoryMessageLog
from radar.ingest.pool import AccountWorker, PoolRunner
from radar.ingest.ports import IncomingMessage, Resolved
from radar.ingest.usecases import PollChannels, ReceiveMessage, RunJoinQueue, RunResolveQueue
from radar.shared.clock import FakeClock
from radar.sources.adapters.memory_repo import InMemorySourceRepository
from radar.sources.entities import SourceKind
from radar.sources.service import SourceService
from radar.sources.usecases import AssignWork, ReleaseAccountSources
from tests.factories import JOIN_POLICY, RESOLVE_POLICY, make_account

CAP = 500


class ListSink:
    def __init__(self) -> None:
        self.got: list[IncomingMessage] = []

    async def submit(self, msg: IncomingMessage) -> None:
        self.got.append(msg)


@dataclass
class World:
    clock: FakeClock
    tg: FakeTelegram = field(default_factory=FakeTelegram)
    accounts: InMemoryAccountRepository = field(default_factory=InMemoryAccountRepository)
    alerts: RecordingAlertSink = field(default_factory=RecordingAlertSink)
    sink: ListSink = field(default_factory=ListSink)
    log: InMemoryMessageLog = field(default_factory=InMemoryMessageLog)

    def __post_init__(self) -> None:
        self.sources = InMemorySourceRepository(self.accounts, membership_cap=CAP)
        self.account_service = AccountService(
            self.accounts, self.alerts, self.clock, random.Random(3), JOIN_POLICY, RESOLVE_POLICY)
        self.source_service = SourceService(self.sources, self.accounts)
        self.receive = ReceiveMessage(self.log, self.sink, self.sources, self.clock)
        self.poll = PollChannels(self.sources, self.receive, self.clock, interval_s=300)
        self.join_queue = RunJoinQueue(self.accounts, self.account_service, self.sources, self.clock, CAP)
        self.resolve_queue = RunResolveQueue(self.accounts, self.account_service, self.sources, self.clock)
        self.release = ReleaseAccountSources(self.source_service)
        self.assign = AssignWork(self.source_service)

    def worker(self, account) -> AccountWorker:
        return AccountWorker(
            account_id=account.id, gateway=self.tg.factory(account), accounts=self.accounts,
            account_service=self.account_service, join_queue=self.join_queue,
            resolve_queue=self.resolve_queue, poll=self.poll, receive=self.receive,
            release_sources=self.release, sources=self.sources, clock=self.clock,
        )

    def runner(self, sleep=None) -> PoolRunner:
        return PoolRunner(accounts=self.accounts, worker_factory=self.worker, account_service=self.account_service,
                          assign=self.assign, sleep=sleep)

    async def add_account(self, **kw):
        a = make_account(**kw)
        await self.accounts.add(a)
        return a

    async def add_source(self, ref: str, kind: SourceKind, peer: int, account=None, priority: int = 5):
        s = await self.sources.add_candidate(ref, "seed", priority)
        await self.sources.set_resolved(s.id, peer, 1, kind, ref)
        self.tg.chats[ref] = Resolved(peer, 1, kind, ref)
        if account is not None:
            assert await self.sources.assign(s.id, account.id)
        return await self.sources.get(s.id)


@pytest.fixture
def world(clock) -> World:
    return World(clock=clock)
