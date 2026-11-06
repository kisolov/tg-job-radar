"""Контрактные тесты: каждая фикстура репозитория параметризована [sqlalchemy, memory].

Фейки, которым нужен общий «стол» (закрепление источника меняет счётчик членств аккаунта),
получают одно и то же in-memory хранилище аккаунтов — как две таблицы одной БД.
"""
import pytest

from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.accounts.adapters.sqlalchemy_repo import SqlAlchemyAccountRepository
from radar.sources.adapters.memory_repo import InMemorySourceRepository
from radar.sources.adapters.sqlalchemy_repo import SqlAlchemySourceRepository

CAP = 500


@pytest.fixture(params=["sqlalchemy", "memory"])
def backend(request):
    return request.param


@pytest.fixture
def account_repo(backend, request):
    if backend == "memory":
        return InMemoryAccountRepository()
    return SqlAlchemyAccountRepository(request.getfixturevalue("pg_sessionmaker"))


@pytest.fixture
def repos(backend, request):
    if backend == "memory":
        accounts = InMemoryAccountRepository()
        return accounts, InMemorySourceRepository(accounts, membership_cap=CAP)
    sf = request.getfixturevalue("pg_sessionmaker")
    return SqlAlchemyAccountRepository(sf), SqlAlchemySourceRepository(sf, membership_cap=CAP)


@pytest.fixture
def account_repo_shared(repos):
    return repos[0]


@pytest.fixture
def source_repo(repos):
    return repos[1]
