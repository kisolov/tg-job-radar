"""Сборка зависимостей. Один контейнер на процесс (бот, воркеры, CLI)."""
import random

from dependency_injector import containers, providers

from radar.accounts.adapters.alerts import LogAlertSink
from radar.accounts.adapters.device_profiles import DefaultDeviceProfileProvider
from radar.accounts.adapters.fernet_box import FernetSecretBox
from radar.accounts.adapters.session_probe import TelethonSessionProbe, interactive_login
from radar.accounts.adapters.sqlalchemy_repo import SqlAlchemyAccountRepository
from radar.accounts.entities import PacingPolicy
from radar.accounts.service import AccountService
from radar.accounts.usecases import DisableAccount, ImportAccount, ListAccounts, LoginAccount
from radar.shared.clock import SystemClock
from radar.shared.db import make_engine, make_session_factory
from radar.shared.settings import Settings


class Container(containers.DeclarativeContainer):
    settings = providers.Singleton(Settings)
    clock = providers.Singleton(SystemClock)
    rng = providers.Singleton(random.Random)

    engine = providers.Singleton(make_engine, url=settings.provided.DATABASE_URL)
    sessions = providers.Singleton(make_session_factory, engine=engine)

    join_policy = providers.Singleton(PacingPolicy.join_from_settings, settings)
    resolve_policy = providers.Singleton(PacingPolicy.resolve_from_settings, settings)

    # accounts
    secret_box = providers.Singleton(FernetSecretBox, key=settings.provided.USERBOT_STORE_KEY)
    devices = providers.Singleton(DefaultDeviceProfileProvider)
    session_probe = providers.Singleton(TelethonSessionProbe)
    alerts = providers.Singleton(LogAlertSink)
    account_repo = providers.Singleton(SqlAlchemyAccountRepository, sf=sessions)
    account_service = providers.Singleton(
        AccountService, accounts=account_repo, alerts=alerts, clock=clock, rng=rng,
        join_policy=join_policy, resolve_policy=resolve_policy,
    )
    import_account = providers.Factory(
        ImportAccount, accounts=account_repo, probe=session_probe, devices=devices, box=secret_box,
        clock=clock, default_device_profile=settings.provided.USERBOT_DEVICE_PROFILE,
        join_policy=join_policy, resolve_policy=resolve_policy, rng=rng,
    )
    login_account = providers.Factory(LoginAccount, importer=import_account, login_session=interactive_login)
    list_accounts = providers.Factory(ListAccounts, accounts=account_repo)
    disable_account = providers.Factory(DisableAccount, accounts=account_repo, service=account_service)
