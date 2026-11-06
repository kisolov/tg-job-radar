"""Сборка seeds/sources.txt из подборок: разделы вакансий целиком (!), тех-чаты — по стеку."""
import html as htmlmod
import re
import sys
import urllib.request

from sections import sections

STACK = re.compile(
    r"python|питон|django|flask|fastapi|aiogram|asyncio|javascript|\bjs\b|typescript|node|vue|nuxt|react|front|фронт|"
    r"web|веб|backend|бэкенд|бекенд|telegram|телеграм|бот|fullstack|full-stack|php|laravel|"
    r"вакан|работ|job|фриланс|freelance|удал|remote|заказ|hire|hiring|it-сообщ|айти|разработчик|developer|dev\b",
    re.I,
)
JOB = re.compile(r"вакан|работ|job|фриланс|freelance|удал|remote|заказ|hire|hiring|ищу|карьер|career", re.I)
JOB_SECTIONS = {"Вакансии", "Вакансии и работа", "Вакансии и работа для IT & Digital специалистов"}
STACK_SECTIONS = {
    "Языки программирования", "Фреймворки, среды разработок, библиотеки", "Сообщества разработчиков и программистов",
    "Разработка в Telegram, VK и других мессенджерах", "Разные IT-сообщества", "Москва", "Санкт-Петербург", "ЦФО",
    "СЗФО", "ЮФО", "СКФО", "ПФО", "УрФО", "СФО", "Русскоязычные IT-сообщества Ближнего Зарубежья",
    "Чаты и сообщества о разработке и языках программирования", "Фреймворки, библиотеки и IDE",
}
# стек, который владельцу не нужен (если ни Python, ни фронта): чаты по нему не берём
OFF = re.compile(r"\b(1c|1с|java\b|kotlin|android|ios|swift|golang|go\b|c\+\+|c#|\.net|rust|scala|haskell|erlang|"
                 r"elixir|delphi|lua|perl|ruby|clojure|unity|unreal|sap|abap)", re.I)
TME = re.compile(r"(?:t|telegram)\.me/(?:s/)?(\+[\w-]+|joinchat/[\w-]+|[A-Za-z]\w{3,31})", re.I)


def _key(name: str) -> str:
    """Ник — в нижнем регистре; инвайт-хэш регистрозависим и сохраняется как есть."""
    if name.startswith("+"):
        return name
    if name.lower().startswith("joinchat/"):
        return "+" + name.split("/", 1)[1]
    return name.lower()


def from_markdown(path, high, normal, why):
    for sec, items in sections(path).items():
        for name, line in items:
            if sec in JOB_SECTIONS:
                high.add(_key(name)); why[_key(name)] = f"{path}:{sec}"
            elif sec in STACK_SECTIONS and STACK.search(line) and not OFF.search(line):
                normal.add(_key(name)); why[_key(name)] = f"{path}:{sec}"


def from_article(url, high, normal, why, context=160):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
    text = raw.read().decode("utf-8", "replace")
    # ссылки в href → маркер в тексте, чтобы контекст был рядом
    text = re.sub(r'<a [^>]*href="[^"]*?(?:t|telegram)\.me/(?:s/)?([^"/?#]+)[^"]*"[^>]*>', r" t.me/\1 ", text)
    plain = htmlmod.unescape(re.sub(r"<[^>]+>", " ", text))
    plain = re.sub(r"\s+", " ", plain)
    for m in TME.finditer(plain):
        name = m.group(1)
        if name.lower().endswith("bot"):
            continue
        ctx = plain[max(0, m.start() - context): m.end() + 60]
        if OFF.search(ctx) and not re.search(r"python|питон|front|фронт|js|веб|web", ctx, re.I):
            continue
        if STACK.search(ctx) and re.search(r"python|питон|django|front|фронт|javascript|\bjs\b|vue|react|веб|web|"
                                           r"разработ|developer|программист|it\b|айти|ит\b|digital|бот|telegram", ctx,
                                           re.I):
            (high if JOB.search(ctx) else normal).add(_key(name))
            why[_key(name)] = url


if __name__ == "__main__":
    high, normal, why = set(), set(), {}
    for p in ("goq.md", "NewHR.md"):
        from_markdown(p, high, normal, why)
    for url in sys.argv[1:]:
        try:
            from_article(url, high, normal, why)
        except Exception as exc:  # noqa: BLE001
            print("FAIL", url, exc, file=sys.stderr)
    normal -= high
    name_off = re.compile(r"android|ios|java(?!script)|kotlin|golang|_go_|^go_|1c|1с|swift|scala|unity|cctv|asterisk|"
                          r"dba|copy|design|smm|market|seo|analyst|qa_|_qa|tester|hr_|recruit|sales|game|gamedev|"
                          r"devops|sysadmin|admin|cpp|csharp|dotnet|rust|php|bitrix|data|bigdata|ml|deeplearning", re.I)
    high = {n for n in high if not name_off.search(n)}
    normal = {n for n in normal if not name_off.search(n)}
    junk = {"joinchat", "share", "addstickers", "iv", "proxy", "s"}
    lines = ["# Стартовый список источников tg-job-radar. Формат: [!]@name — `!` = группа/канал вакансий и фриланса",
             "# (priority 10), без `!` — тех-чаты по стеку (priority 5). Происхождение — seeds/README.md.", ""]
    lines += [f"!@{n}" for n in sorted(high - junk)]
    lines += [f"@{n}" for n in sorted(normal - junk)]
    print("\n".join(lines))
    print(f"high={len(high)} normal={len(normal)}", file=sys.stderr)
