// Панель tg-job-radar: hash-роутинг, три экрана (обзор, находки, источники). Без сборки и зависимостей.
"use strict";

const REFRESH_MS = 30000;
const view = document.getElementById("view");
const nf = new Intl.NumberFormat("ru-RU");
const nf1 = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ---------- утилиты ----------
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n = (v) => nf.format(v ?? 0);
const pct = (a, b) => (b ? nf1.format((a / b) * 100) : "0") + " %";
const tokens = (v) => (v >= 1e6 ? nf1.format(v / 1e6) + " млн" : v >= 1e3 ? n(Math.round(v / 1e3)) + " тыс." : n(v));
const hhmm = (iso) => new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
const dayMonth = (isoDate) => new Date(isoDate).toLocaleDateString("ru-RU", { day: "numeric", month: "long", timeZone: "UTC" });
function ago(iso) {
  const min = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  if (min < 60) return `${min} мин назад`;
  if (min < 48 * 60) return `${Math.round(min / 60)} ч назад`;
  return `${Math.round(min / 1440)} дн назад`;
}
function when(iso) {
  if (!iso) return "—";
  const d = new Date(iso), now = new Date();
  const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
  if (days === 0) return "сегодня " + hhmm(iso);
  if (days === 1) return "вчера " + hhmm(iso);
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) + " " + hhmm(iso);
}
function plural(k, one, few, many) {
  const m10 = k % 10, m100 = k % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}
function contactHref(c) {
  if (!c) return null;
  if (/^@\w{3,}$/.test(c)) return "https://t.me/" + c.slice(1);
  if (/^(https?:\/\/)?t\.me\//.test(c)) return c.startsWith("http") ? c : "https://" + c;
  return null;
}
function contactOf(row, sender) {
  return row.contact || (sender ? "@" + sender : "профиль автора");
}
function toast(text) {
  const t = document.createElement("div");
  t.className = "toast"; t.role = "status"; t.textContent = text;
  document.body.append(t);
  setTimeout(() => t.remove(), 3500);
}
function parseHash() {
  const [path, query] = location.hash.replace(/^#/, "").split("?");
  return { path: path || "/", params: new URLSearchParams(query || "") };
}
function setParams(path, params) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null && v !== false));
  const next = "#" + path + (q.toString() ? "?" + q : "");
  if (location.hash !== next) location.hash = next; else route();
}

// ---------- API ----------
class AuthError extends Error {}
async function api(path, opts = {}) {
  const init = { credentials: "same-origin", ...opts, headers: { ...(opts.headers || {}) } };
  if (init.method && init.method !== "GET") {
    init.headers["X-Radar"] = "1";
    if (init.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(init.body); }
  }
  const r = await fetch(path, init);
  if (r.status === 401) throw new AuthError();
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || "Ошибка " + r.status);
  return body;
}

// ---------- шапка ----------
let paused = null;
function renderHeader(o) {
  paused = o.paused;
  const pill = document.getElementById("delivery-pill");
  const btn = document.getElementById("pause-btn");
  pill.hidden = btn.hidden = false;
  pill.className = "pill big " + (paused ? "warn" : "ok");
  pill.innerHTML = `<svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true"><circle cx="4" cy="4" r="4" fill="currentColor"></circle></svg>${paused ? "Доставка на паузе" : "Доставка идёт"}`;
  btn.textContent = paused ? "Возобновить доставку" : "Поставить на паузу";
  document.getElementById("updated").textContent = "обновлено " + new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}
document.getElementById("pause-btn").addEventListener("click", async (e) => {
  e.currentTarget.disabled = true;
  try {
    await api("/api/delivery", { method: "POST", body: { paused: !paused } });
    toast(!paused ? "Доставка на паузе. Находки копятся." : "Доставка возобновлена.");
    await refreshHeader();
  } catch (err) { handleError(err); } finally { e.currentTarget.disabled = false; }
});
async function refreshHeader() {
  const o = await api("/api/overview");
  renderHeader(o);
  return o;
}

// ---------- обзор ----------
const ACCOUNT_STATUS = {
  active: ["Читает", "ok"], flood_wait: ["Пауза", "warn"], banned: ["Забанен", "bad"],
  unauthorized: ["Нет входа", "bad"], disabled: ["Выключен", "off"],
};
const KIND = { vacancy: ["Вакансия", "info"], project: ["Проект", "warn"] };

function kindTag(kind) {
  if (!kind) return "";  // ещё не классифицирована — тип неизвестен
  const [label, cls] = KIND[kind] || [kind, "off"];
  return `<span class="pill tag ${cls}">${label}</span>`;
}

function renderOverview(o) {
  const st = o.stats, c = o.counts, s = o.sources;
  const totalTokens = st.prompt_tokens + st.completion_tokens;
  const kpis = [
    ["Прочитано сообщений", n(st.read), `из ${n(s.reading)} источников`],
    ["Прошло предфильтр", n(st.passed_prefilter), `${pct(st.passed_prefilter, st.read)} прочитанного`],
    ["Уникальных (без дублей)", n(c.unique), `${n(Math.max(0, c.copies - c.unique))} копий склеено`],
    ["Ушло в LLM", n(st.llm_items), `${n(st.requests)} ${plural(st.requests, "пакет", "пакета", "пакетов")}`],
    ["Находок доставлено", n(c.delivered), c.queued ? `ещё ${n(c.queued)} ждёт отправки` : "очередь пуста"],
    ["Стоимость LLM", "≈ " + nf2.format(o.cost), `${tokens(totalTokens)} токенов`],
  ];
  const funnel = [
    ["Прочитано", st.read], ["Прошло предфильтр", st.passed_prefilter], ["Уникальных", c.unique],
    ["Классифицировано", st.llm_items], ["Подошло", c.accepted], ["Доставлено", c.delivered],
  ];
  const top = Math.max(1, ...funnel.map((f) => f[1]));
  const weekMax = Math.max(1, ...o.week.map((d) => d.n));
  const reading = o.accounts.filter((a) => a.status === "active").length;
  const tokenShare = o.llm.token_limit ? Math.min(100, (totalTokens / o.llm.token_limit) * 100) : 0;

  const accountRows = o.accounts.map((a) => {
    let [label, cls] = ACCOUNT_STATUS[a.status] || [a.status, "off"];
    if (a.status === "flood_wait" && a.status_until) label = "Пауза до " + hhmm(a.status_until);
    const pace = "×" + nf1.format(a.pace_factor) + " · "
      + (a.last_flood_at ? "FloodWait " + ago(a.last_flood_at) : a.pace_factor > 1 ? "торможение" : "норма");
    const share = Math.min(100, (a.groups / o.membership_cap) * 100);
    return `<tr>
      <td class="mono nw">${esc(a.phone)}</td>
      <td><span class="pill ${cls}">${esc(label)}</span></td>
      <td class="nw"><div style="display:flex;align-items:center;gap:8px"><div class="track mini"><div style="width:${share}%"></div></div><span class="mono">${n(a.groups)} / ${n(o.membership_cap)}</span></div></td>
      <td class="mono nw">${n(a.joins_today)} / ${n(a.joins_limit)}</td>
      <td class="pace">${esc(pace)}</td>
      <td class="mono nw">${a.status === "active" ? n(a.channels) : "—"}</td>
      <td class="ev">${esc(a.last_error || "—")}</td>
    </tr>`;
  }).join("");

  const recent = o.recent.map((r) => `
    <a class="recent" href="#/findings?id=${r.id}">
      <span class="meta">${kindTag(r.kind)}${esc(hhmm(r.delivered_at || r.created_at))} · ${esc(r.source_title || "—")}</span>
      <span style="font-weight:600">${esc(r.title)}</span>
      <span style="color:var(--ink-3);font-size:13px">${esc([r.money || "бюджет не указан", r.contact || "профиль автора",
        r.copies > 1 ? `ещё в ${r.copies - 1} ${plural(r.copies - 1, "чате", "чатах", "чатах")}` : ""].filter(Boolean).join(" · "))}</span>
    </a>`).join("") || `<span class="muted">Пока ничего не доставлено.</span>`;

  view.innerHTML = `
    <div class="head"><h1>Сегодня</h1><span class="muted">${esc(dayMonth(o.day))}, сутки UTC</span></div>
    <section aria-label="Показатели за сутки" class="grid-kpi">
      ${kpis.map(([l, v, h]) => `<div class="kpi"><span class="l">${l}</span><span class="v">${v}</span><span class="h">${esc(h)}</span></div>`).join("")}
    </section>
    <div class="cols">
      <div class="col-main">
        <section class="card">
          <div class="card-head"><h2>Конвейер за сутки</h2><span class="muted small">от прочитанного до карточки в боте</span></div>
          <div class="funnel">
            ${funnel.map(([l, v]) => `<div class="funnel-row"><span class="lab">${l}</span><div class="track"><div style="width:${v ? Math.max(1, Math.sqrt(v / top) * 100) : 0}%"></div></div><span class="num">${n(v)}</span></div>`).join("")}
          </div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Парсеры</h2><span class="muted small">${n(o.accounts.length)} ${plural(o.accounts.length, "аккаунт", "аккаунта", "аккаунтов")} · ${n(reading)} читают · лимит групп ${n(o.membership_cap)} на аккаунт</span></div>
          ${o.accounts.length ? `<div class="table-wrap"><table class="accounts">
            <thead><tr><th>Аккаунт</th><th>Статус</th><th>Групп</th><th>Вступлений сегодня</th><th>Темп</th><th>Каналов на опросе</th><th>Последнее событие</th></tr></thead>
            <tbody>${accountRows}</tbody></table></div>`
            : `<div class="empty">Аккаунтов нет. Добавьте: <span class="mono">radar accounts login +7…</span></div>`}
        </section>
        <section class="card">
          <div class="card-head"><h2>Находки за 7 дней</h2><span class="muted small">доставлено в бота по дням</span></div>
          <div class="week">
            ${o.week.map((d) => `<div class="d"><span class="n">${n(d.n)}</span><div class="bar" style="height:${Math.max(2, Math.round((d.n / weekMax) * 120))}px"></div><span class="day">${esc(new Date(d.day).toLocaleDateString("ru-RU", { day: "numeric", month: "numeric", timeZone: "UTC" }))}</span></div>`).join("")}
          </div>
        </section>
      </div>
      <aside class="col-side">
        <section class="card" style="gap:12px">
          <h2>LLM</h2>
          <div class="kv"><span>Модель</span><span>${esc(o.llm.model)}</span></div>
          <div style="display:flex;flex-direction:column;gap:6px">
            <div class="kv"><span>Токены сегодня</span><span>${tokens(totalTokens)} из ${tokens(o.llm.token_limit)}</span></div>
            <div class="track thin"><div style="width:${tokenShare}%"></div></div>
          </div>
          <div class="kv"><span>Запросов</span><span>${n(st.requests)}</span></div>
          <div class="kv"><span>Пакет / ожидание</span><span>${n(o.llm.batch_size)} · ${n(o.llm.batch_wait_s)} с</span></div>
          <div class="kv"><span>Ждут классификации</span><span>${n(c.pending)}</span></div>
        </section>
        <section class="card" style="gap:12px">
          <div class="card-head"><h2>Последние находки</h2><a href="#/findings" class="small" style="font-weight:600">Все находки</a></div>
          ${recent}
        </section>
        <section class="card" style="gap:12px">
          <div class="card-head"><h2>Источники</h2><a href="#/sources" class="small" style="font-weight:600">Открыть</a></div>
          <div class="mini-stats">
            ${[["Читаются", n(s.reading)], ["Ждут резолва", n(s.awaiting_resolve)], ["Ждут вступления", n(s.awaiting_join)],
               ["Мёртвые", n(s.dead)], ["Отсеяны", n(s.rejected)], ["Найдено автопоиском", "+" + n(c.discovered) + " сегодня"]]
              .map(([l, v]) => `<div><span class="l">${l}</span><span class="v">${v}</span></div>`).join("")}
          </div>
        </section>
      </aside>
    </div>`;
}

// ---------- находки ----------
const F_STATUS = {
  delivered: ["Доставлена", "ok"], rejected: ["Отклонена LLM", "off"], pending: ["Ждёт LLM", "warn"],
  accepted: ["В очереди доставки", "info"], delivering: ["В очереди доставки", "info"],
  failed: ["Не обработана", "bad"],
};
const F_TABS = [["all", "Все"], ["delivered", "Доставлены"], ["queue", "В очереди"], ["pending", "Ждут LLM"], ["rejected", "Отклонены"]];
let findingsState = { key: "", items: [], page: 1, total: 0 };

function findingItem(f, selected) {
  const [label, cls] = F_STATUS[f.status] || [f.status, "off"];
  const more = f.copies > 1 ? `ещё в ${f.copies - 1} ${plural(f.copies - 1, "чате", "чатах", "чатах")}` : "";
  return `<button type="button" class="item" data-id="${f.id}" aria-current="${selected ? "true" : "false"}">
    <span class="meta">${kindTag(f.kind)}<span class="pill tag ${cls}">${label}</span><span>${esc(when(f.created_at))} · ${esc(f.source_title || "—")}</span><span style="margin-left:auto">${more}</span></span>
    <h2>${esc(f.title)}</h2>
    <span class="facts"><span>${esc(f.money || "бюджет не указан")}</span><span>${esc(f.work_format || "—")}</span><span class="mono">${esc(f.contact || "—")}</span></span>
  </button>`;
}

async function renderFindings(params) {
  const p = { tab: params.get("tab") || "all", kind: params.get("kind") || "", period: params.get("period") || "7d", q: params.get("q") || "" };
  const selected = params.get("id");
  const key = JSON.stringify(p);
  if (key !== findingsState.key) {
    const page = await api("/api/findings?" + new URLSearchParams({ ...p, page: 1 }));
    findingsState = { key, items: page.items, page: 1, total: page.total, tabs: page.tabs };
  }
  const st = findingsState;
  const go = (patch) => setParams("/findings", { ...p, id: selected, ...patch });

  view.innerHTML = `
    <div class="head"><h1>Находки</h1><span class="muted">всё, что прошло предфильтр, — с решением LLM</span></div>
    <form role="search" aria-label="Фильтр находок" class="filters" id="f-form">
      <label class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#5B6370" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>
        <span class="sr">Поиск по тексту</span>
        <input type="search" name="q" value="${esc(p.q)}" placeholder="Поиск: fastapi, бот, @контакт…">
      </label>
      <div role="group" aria-label="Решение" class="seg">
        ${F_TABS.map(([k, l]) => `<button type="button" data-tab="${k}" aria-pressed="${p.tab === k}">${l} <span class="c">${n(st.tabs[k])}</span></button>`).join("")}
      </div>
      <label class="field">Тип <select name="kind">
        ${[["", "Все"], ["vacancy", "Вакансии"], ["project", "Проекты"]].map(([v, l]) => `<option value="${v}"${p.kind === v ? " selected" : ""}>${l}</option>`).join("")}
      </select></label>
      <label class="field">Период <select name="period">
        ${[["today", "Сегодня"], ["7d", "7 дней"], ["30d", "30 дней"], ["all", "Всё время"]].map(([v, l]) => `<option value="${v}"${p.period === v ? " selected" : ""}>${l}</option>`).join("")}
      </select></label>
    </form>
    <div class="split">
      <section aria-label="Список находок" class="list" id="f-list">
        ${st.items.length ? st.items.map((f) => findingItem(f, String(f.id) === selected)).join("")
          : `<div class="empty">Ничего не нашлось. Попробуйте другой период или вкладку.</div>`}
        ${st.items.length < st.total ? `<div class="center"><button type="button" class="btn" id="f-more">Показать ещё</button></div>` : ""}
      </section>
      <article aria-label="Выбранная находка" class="detail" id="f-detail">
        <p class="muted" style="margin:0">Выберите находку слева.</p>
      </article>
    </div>`;

  const form = document.getElementById("f-form");
  form.addEventListener("submit", (e) => { e.preventDefault(); go({ q: form.q.value.trim(), id: "" }); });
  let timer;
  form.q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => go({ q: form.q.value.trim(), id: "" }), 400); });
  form.kind.addEventListener("change", () => go({ kind: form.kind.value, id: "" }));
  form.period.addEventListener("change", () => go({ period: form.period.value, id: "" }));
  form.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => go({ tab: b.dataset.tab, id: "" })));
  document.getElementById("f-list").addEventListener("click", (e) => {
    const it = e.target.closest(".item");
    if (it) go({ id: it.dataset.id });
  });
  const more = document.getElementById("f-more");
  if (more) more.addEventListener("click", async () => {
    more.disabled = true;
    const page = await api("/api/findings?" + new URLSearchParams({ ...p, page: st.page + 1 }));
    st.items = st.items.concat(page.items); st.page += 1; st.total = page.total;
    route();
  });
  if (p.q) { form.q.focus(); form.q.setSelectionRange(p.q.length, p.q.length); }

  const id = selected || (st.items[0] && String(st.items[0].id));
  if (id) await renderDetail(id);
}

async function renderDetail(id) {
  const box = document.getElementById("f-detail");
  let d;
  try { d = await api("/api/findings/" + encodeURIComponent(id)); }
  catch (err) { if (err instanceof AuthError) throw err; box.innerHTML = `<p class="muted" style="margin:0">${esc(err.message)}</p>`; return; }
  document.querySelectorAll(".item").forEach((el) => el.setAttribute("aria-current", el.dataset.id === String(id) ? "true" : "false"));
  const r = d.row;
  const [label, cls] = F_STATUS[r.status] || [r.status, "off"];
  const statusText = r.status === "delivered" && r.delivered_at ? "Доставлена в бота " + when(r.delivered_at) : label;
  const contact = contactOf(r, d.sender_username);
  const href = contactHref(contact);
  const others = d.copies.slice(1);
  box.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:8px">
      <span class="meta" style="font-size:12.5px">${kindTag(r.kind)}<span class="pill tag ${cls}">${esc(statusText)}</span>${d.requirements_version ? `<span>требования v${d.requirements_version}</span>` : ""}</span>
      <h2>${esc(r.title)}</h2>
    </div>
    <dl>
      <dt>Деньги</dt><dd>${esc(r.money || "не указаны")}</dd>
      <dt>Формат</dt><dd>${esc(r.work_format || "—")}</dd>
      <dt>Контакт</dt><dd>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(contact)}</a>` : esc(contact)}</dd>
      <dt>${r.status === "rejected" ? "Почему отклонена" : "Почему подходит"}</dt><dd>${esc(d.reason || (r.status === "pending" ? "ждёт решения LLM" : "—"))}</dd>
      <dt>Оригинал</dt><dd>${d.link ? `<a href="${esc(d.link)}" target="_blank" rel="noopener">${esc(r.source_title || "сообщение")}</a>` : esc(r.source_title || "—")}</dd>
      <dt>Найдена</dt><dd>${esc(when(r.created_at))}</dd>
    </dl>
    <section style="display:flex;flex-direction:column;gap:8px"><h3>Текст сообщения</h3><div class="msg">${esc(d.text)}</div></section>
    ${others.length ? `<section style="display:flex;flex-direction:column;gap:8px">
      <h3>Встречалось также в <span class="mono muted" style="font-weight:500">${others.length}</span></h3>
      <ul class="copies">${others.map((c) => `<li>${c.link ? `<a href="${esc(c.link)}" target="_blank" rel="noopener">${esc(c.source_title || c.link)}</a>` : esc(c.source_title || "—")}<span class="muted small">${esc(when(c.created_at))}</span></li>`).join("")}</ul>
    </section>` : ""}`;
}

// ---------- источники ----------
const S_STATUS = {
  reading: ["Читается", "ok"], awaiting_join: ["Ждёт вступления", "info"], awaiting_resolve: ["Ждёт резолва", "warn"],
  dead: ["Мёртвый", "bad"], rejected: ["Отсеян", "off"],
};
const S_TABS = [["all", "Все"], ["reading", "Читаются"], ["waiting", "Ждут"], ["dead", "Мёртвые"], ["rejected", "Отсеяны"]];
const ORIGIN = { seed: "стартовый список", discovery: "автопоиск" };

async function renderSources(params) {
  const p = { tab: params.get("tab") || "all", kind: params.get("kind") || "", sort: params.get("sort") || "found", page: Number(params.get("page")) || 1 };
  const { page, counts: c } = await api("/api/sources?" + new URLSearchParams(p));
  const go = (patch) => setParams("/sources", { ...p, page: 1, ...patch });
  const from = page.total ? (p.page - 1) * 20 + 1 : 0, to = (p.page - 1) * 20 + page.items.length;
  const stats = [
    ["Читаются", c.reading, `${n(c.reading_groups)} ${plural(c.reading_groups, "группа", "группы", "групп")} · ${n(c.reading_channels)} ${plural(c.reading_channels, "канал", "канала", "каналов")}`],
    ["Ждут вступления", c.awaiting_join, "вступления идут с дневным лимитом"],
    ["Ждут резолва", c.awaiting_resolve, `в том числе ${n(c.resolve_from_discovery)} из автопоиска`],
    ["Мёртвые", c.dead, "приватные, удалённые, кик"],
    ["Отсеяны", c.rejected, "не по теме, ретрансляторы, убраны вами"],
    ["Дали находки за 7 дней", c.productive, `${pct(c.productive, c.reading)} читаемых`],
  ];
  const rows = page.items.map((r) => {
    const [label, cls] = S_STATUS[r.status] || [r.status, "off"];
    const origin = ORIGIN[r.added_by] || "вы, " + new Date(r.created_at).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
    const showRef = r.ref.startsWith("+") ? "t.me/" + r.ref : "@" + r.ref;
    const counted = r.status === "reading" || r.read > 0;
    return `<tr>
      <td><div class="stack"><span style="font-weight:600">${esc(r.title || showRef)}</span>${r.link ? `<a class="mono" style="font-size:12.5px" href="${esc(r.link)}" target="_blank" rel="noopener">${esc(showRef)}</a>` : `<span class="mono muted">${esc(showRef)}</span>`}</div></td>
      <td style="color:var(--ink-3)">${r.kind === "group" ? "группа" : r.kind === "channel" ? "канал" : "—"}</td>
      <td><span class="pill ${cls}">${label}</span></td>
      <td class="mono" style="font-size:12.5px;color:var(--ink-3)">${esc(r.account_phone || "—")}</td>
      <td class="mono r">${n(r.found)}</td>
      <td class="mono r">${counted ? n(r.read) : "—"}</td>
      <td class="mono r">${counted ? n(r.passed) : "—"}</td>
      <td style="color:var(--ink-3)">${esc(origin)}</td>
      <td class="r">${r.status === "rejected" ? "" : `<button type="button" class="icon-btn" data-remove="${r.id}" data-name="${esc(r.title || showRef)}" aria-label="Убрать источник ${esc(r.title || showRef)}" title="Убрать источник">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#5B6370" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"></path></svg></button>`}</td>
    </tr>`;
  }).join("");

  view.innerHTML = `
    <div class="head" style="align-items:center">
      <h1>Источники</h1>
      <form class="add-form" id="s-add">
        <label style="flex:1 1 280px;display:flex"><span class="sr">Ссылки на чаты</span>
          <input class="text" name="text" type="text" placeholder="t.me/chat, @channel — можно несколько" autocomplete="off"></label>
        <button type="submit" class="btn primary">Добавить</button>
      </form>
    </div>
    <section aria-label="Источники по статусам" class="grid-kpi narrow">
      ${stats.map(([l, v, h]) => `<div class="kpi"><span class="l">${l}</span><span class="v">${n(v)}</span><span class="h">${esc(h)}</span></div>`).join("")}
    </section>
    <section class="card" style="padding:16px 18px">
      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">
        <div role="group" aria-label="Статус" class="seg">${S_TABS.map(([k, l]) => `<button type="button" data-tab="${k}" aria-pressed="${p.tab === k}">${l}</button>`).join("")}</div>
        <label class="field">Тип <select id="s-kind">${[["", "Все"], ["group", "Группы"], ["channel", "Каналы"]].map(([v, l]) => `<option value="${v}"${p.kind === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="field">Сортировка <select id="s-sort">${[["found", "По находкам"], ["read", "По прочитанному"], ["new", "Новые"]].map(([v, l]) => `<option value="${v}"${p.sort === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
      </div>
      ${page.items.length ? `<div class="table-wrap"><table class="sources-table">
        <thead><tr><th>Источник</th><th>Тип</th><th>Статус</th><th>Читает</th><th class="r">Находок</th><th class="r">Прочитано</th><th class="r">Прошло предфильтр</th><th>Откуда</th><th><span class="sr">Действия</span></th></tr></thead>
        <tbody id="s-rows">${rows}</tbody></table></div>` : `<div class="empty">В этой вкладке пусто.</div>`}
      <div class="pager"><span>${n(from)}–${n(to)} из ${n(page.total)}</span><div>
        <button type="button" class="btn sm" id="s-prev"${p.page <= 1 ? " disabled" : ""}>Назад</button>
        <button type="button" class="btn sm" id="s-next"${to >= page.total ? " disabled" : ""}>Дальше</button></div></div>
    </section>`;

  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => go({ tab: b.dataset.tab })));
  document.getElementById("s-kind").addEventListener("change", (e) => go({ kind: e.target.value }));
  document.getElementById("s-sort").addEventListener("change", (e) => go({ sort: e.target.value }));
  document.getElementById("s-prev").addEventListener("click", () => go({ page: p.page - 1 }));
  document.getElementById("s-next").addEventListener("click", () => go({ page: p.page + 1 }));
  document.getElementById("s-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = e.target.text.value.trim();
    if (!text) return;
    try {
      const res = await api("/api/sources", { method: "POST", body: { text } });
      if (!res.added.length && !res.duplicates.length) toast("Не нашёл ссылок. Пример: t.me/chat @channel");
      else toast(`Добавлено: ${res.added.join(", ") || "—"}. Уже были: ${res.duplicates.join(", ") || "—"}`);
      route();
    } catch (err) { handleError(err); }
  });
  const body = document.getElementById("s-rows");
  if (body) body.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-remove]");
    if (!b || !confirm(`Убрать источник «${b.dataset.name}»? Он перестанет читаться.`)) return;
    try { await api("/api/sources/" + b.dataset.remove, { method: "DELETE" }); toast("Источник убран."); route(); }
    catch (err) { handleError(err); }
  });
}

// ---------- роутинг ----------
function showLogin() {
  document.getElementById("delivery-pill").hidden = document.getElementById("pause-btn").hidden = true;
  view.innerHTML = `<div class="empty" style="max-width:520px;margin:48px auto;display:flex;flex-direction:column;gap:8px">
    <h1 style="font-size:20px;color:var(--ink)">Нужен вход</h1>
    <span>Пришлите боту команду <span class="mono">/web</span> и откройте ссылку из ответа. Ссылка одноразовая и живёт 10 минут.</span></div>`;
}
function handleError(err) {
  if (err instanceof AuthError) showLogin();
  else toast(err.message || "Что-то пошло не так");
}

let busy = false;
async function route() {
  const { path, params } = parseHash();
  const name = path.startsWith("/findings") ? "findings" : path.startsWith("/sources") ? "sources" : "overview";
  document.querySelectorAll(".nav a").forEach((a) => {
    if (a.dataset.route === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  document.title = { overview: "Обзор", findings: "Находки", sources: "Источники" }[name] + " — tg-job-radar";
  busy = true;
  try {
    if (name === "overview") renderOverview(await refreshHeader());
    else {
      if (paused === null) await refreshHeader();
      if (name === "findings") await renderFindings(params); else await renderSources(params);
    }
  } catch (err) {
    if (err instanceof AuthError) showLogin();
    else view.innerHTML = `<div class="empty">Не удалось загрузить: ${esc(err.message)}. <button type="button" class="btn sm" onclick="route()">Повторить</button></div>`;
  } finally { busy = false; }
}

window.addEventListener("hashchange", route);
setInterval(async () => {
  if (busy || document.hidden) return;
  const { path } = parseHash();
  try {
    if (path === "/" || path === "") renderOverview(await refreshHeader());
    else await refreshHeader();
  } catch (err) { if (err instanceof AuthError) showLogin(); }
}, REFRESH_MS);
route();
