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
from radar.ingest.adapters.sqlalchemy_log import SqlAlchemyMessageLog
from radar.ingest.adapters.telethon_gateway import TelethonGatewayFactory
from radar.ingest.usecases import SearchSources
from radar.screening.adapters.neuroapi_classifier import NeuroApiClassifier
from radar.screening.adapters.sqlalchemy_repos import SqlAlchemyRequirementsRepository, SqlAlchemyUsageRepository
from radar.screening.service import ScreeningService
from radar.screening.usecases import ProbeModel
from radar.shared.clock import SystemClock
from radar.shared.db import make_engine, make_session_factory
from radar.shared.settings import Settings
from radar.sources.adapters.sqlalchemy_repo import SqlAlchemySourceRepository
from radar.sources.service import SourceService
from radar.sources.usecases import AddSource, AssignWork, ImportSeeds, ReleaseAccountSources, RemoveSource


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

    # sources
    source_repo = providers.Singleton(
        SqlAlchemySourceRepository, sf=sessions, membership_cap=settings.provided.MEMBERSHIP_CAP
    )
    source_service = providers.Singleton(SourceService, sources=source_repo, accounts=account_repo)
    add_source = providers.Factory(AddSource, service=source_service)
    remove_source = providers.Factory(RemoveSource, service=source_service)
    import_seeds = providers.Factory(ImportSeeds, service=source_service)
    assign_work = providers.Factory(AssignWork, service=source_service)
    release_account_sources = providers.Factory(ReleaseAccountSources, service=source_service)

    # ingest
    gateway_factory = providers.Singleton(TelethonGatewayFactory, box=secret_box, devices=devices)
    message_log = providers.Singleton(SqlAlchemyMessageLog, sf=sessions)
    search_sources = providers.Factory(
        SearchSources, accounts=account_repo, account_service=account_service, sources=source_repo,
        gateway_factory=gateway_factory, clock=clock,
    )

    # screening
    classifier = providers.Singleton(
        NeuroApiClassifier, base_url=settings.provided.NEUROAPI_BASE_URL, key=settings.provided.NEUROAPI_KEY,
        model=settings.provided.NEUROAPI_MODEL, max_chars=settings.provided.LLM_MAX_CHARS,
    )
    usage_repo = providers.Singleton(SqlAlchemyUsageRepository, sf=sessions)
    requirements_repo = providers.Singleton(SqlAlchemyRequirementsRepository, sf=sessions)
    screening_service = providers.Singleton(ScreeningService, usage=usage_repo, alerts=alerts, clock=clock)
    probe_model = providers.Factory(ProbeModel, classifier=classifier, requirements=requirements_repo)
