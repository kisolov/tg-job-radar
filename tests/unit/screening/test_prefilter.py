import pytest

from radar.screening.prefilter import PrefilterConfig, is_aggregator_only, is_russian, prefilter
from radar.shared.settings import DEFAULT_AGGREGATORS, DEFAULT_MARKERS, DEFAULT_STOPWORDS

cfg = PrefilterConfig(min_len=60, markers=DEFAULT_MARKERS, stopwords=DEFAULT_STOPWORDS,
                      aggregator_domains=DEFAULT_AGGREGATORS)

VACANCY = ("Ищем Python-разработчика (FastAPI, PostgreSQL) в команду, удалённо, частичная занятость. "
           "Задачи: API для CRM, интеграции. Пишите @hr_anna")


def test_media_without_text_dropped():
    assert prefilter(None, cfg) == "empty"
    assert prefilter("   \n", cfg) == "empty"


def test_caption_counts_as_text():
    caption = "📷 " + VACANCY  # подпись к картинке приходит как текст сообщения
    assert prefilter(caption, cfg) == "pass"


def test_hh_link_only_dropped():
    assert prefilter("Python dev 🔥 https://hh.ru/vacancy/123 #python #вакансия", cfg) == "aggregator_only"


def test_hh_link_with_short_russian_text_dropped():
    text = "Вакансия: Python-разработчик в финтех, удалёнка. Подробнее: https://hh.ru/vacancy/123456 #вакансия"
    assert prefilter(text, cfg) == "aggregator_only"


def test_hh_link_with_full_text_and_contact_passes():
    text = VACANCY + " Требования: опыт от 3 лет, asyncio, Docker. Условия: 250–300к, гибкий график. " \
           "Также на hh: https://hh.ru/vacancy/123"
    assert prefilter(text, cfg) == "pass"


def test_aggregator_subdomain_and_no_contact():
    text = ("Требуется backend-разработчик на Django в продуктовую компанию, полная удалёнка, "
            "оклад от 200 тысяч рублей, ДМС, оплачиваемое обучение, сильная команда, интересные задачи. "
            "Откликнуться: https://spb.hh.ru/vacancy/999")
    assert prefilter(text, cfg) == "aggregator_only"  # длинно, но контакта нет — только ссылка


def test_english_dropped():
    text = "We are hiring Python developer for a remote position, FastAPI and Postgres, DM @recruiter"
    assert prefilter(text, cfg) == "not_russian"


def test_resume_dropped():
    assert prefilter("#резюме Ищу работу Python backend разработчиком, опыт 4 года, FastAPI, Django. @me",
                     cfg) == "stopword"


def test_order_passes():
    assert prefilter("Нужен бот для записи клиентов в салон, бюджет 30к, пишите @ivan", cfg) == "pass"


def test_short_dropped():
    assert prefilter("Нужен бот, пишите @ivan", cfg) == "short"


def test_no_marker_dropped():
    assert prefilter("Сегодня отличная погода, гуляли с собакой по парку и обсуждали новые фильмы.",
                     cfg) == "no_marker"


@pytest.mark.parametrize("text", [
    "Оставьте отзыв о нашем сервисе доставки еды, мы ценим каждого клиента и его мнение!!!",
    "Полезный ресурс для изучения английского языка, много материалов и упражнений бесплатно",
])
def test_short_markers_match_whole_words_only(text):
    assert prefilter(text, cfg) == "no_marker"  # «тз» в «отзыв», «курс» в «ресурс» не считаются


def test_legit_vacancy_mentioning_experience_not_stopword():
    text = "Требуется Python-разработчик, удалённо, кандидатов без опыта коммерческой разработки не рассматриваем. @hr"
    assert prefilter(text, cfg) == "pass"


def test_yo_and_e_equivalent():
    text = "Ищем фронтенд-разработчика на Vue, работа удаленная, проектная занятость, пишите @lead_dev"
    assert prefilter(text, cfg) == "pass"


def test_is_russian_ignores_links_and_mentions():
    assert is_russian("Нужен разработчик https://example.com/very/long/english/path @some_english_handle")
    assert not is_russian("Hello world, привет")


def test_is_aggregator_only_requires_aggregator_link():
    assert not is_aggregator_only("Просто короткий текст", DEFAULT_AGGREGATORS)
