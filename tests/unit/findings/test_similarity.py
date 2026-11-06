from radar.findings.similarity import fingerprint, jaccard, normalize, pack, shingles, unpack

BASE = ("Ищем Python-разработчика в команду маркетплейса. Стек: FastAPI, PostgreSQL, Redis, Celery. "
        "Удалённо, полная занятость, вилка 250–300 тысяч. Задачи: развитие API каталога и заказов, "
        "интеграции с платёжными системами. Пишите @hr_anna")


def sim(a: str, b: str) -> float:
    return jaccard(shingles(normalize(a)), shingles(normalize(b)))


def test_normalize_strips_noise():
    assert normalize("🔥 Ищем #python Dev!!! https://t.me/x/1 @hr_anna  ЁЖ") == "ищем dev еж"


def test_fingerprint_stable_for_noise_only_diff():
    a = normalize("Нужен бот 🔥 #заказ https://t.me/a/1")
    b = normalize("Нужен   бот! #бот t.me/b/2")
    assert fingerprint(a) == fingerprint(b)


def test_shingles_stable_across_processes():
    # crc32, не встроенный hash(): значения хранятся в БД
    assert shingles("абвгде") == {shingles("абвгд").pop(), *shingles("бвгде")}
    assert min(shingles("python")) >= 0


def test_reposts_cluster_together():
    repost = "🚀🚀 " + BASE.replace("Пишите @hr_anna", "Контакт: @recruiter_ivan") + " #вакансия #python #remote " \
             "Больше вакансий: t.me/it_jobs_channel"
    assert sim(BASE, repost) >= 0.6


def test_different_vacancies_apart():
    other = ("Ищем Python-разработчика в команду финтех-стартапа. Стек: Django, DRF, MySQL, RabbitMQ. "
             "Офис в Казани, гибрид, вилка 180–220 тысяч. Задачи: биллинг, отчёты для бухгалтерии, "
             "поддержка легаси-модулей. Пишите @cto_petr")
    assert sim(BASE, other) < 0.6


def test_pack_roundtrip():
    sh = shingles(normalize(BASE))
    assert unpack(pack(sh)) == sh
