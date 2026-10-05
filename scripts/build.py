#!/usr/bin/env python3
"""
ЛОТ 44 — сборщик витрины торгов Костромской области (одностраничная версия).
Запуск: python scripts/build.py
Выход:  site/index.html  (данные: torgi.gov.ru)
Лоты, относящиеся к объектам культурного наследия, помечаются значком «ОКН».
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
import ssl


def _ssl_ctx():
    ctx = ssl.create_default_context()
    try:
        ctx.check_hostname = True
    except Exception:
        pass
    # fallback if system certs broken (common on Windows Python)
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        ctx = ssl._create_unverified_context()
    return ctx


SSL_CTX = _ssl_ctx()
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA = ROOT / "data"
MSK = timezone(timedelta(hours=3))

# --- API (публичный, без ключа) ---
TORGI_API = "https://torgi.gov.ru/new/api/public/lotcards/search"
# Костромская область в словаре ГИС Торги (dynSubjRF)
TORGI_REGION = "47"

UA = (
    "Mozilla/5.0 (compatible; LOT44Bot/1.0; +https://vk.ru/lot44) "
    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)

# «объект культурного наследия» / «объекты культурного наследия …»
OKN_RE = re.compile(r"объект[а-яё]*\s+культурн[а-яё]*\s+наследи[а-яё]*", re.IGNORECASE)


def now_msk() -> datetime:
    return datetime.now(MSK)


def http_get_json(url: str, params: dict | None = None, timeout: int = 45) -> Any:
    if params:
        from urllib.parse import urlencode
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def load_cache(name: str) -> Any | None:
    p = DATA / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_cache(name: str, data: Any) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------- ТОРГИ ----------

def fetch_torgi_lots():
    """Все активные лоты Костромской области с torgi.gov.ru.

    Возвращает (lots, total|None). Набор параметров проверен на живом API:
    другой вариант sort даёт HTTP 400; сервер отдаёт не больше 10 записей на
    страницу — идём по страницам до totalElements. На каждый запрос — до 3 попыток.
    """
    lots: list[dict] = []
    page = 0
    total = None
    while page < 60:  # safety
        url = (TORGI_API
               + "?dynSubjRF=" + TORGI_REGION
               + "&lotStatus=PUBLISHED,APPLICATIONS_SUBMISSION"
               + "&matchPhrase=false&byFirstVersion=true"
               + "&size=10&page=%d" % page
               + "&sort=firstVersionPublicationDate,desc")
        data = None
        for attempt in range(1, 4):  # до 3 попыток на страницу
            try:
                data = http_get_json(url)
                break
            except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
                print(f"[torgi] API error page={page}, попытка {attempt}: {e}", file=sys.stderr)
                time.sleep(1.5 * attempt)
        if data is None:
            print(f"[torgi] страница {page} недоступна — пагинация прервана", file=sys.stderr)
            break

        content = data.get("content") or []
        if not content:
            break
        for item in content:
            lots.append(normalize_torgi(item))

        total = data.get("totalElements")
        page += 1
        if total is not None and len(lots) >= int(total):
            break
        time.sleep(0.25)  # мягкий темп

    print(f"[torgi] fetched {len(lots)} lots")
    return lots, total


def normalize_torgi(raw: dict) -> dict:
    """Приводим карточку лота к единому виду."""
    lot_id = (
        raw.get("id")
        or raw.get("lotId")
        or raw.get("lotNumber")
        or ""
    )
    notice = (
        raw.get("noticeNumber")
        or raw.get("notice_number")
        or raw.get("noticeId")
        or ""
    )
    name = (
        raw.get("lotName")
        or raw.get("name")
        or raw.get("objectName")
        or raw.get("title")
        or "Лот без названия"
    )
    price = raw.get("priceMin") or raw.get("price") or raw.get("startPrice") or raw.get("nprice")
    price_str = format_price(price)

    deal = raw.get("biddType") or raw.get("dealType") or raw.get("lotType") or ""
    if isinstance(deal, dict):
        deal = deal.get("name") or deal.get("code") or ""
    deal = str(deal)
    deal_label = classify_deal(deal, name)

    form = raw.get("biddForm") or raw.get("form") or raw.get("procedureType") or ""
    if isinstance(form, dict):
        form = form.get("name") or ""
    form = str(form) or "—"

    deadline = (
        raw.get("applicationDeadline")
        or raw.get("biddEndTime")
        or raw.get("endDate")
        or raw.get("expireDate")
        or ""
    )
    deadline_str, days_left = format_deadline(deadline)

    link = (
        raw.get("lotUrl")
        or raw.get("url")
        or f"https://torgi.gov.ru/new/public/lots/lot/{lot_id}"
    )
    if link and not link.startswith("http"):
        link = "https://torgi.gov.ru/new/public/lots/lot/" + str(lot_id)

    snip = (
        raw.get("lotDescription")
        or raw.get("description")
        or raw.get("characteristic")
        or name
    )
    snip = re.sub(r"\s+", " ", str(snip)).strip()[:200]

    okn = bool(OKN_RE.search(str(name) + " " + snip))

    return {
        "id": str(lot_id),
        "notice": str(notice),
        "name": str(name)[:180],
        "snip": snip,
        "price": price_str,
        "deal": deal_label,
        "form": form[:60],
        "deadline": deadline_str,
        "deadline_raw": str(deadline),
        "days_left": days_left,
        "okn": okn,
        "link": link,
        "nn": f"№ {notice} · лот {raw.get('lotNumber') or '1'}" if notice else f"лот {lot_id}",
    }


def classify_deal(deal: str, name: str) -> str:
    d = (deal + " " + name).lower()
    if any(x in d for x in ("аренд", "rent", "пользован")):
        return "Аренда"
    if any(x in d for x in ("продаж", "приватиз", "sale", "купл")):
        return "Продажа"
    return "Другое"


def format_price(v: Any) -> str:
    if v is None or v == "" or v == 0:
        return "—"
    try:
        n = float(str(v).replace(" ", "").replace(",", "."))
        if n == 0:
            return "0 ₽"
        return f"{n:,.0f} ₽".replace(",", " ")
    except Exception:
        return str(v)


def format_deadline(s: Any) -> tuple[str, int | None]:
    if not s:
        return "—", None
    s = str(s)
    # ISO or "2026-09-30T17:00:00"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})", s)
    if not m:
        m2 = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s)
        if m2:
            d, mo, y = m2.group(1), m2.group(2), m2.group(3)
            return f"до {d}.{mo}.{y}", None
        return s[:30], None
    y, mo, d, hh, mm = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), tzinfo=MSK)
        left = (dt.date() - now_msk().date()).days
        return f"до {d}.{mo}.{y}, {hh}:{mm} МСК", left
    except Exception:
        return f"до {d}.{mo}.{y}, {hh}:{mm} МСК", None


# ---------- HTML ----------

CSS = """
:root{
  --navy:#14213D; --navy2:#1F2F55; --amber:#FCA311; --bg:#f2f4f8; --card:#fff;
  --ink:#1c1e21; --muted:#6b7280; --line:#e5e7eb; --green:#047857; --blue:#1d4ed8;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
a{color:inherit}
.hero{background:linear-gradient(135deg,var(--navy),var(--navy2));color:#fff;padding:26px 22px 22px}
.wrap{max-width:1180px;margin:0 auto}
.brandrow{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.brandrow .l{font-weight:800;font-size:22px}
.brandrow .l .n{color:var(--amber)}
.hero h1{margin:10px 0 6px;font-size:26px;line-height:1.25}
.hero p{margin:0;color:#c8d3ea;font-size:14.5px}
.meta{margin-top:12px;font-size:13px;color:#9fb0d0}
.meta a{color:#FCA311;font-weight:700}
.controls{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);
          padding:12px 22px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.controls input[type=search]{flex:1 1 260px;min-width:200px;padding:10px 14px;border:1px solid var(--line);
          border-radius:10px;font-size:14.5px;outline:none}
.controls input[type=search]:focus{border-color:var(--amber)}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:7px 14px;font-size:13.5px;
      cursor:pointer;font-weight:600;color:#374151}
.chip.on{background:var(--amber);border-color:var(--amber);color:var(--navy)}
.count{font-size:13px;color:var(--muted);margin-left:auto;white-space:nowrap}
main{max-width:1180px;margin:0 auto;padding:18px 22px 40px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.lot,.obj{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;
          display:flex;flex-direction:column;gap:10px}
.badges{display:flex;flex-wrap:wrap;gap:6px}
.b{font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;background:#eef2ff;color:#1d4ed8}
.b.deal-Продажа{background:#dcfce7;color:#047857}
.b.deal-Аренда{background:#dbeafe;color:#1d4ed8}
.b.deal-Другое{background:#f3f4f6;color:#4b5563}
.b.form{background:#f3f4f6;color:#374151}
.b.okn{background:var(--amber);color:var(--navy)}
h3{margin:0;font-size:16px;line-height:1.35}
.snip{margin:0;color:var(--muted);font-size:13.5px}
.price{font-weight:800;font-size:18px;color:var(--navy)}
.meta2{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;color:var(--muted)}
.meta2 .urgent{color:#b45309;font-weight:700}
.foot{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:13px;margin-top:auto}
.foot a{color:var(--blue);font-weight:600;text-decoration:none}
.nn{color:var(--muted);font-size:12px}
.empty{text-align:center;padding:48px;color:var(--muted)}
footer{background:var(--navy);color:#9fb0d0;padding:28px 22px;margin-top:40px;font-size:13px;line-height:1.6}
footer a{color:#FCA311;font-weight:700}
footer .brand{color:#fff;font-weight:800;margin-bottom:8px;font-size:16px}
footer .brand span{color:var(--amber)}
@media(max-width:600px){.hero h1{font-size:22px}.grid{grid-template-columns:1fr}}
"""

JS_FILTER = """
<script>
(function(){
  const q = document.getElementById('q');
  const chips = document.querySelectorAll('.chip');
  const cards = document.querySelectorAll('[data-card]');
  const count = document.getElementById('count');
  let filter = 'Все';
  function apply(){
    const term = (q?.value || '').toLowerCase().trim();
    let n = 0;
    cards.forEach(c => {
      const hay = (c.dataset.search || '').toLowerCase();
      const cat = c.dataset.cat || '';
      const okCat = filter === 'Все' || cat === filter;
      const okQ = !term || hay.includes(term);
      const show = okCat && okQ;
      c.style.display = show ? '' : 'none';
      if (show) n++;
    });
    if (count) count.textContent = 'Показано: ' + n + ' из ' + cards.length;
  }
  chips.forEach(ch => ch.addEventListener('click', () => {
    chips.forEach(x => x.classList.remove('on'));
    ch.classList.add('on');
    filter = ch.dataset.filter;
    apply();
  }));
  q?.addEventListener('input', apply);
  apply();
})();
</script>
"""


def refresh_days(lots: list[dict]) -> None:
    """Пересчитывает дедлайны/счётчики дней из сырой даты (важно для кэша)."""
    for L in lots:
        raw = L.get("deadline_raw")
        if raw:
            ds, dl = format_deadline(raw)
            L["deadline"], L["days_left"] = ds, dl


def render_torgi(lots: list[dict], updated: str) -> str:
    refresh_days(lots)

    counts = {"Продажа": 0, "Аренда": 0, "Другое": 0}
    for L in lots:
        counts[L["deal"]] = counts.get(L["deal"], 0) + 1
    okn_count = sum(1 for L in lots if L.get("okn"))

    # sort: urgent first, then by deadline
    def sort_key(L):
        d = L["days_left"]
        if d is None:
            return (1, 9999)
        return (0 if d <= 3 else 1, d)

    lots_sorted = sorted(lots, key=sort_key)

    cards = []
    for L in lots_sorted:
        urgent = ""
        if L["days_left"] is not None:
            if L["days_left"] <= 0:
                urgent = '<span class="urgent">осталось 0 дн.</span>'
            elif L["days_left"] <= 3:
                urgent = f'<span class="urgent">осталось {L["days_left"]} дн.</span>'
            else:
                urgent = f'<span>осталось {L["days_left"]} дн.</span>'
        okn_span = '<span class="b okn" title="Объект культурного наследия">ОКН</span>' if L.get("okn") else ''
        search = f"{L['name']} {L['snip']} {L['nn']} {L['notice']}" + (" ОКН" if L.get("okn") else "")
        cards.append(f'''
<article class="lot" data-card data-cat="{L['deal']}" data-search="{esc(search)}">
  <div class="badges">
    {okn_span}<span class="b deal-{L['deal']}">{esc(L['deal'])}</span>
    <span class="b form">{esc(L['form'])}</span>
  </div>
  <h3>{esc(L['name'])}</h3>
  <p class="snip">{esc(L['snip'])}</p>
  <div><span class="price">{esc(L['price'])}</span></div>
  <div class="meta2"><span class="end">{esc(L['deadline'])}</span>{urgent}</div>
  <div class="foot">
    <a href="{esc(L['link'])}" target="_blank" rel="noopener">Портал торгов ↗</a>
    <span class="nn">{esc(L['nn'])}</span>
  </div>
</article>''')

    chips = ["Все", "Продажа", "Аренда", "Другое"]
    chip_html = "".join(
        f'<button type="button" class="chip{" on" if c=="Все" else ""}" data-filter="{c}">{c}</button>'
        for c in chips
    )

    okn_meta = f" · ОКН: {okn_count}" if okn_count else ""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Торги Костромской области — актуальные лоты | ЛОТ 44</title>
<meta name="description" content="Актуальные лоты продажи и аренды госимущества Костромской области. Данные torgi.gov.ru.">
<style>{CSS}</style>
</head>
<body>
<header class="hero">
  <div class="wrap">
    <div class="brandrow"><div class="l">ЛОТ <span class="n">44</span></div>
      <span style="color:#9fb0d0;font-size:14px">агрегатор торгов</span></div>
    <h1>Торги Костромской области — актуальные лоты</h1>
    <p>Продажа и аренда государственного и муниципального имущества, публичные предложения — одним списком.
       Данные: портал торгов <strong>torgi.gov.ru</strong>. Лоты-объекты культурного наследия отмечены значком <strong>ОКН</strong>.</p>
    <div class="meta">Обновлено: {esc(updated)} · активных лотов: {len(lots)}
      (Аренда: {counts.get('Аренда',0)} · Другое: {counts.get('Другое',0)} · Продажа: {counts.get('Продажа',0)}){okn_meta}
      · канал: <a href="https://vk.ru/lot44" target="_blank" rel="noopener">vk.ru/lot44</a></div>
  </div>
</header>
<div class="controls">
  <input type="search" id="q" placeholder="Поиск: объект, адрес, кадастровый номер, № извещения…" autocomplete="off">
  <div class="chips">{chip_html}</div>
  <span class="count" id="count">Показано: {len(lots)} из {len(lots)}</span>
</div>
<main>
  <div class="grid">
    {''.join(cards) if cards else '<div class="empty">Лоты не загружены. Попробуйте позже.</div>'}
  </div>
</main>
{footer_html()}
{JS_FILTER}
</body>
</html>
"""


def footer_html() -> str:
    return """
<footer>
  <div class="wrap" style="display:flex;flex-wrap:wrap;gap:24px;justify-content:space-between">
    <div style="flex:1;min-width:260px">
      <div class="brand">ЛОТ <span>44</span></div>
      Неофициальный агрегатор имущественных торгов Костромской области.<br>
      Данные: портал торгов torgi.gov.ru. Лоты, относящиеся к объектам культурного наследия,
      отмечены значком «ОКН». Не является офертой и юридической консультацией. Решения принимаете вы.
    </div>
    <div style="min-width:160px">
      <div style="color:#fff;font-weight:600;margin-bottom:8px">Канал</div>
      <a href="https://vk.ru/lot44" target="_blank" rel="noopener">vk.ru/lot44</a>
    </div>
  </div>
</footer>
"""


def esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main() -> int:
    SITE.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    updated = now_msk().strftime("%d.%m.%Y, %H:%M МСК")

    # --- торги ---
    lots = []
    total = None
    try:
        lots, total = fetch_torgi_lots()
    except Exception as e:
        print(f"[torgi] fatal: {e}", file=sys.stderr)
    complete = bool(lots) and (total is None or len(lots) >= int(total))
    if complete:
        save_cache("torgi.json", lots)
    elif lots:
        print("[torgi] сбор неполный (%s из %s) — кэш не трогаю" % (len(lots), total), file=sys.stderr)
    if not complete:
        cached = load_cache("torgi.json")
        if cached and (not lots or len(cached) > len(lots)):
            print("[torgi] использую кэш", len(cached))
            lots = cached
        elif not lots:
            print("[torgi] no data", file=sys.stderr)
        else:
            print("[torgi] кэша нет — оставляю неполный набор", len(lots), file=sys.stderr)

    (SITE / "index.html").write_text(render_torgi(lots, updated), encoding="utf-8")
    print(f"[ok] site/index.html ({len(lots)} lots)")
    print(f"[ok] updated {updated}")
    print(("STATUS: OK lots=%d" % len(lots)) if lots else "STATUS: EMPTY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
