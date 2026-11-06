# Стартовый список источников

`sources.txt` — 180 источников (собрано 2026-11-06): 112 каналов и групп вакансий, фриланса и заказов
(`!`, priority 10) и 68 тех-чатов по стеку: Python, веб, фронтенд, боты (priority 5).
Импорт: `radar sources import seeds/sources.txt`.

## Откуда

| Источник | Что взято |
|---|---|
| [NewHR/telegram](https://github.com/NewHR/telegram) | раздел «Вакансии и работа» целиком; чаты, фреймворки — строки по стеку |
| [goq/telegram-list](https://github.com/goq/telegram-list) | разделы «Вакансии», «Вакансии и работа» целиком; языки, фреймворки, сообщества, разработка ботов, региональные IT-сообщества — строки по стеку |
| [vc.ru: 300+ каналов с вакансиями](https://vc.ru/hr/2295219-300-telegram-kanalov-s-vakansiyami) | ссылки, рядом с которыми в тексте IT/веб/Python/фронтенд |
| [vc.ru: удалёнка для Python-разработчика](https://vc.ru/hr___/2878426-udalyonnaya-rabota-dlya-python-razrabotchika), [vc.ru: заказы для фриланса](https://vc.ru/353605-kak-iskat-zakazy-dlya-frilansa-v-telegram), [vc.ru: онлайн-работа](https://vc.ru/hr/2219346-onlajn-rabota-v-telegram) | то же |
| [Нетология: 87 каналов для программистов](https://netology.ru/blog/prg-tg), [Нетология: поиск работы](https://netology.ru/blog/05-2019-telegram-poisk-raboty) | то же |
| [teletype: фриланс в Telegram](https://teletype.in/@winter_day/frilans-kanal-v-telegram), [Sostav: каналы для фрилансера](https://www.sostav.ru/blogs/271909/57030), [lpmotor: фриланс в Telegram](https://lpmotor.ru/articles/Frilans-v-Telegram-TOP-boty-i-kanaly-dlya-poiska-zakazov) | то же |
| [Skillbox: 23 канала](https://skillbox.ru/media/growth/23_telegram_kanala_dlya_tekh_kto_ishchet_rabotu/), [Timeweb: топ-10](https://timeweb.com/ru/community/articles/top-10-telegram-kanalov-s-vakansiyami-dlya-it-specialistov), [Timeweb: удалёнка](https://timeweb.com/ru/community/articles/gde-iskat-udalyonnuyu-rabotu-v-telegram-proverennye-kanaly-s-vakansiyami), [Tproger: топ-10](https://tproger.ru/articles/top-10-telegram-kanalov-dlya-poiska-raboty-v-it), [Хабр](https://habr.com/ru/articles/877182/), [dev.ua](https://dev.ua/ru/news/telegram-channels-it) | то же |

tgstat (403) и telemetr (каталог рендерится скриптом) автоматом не читаются.

## Что отброшено и почему

Около 120 найденных источников убраны (`tools/finalize.py`, список `EXCLUDE`, плюс фильтр имён в `tools/build.py`):
стек, который не нужен без Python/фронтенда (PHP/Laravel/MODX/Yii, Java/JVM, мобильная разработка, 1С, SAP, Ruby,
Haskell, QA, DevOps, данные/ML), стажировки и junior, релокация (офис за рубежом), тексты/дизайн/таргет/моушн,
железо и ОС, новостные каналы без вакансий. Ретрансляторов hh по названию не видно; их отсеет `vet` только для
автопополнения — стартовый список не проверяется, поэтому чужие ретрансляторы при запуске удаляются вручную
(`/remove`), если начнут слать «только ссылку».

## Как набрать до сотен групп и тысяч каналов

Каталоги в открытом вебе дают ~200 живых тематических источников. Остальной охват — изнутри Telegram, после
входа аккаунтов:

1. Глобальный поиск (пауза resolve-Pacer между запросами, находки → кандидаты):

   ```
   radar sources search "вакансии python" "работа python" "python jobs" "django вакансии" "fastapi" \
     "фриланс программист" "фриланс заказы" "заказы разработка" "заказы на ботов" "telegram боты заказ" \
     "ищу разработчика" "нужен программист" "удалённая работа it" "удаленка it" "вакансии frontend" \
     "вакансии backend" "vue вакансии" "react вакансии" "веб разработка заказы" "парсинг заказ" \
     "it вакансии remote" "работа программистом" "подработка программист" "it фриланс чат"
   ```

2. Автопополнение: ссылки t.me и источники репостов из прочитанных сообщений становятся кандидатами
   и проверяются (`SourceService.vet`).

Скорость охвата групп = число аккаунтов × 25–30 вступлений в сутки; каналы читаются без вступления, их
подключение ограничено только резолвом (~1/мин на аккаунт).

## Пересборка

```
cd seeds/tools
python3 peek.py https://raw.githubusercontent.com/goq/telegram-list/master/README.md \
               https://raw.githubusercontent.com/NewHR/telegram/master/README.md   # кладёт goq.md, NewHR.md
python3 build.py <URL статей…> > /tmp/raw.txt
python3 finalize.py /tmp/raw.txt ../sources.txt
sed -i -E 's#^(!?)@(\+.*)$#\1t.me/\2#' ../sources.txt   # инвайты — в виде t.me/+hash
```
