"""Сборка зависимостей. Один контейнер на процесс (бот, воркеры, CLI). Тесты подменяют провайдеры через override."""
import asyncio
import random

from aiogram import Bot
from dependency_injector import containers, providers

from radar.accounts.adapters.alerts import AlertLog, TeeAlertSink
from radar.accounts.adapters.device_profiles import DefaultDeviceProfileProvider
from radar.accounts.adapters.fernet_box import FernetSecretBox
from radar.accounts.adapters.session_probe import TelethonSessionProbe, interactive_login
from radar.accounts.adapters.sqlalchemy_repo import SqlAlchemyAccountRepository
from radar.accounts.adapters.tdata_reader import OpenteleTdataReader
from radar.accounts.entities import PacingPolicy
from radar.accounts.service import AccountService
from radar.accounts.usecases import DisableAccount, ImportAccount, ImportTdata, ListAccounts, LoginAccount
from radar.delivery.adapters.aiogram_notifier import AiogramNotifier
from radar.delivery.adapters.panel_notifier import PanelOnlyNotifier
from radar.delivery.bot import BotDeps
from radar.delivery.card import render_card, to_plain
from radar.delivery.usecases import AttachCopyEdit, SetPaused
from radar.findings.adapters.sqlalchemy_repo import SqlAlchemyFindingRepository
from radar.findings.events import InProcessEventBus
from radar.findings.service import FindingService
from radar.findings.usecases import ClusterMessage, DeliverAccepted, RedeliverStale
from radar.ingest.adapters.sqlalchemy_log import SqlAlchemyMessageLog
from radar.ingest.adapters.telethon_gateway import TelethonGatewayFactory
from radar.ingest.pool import PoolRunner, WorkerFactory
from radar.ingest.usecases import PollChannels, ReceiveMessage, RunJoinQueue, RunResolveQueue, SearchSources
from radar.panel.adapters.sqlalchemy_read_model import SqlAlchemyPanelReadModel
from radar.panel.auth import PanelAuth, secret_from
from radar.panel.usecases import GetFinding, GetOverview, ListFindings, ListPanelSources, RemoveSourceById
from radar.panel.web import PanelDeps
from radar.screening.adapters.neuroapi_classifier import NeuroApiClassifier
from radar.screening.adapters.sqlalchemy_repos import SqlAlchemyRequirementsRepository, SqlAlchemyUsageRepository
from radar.screening.prefilter import PrefilterConfig
from radar.screening.service import ScreeningService
from radar.screening.usecases import ClassifyPending, ProbeModel
from radar.shared.clock import SystemClock
from radar.shared.db import make_engine, make_session_factory
from radar.shared.runtime import RuntimeConfig, SqlAlchemyOverridesStore
from radar.shared.settings import Settings
from radar.sources.adapters.sqlalchemy_repo import SqlAlchemySourceRepository
from radar.sources.service import SourceService
from radar.sources.usecases import (
    AddSource,
    AssignWork,
    DiscoverFromMessage,
    ImportSeeds,
    ReleaseAccountSources,
    RemoveSource,
    RetireUseless,
)


def prefilter_provider(runtime: RuntimeConfig):
    """Конфиг предфильтра на каждый вызов: PREFILTER_MIN_LEN меняется через /set."""

    def get() -> PrefilterConfig:
        s = runtime.settings
        return PrefilterConfig(min_len=runtime.get("PREFILTER_MIN_LEN"), markers=list(s.PREFILTER_MARKERS),
                               stopwords=list(s.PREFILTER_STOPWORDS), aggregator_domains=list(s.AGGREGATOR_DOMAINS))

    return get


class DeliveryTrigger:
    """Будильник доставки: ClassifyPending будит DeliverAccepted сразу после принятых находок."""

    def __init__(self) -> None:
        self.event = asyncio.Event()

    async def __call__(self) -> None:
        self.event.set()


def make_bot(settings: Settings) -> Bot | None:
    return Bot(token=settings.BOT_TOKEN) if settings.bot_enabled else None


def make_notifier(bot: Bot | None, settings: Settings):
    """С ботом — карточки в личку владельцу; без бота — находки только в панели."""
    return AiogramNotifier(bot=bot, owner_id=settings.OWNER_TELEGRAM_ID) if bot else PanelOnlyNotifier()


def web_link_factory(settings: Settings, auth: PanelAuth):
    """Для /web: функция, выдающая одноразовую ссылку входа; None — панель выключена."""
    if not settings.WEB_PORT or not settings.bot_enabled:
        return None
    base = settings.WEB_BASE_URL.rstrip("/")
    return lambda: f"{base}/login?t={auth.issue_login()}"


class Container(containers.DeclarativeContainer):
    settings = providers.Singleton(Settings)
    clock = providers.Singleton(SystemClock)
    rng = providers.Singleton(random.Random)

    engine = providers.Singleton(make_engine, url=settings.provided.DATABASE_URL)
    sessions = providers.Singleton(make_session_factory, engine=engine)

    overrides_store = providers.Singleton(SqlAlchemyOverridesStore, sf=sessions)
    runtime = providers.Singleton(RuntimeConfig, settings=settings, store=overrides_store)

    join_policy = providers.Singleton(PacingPolicy.join_from_settings, settings)
    resolve_policy = providers.Singleton(PacingPolicy.resolve_from_settings, settings)

    # delivery transport — он же канал алертов (AlertSink = тот же бот)
    bot = providers.Singleton(make_bot, settings)
    notifier = providers.Singleton(make_notifier, bot, settings)
    alert_log = providers.Singleton(AlertLog, clock=clock)
    alerts = providers.Singleton(TeeAlertSink, log=alert_log,
                                 inner=providers.Callable(lambda b, n: n if b else None, bot, notifier))

    # accounts
    secret_box = providers.Singleton(FernetSecretBox, key=settings.provided.USERBOT_STORE_KEY)
    devices = providers.Singleton(DefaultDeviceProfileProvider)
    session_probe = providers.Singleton(TelethonSessionProbe)
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
    tdata_reader = providers.Singleton(OpenteleTdataReader)
    import_tdata = providers.Factory(ImportTdata, importer=import_account, reader=tdata_reader, probe=session_probe)
    login_account = providers.Factory(LoginAccount, importer=import_account, login_session=interactive_login)
    list_accounts = providers.Factory(ListAccounts, accounts=account_repo)
    disable_account = providers.Factory(DisableAccount, accounts=account_repo, service=account_service)

    # sources
    source_repo = providers.Singleton(
        SqlAlchemySourceRepository, sf=sessions, membership_cap=settings.provided.MEMBERSHIP_CAP
    )
    source_service = providers.Singleton(SourceService, sources=source_repo, accounts=account_repo,
                                         aggregator_domains=settings.provided.AGGREGATOR_DOMAINS)
    add_source = providers.Factory(AddSource, service=source_service)
    remove_source = providers.Factory(RemoveSource, service=source_service)
    import_seeds = providers.Factory(ImportSeeds, service=source_service)
    assign_work = providers.Singleton(AssignWork, service=source_service, clock=clock)
    discover = providers.Singleton(DiscoverFromMessage, service=source_service)
    retire_useless = providers.Singleton(RetireUseless, service=source_service,
                                         min_read=settings.provided.RETIRE_AFTER_READ)
    release_account_sources = providers.Singleton(ReleaseAccountSources, service=source_service)

    # screening
    classifier = providers.Singleton(
        NeuroApiClassifier, base_url=settings.provided.NEUROAPI_BASE_URL, key=settings.provided.NEUROAPI_KEY,
        model=settings.provided.NEUROAPI_MODEL, max_chars=settings.provided.LLM_MAX_CHARS,
    )
    usage_repo = providers.Singleton(SqlAlchemyUsageRepository, sf=sessions)
    requirements_repo = providers.Singleton(SqlAlchemyRequirementsRepository, sf=sessions)
    screening_service = providers.Singleton(ScreeningService, usage=usage_repo, alerts=alerts, clock=clock)
    probe_model = providers.Factory(ProbeModel, classifier=classifier, requirements=requirements_repo)

    # findings
    finding_repo = providers.Singleton(SqlAlchemyFindingRepository, sf=sessions)
    bus = providers.Singleton(InProcessEventBus)
    finding_service = providers.Singleton(
        FindingService, repo=finding_repo, clock=clock, window_days=settings.provided.DEDUP_WINDOW_DAYS,
        threshold=settings.provided.DEDUP_JACCARD,
    )
    cluster_message = providers.Singleton(
        ClusterMessage, service=finding_service, prefilter_config=providers.Callable(prefilter_provider, runtime),
        bus=bus, stats=usage_repo, clock=clock, discover=discover, sources=source_repo,
    )
    delivery_trigger = providers.Singleton(DeliveryTrigger)
    deliver_accepted = providers.Singleton(
        DeliverAccepted, repo=finding_repo, notifier=notifier, render=providers.Object(render_card),
        paused=runtime.provided.paused, stats=usage_repo, clock=clock, plain=providers.Object(to_plain),
        alerts=alerts,
    )
    redeliver_stale = providers.Singleton(
        RedeliverStale, repo=finding_repo, clock=clock, stale_s=settings.provided.CLAIM_STALE_S)
    attach_copy_edit = providers.Singleton(
        AttachCopyEdit, findings=finding_repo, notifier=notifier, render=providers.Object(render_card))
    classify_pending = providers.Singleton(
        ClassifyPending, findings=finding_repo, classifier=classifier, screening=screening_service,
        requirements=requirements_repo, usage=usage_repo, sources=source_repo, runtime=runtime, clock=clock,
        on_accepted=delivery_trigger,
    )

    # ingest
    gateway_factory = providers.Singleton(TelethonGatewayFactory, box=secret_box, devices=devices)
    message_log = providers.Singleton(SqlAlchemyMessageLog, sf=sessions)
    receive = providers.Singleton(ReceiveMessage, log=message_log, sink=cluster_message, sources=source_repo,
                                  clock=clock)
    poll = providers.Singleton(PollChannels, sources=source_repo, receive=receive, clock=clock,
                               interval_s=settings.provided.CHANNEL_POLL_INTERVAL_S)
    join_queue = providers.Singleton(RunJoinQueue, accounts=account_repo, account_service=account_service,
                                     sources=source_repo, clock=clock,
                                     membership_cap=settings.provided.MEMBERSHIP_CAP)
    resolve_queue = providers.Singleton(RunResolveQueue, accounts=account_repo, account_service=account_service,
                                        sources=source_repo, clock=clock, source_service=source_service)
    worker_factory = providers.Singleton(
        WorkerFactory, gateway_factory=gateway_factory, accounts=account_repo, account_service=account_service,
        join_queue=join_queue, resolve_queue=resolve_queue, poll=poll, receive=receive,
        release_sources=release_account_sources, sources=source_repo, clock=clock,
    )
    pool_runner = providers.Singleton(PoolRunner, accounts=account_repo, worker_factory=worker_factory,
                                      account_service=account_service, assign=assign_work)
    search_sources = providers.Factory(
        SearchSources, accounts=account_repo, account_service=account_service, sources=source_repo,
        gateway_factory=gateway_factory, clock=clock,
    )

    # panel
    panel_auth = providers.Singleton(
        PanelAuth, secret=providers.Callable(secret_from, settings.provided.WEB_SECRET,
                                            settings.provided.USERBOT_STORE_KEY),
        clock=clock,
    )
    panel_read_model = providers.Singleton(SqlAlchemyPanelReadModel, sf=sessions)
    panel_deps = providers.Singleton(
        PanelDeps, auth=panel_auth,
        overview=providers.Factory(GetOverview, read_model=panel_read_model, accounts=account_repo, usage=usage_repo,
                                   runtime=runtime, clock=clock, alert_log=alert_log,
                                   bot_enabled=settings.provided.bot_enabled),
        findings=providers.Factory(ListFindings, read_model=panel_read_model, clock=clock),
        finding=providers.Factory(GetFinding, read_model=panel_read_model),
        sources=providers.Factory(ListPanelSources, read_model=panel_read_model, clock=clock),
        add_source=add_source,
        remove_source=providers.Factory(RemoveSourceById, sources=source_repo, service=source_service),
        set_paused=providers.Factory(SetPaused, runtime=runtime),
        secure_cookie=providers.Callable(lambda url: url.startswith("https://"), settings.provided.WEB_BASE_URL),
        password=settings.provided.WEB_PASSWORD, bot_login=settings.provided.bot_enabled,
    )

    bot_deps = providers.Singleton(
        BotDeps, accounts=account_repo, sources=source_repo, source_service=source_service,
        requirements=requirements_repo, usage=usage_repo, runtime=runtime, clock=clock,
        web_link=providers.Callable(web_link_factory, settings, panel_auth),
    )
