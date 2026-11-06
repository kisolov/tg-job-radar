import pytest

from radar.accounts.adapters.memory_repo import InMemoryAccountRepository
from radar.accounts.adapters.sqlalchemy_repo import SqlAlchemyAccountRepository


@pytest.fixture(params=["sqlalchemy", "memory"])
def backend(request):
    return request.param


@pytest.fixture
def account_repo(backend, request):
    if backend == "memory":
        return InMemoryAccountRepository()
    sf = request.getfixturevalue("pg_sessionmaker")
    return SqlAlchemyAccountRepository(sf)
