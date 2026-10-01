#!/usr/bin/env python3
"""
ЛОТ 44 — сборщик витрины торгов + наследия Костромской области.
Запуск: python scripts/build.py
Выход:  site/index.html, site/heritage.html
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA = ROOT / "data"
MSK = timezone(timedelta(hours=3))

# --- API endpoints (публичные, без ключа) ---
TORGI_API = "https://torgi.gov.ru/new/api/public/lotcards/search"
# Костромская область в словаре ГИС Торги (dynSubjRF)
TORGI_REGION = "47"
HERITAGE_API = "https://xn--80aacb2b1a.xn--d1aqf.xn--p1ai/okn/api/objects"
# запасной (punycode/латиница может отличаться)
HERITAGE_API_ALT = "https://наследие.дом.рф/okn/api/objects"

UA = (
    "Mozilla/5.0 (compatible; LOT44Bot/1.0; +https://vk.ru/lot44) "
    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)


def now_msk() -> datetime:
    return datetime.now(MSK)


def http_get_json(url: str, params: dict | None = None, timeout: int = 45) -> Any:
    if params:
        from urllib.parse import urlencode
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
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

def fetch_torgi_lots() -> list[dict]:
    """Все активные лоты Костромской области с torgi.gov.ru."""
    lots: list[dict] = []
    page = 0
    size = 100
    while True:
        try:
            data = http_get_json(
                TORGI_API,
                {
                    "dynSubjRF": TORGI_REGION,
                    "page": page,
                    "size": size,
                    "sort": "applicationDeadline,asc",
                },
            )
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
            print(f"[torgi] API error page={page}: {e}", file=sys.stderr)
            break

        content = data.get("content") or data.get("list") or data.get("data") or []
        if not content and isinstance(data, list):
            content = data
        if not content:
            break

        for item in content:
            lots.append(normalize_torgi(item))

        total_pages = data.get("totalPages") or data.get("total_pages")
        if total_pages is not None:
            if page + 1 >= int(total_pages):
                break
        elif len(content) < size:
            break
        page += 1
        if page > 50:  # safety
            break

    print(f"[torgi] fetched {len(lots)} lots")
    return lots


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

    return {
        "id": str(lot_id),
        "notice": str(notice),
        "name": str(name)[:180],
        "snip": snip,
        "price": price_str,
        "price_raw": price,
        "deal": deal_label,
        "form": form[:60],
        "deadline": deadline_str,
        "days_left": days_left,
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


# ---------- НАСЛЕДИЕ ----------

def fetch_heritage() -> list[dict]:
    objects: list[dict] = []
    offset = 0
    limit = 100
    while True:
        params = {
            "regionCode": "44",
            "offset": offset,
            "limit": limit,
        }
        data = None
        for base in (HERITAGE_API, HERITAGE_API_ALT):
            try:
                data = http_get_json(base, params, timeout=40)
                break
            except Exception as e:
                print(f"[heritage] {base} failed: {e}", file=sys.stderr)
        if data is None:
            break

        items = (
            data.get("content")
            or data.get("items")
            or data.get("data")
            or data.get("objects")
            or []
        )
        if not items and isinstance(data, list):
            items = data
        if not items:
            break

        for it in items:
            objects.append(normalize_heritage(it))

        total = data.get("total") or data.get("totalElements") or data.get("count")
        offset += limit
        if total is not None and offset >= int(total):
            break
        if len(items) < limit:
            break
        if offset > 500:
            break

    print(f"[heritage] fetched {len(objects)} objects")
    return objects


def normalize_heritage(raw: dict) -> dict:
    oid = raw.get("id") or raw.get("objectId") or ""
    name = raw.get("name") or raw.get("title") or raw.get("objectName") or "Объект"
    address = raw.get("address") or raw.get("fullAddress") or raw.get("location") or ""
    status = (
        raw.get("statusName")
        or raw.get("investmentStatus")
        or raw.get("status")
        or "Решение отсутствует"
    )
    if isinstance(status, dict):
        status = status.get("name") or status.get("code") or "Решение отсутствует"
    status = map_heritage_status(str(status))

    otype = raw.get("typeName") or raw.get("objectType") or raw.get("type") or "Памятник"
    if isinstance(otype, dict):
        otype = otype.get("name") or "Памятник"

    area = raw.get("area") or raw.get("totalArea") or raw.get("square") or ""
    condition = raw.get("condition") or raw.get("technicalCondition") or raw.get("state") or ""
    if isinstance(condition, dict):
        condition = condition.get("name") or ""

    photo = (
        raw.get("photoUrl")
        or raw.get("imageUrl")
        or raw.get("mainPhoto")
        or ""
    )
    if photo and not str(photo).startswith("http"):
        # ресайзер ДОМ.РФ
        photo = (
            "https://наш.дом.рф/resizer/image"
            f"?imageUrl={photo}&systemClientId=okn-client&config=resize:fill:640:400"
        )

    # метки
    tags = []
    if raw.get("goldenRing") or raw.get("isGoldenRing"):
        tags.append("Золотое кольцо")
    if raw.get("supportPoint") or raw.get("isSupportPoint"):
        tags.append("Опорный пункт")

    slug = re.sub(r"[^\w\-]+", "-", str(name).lower())[:40]
    link = (
        raw.get("url")
        or f"https://наследие.дом.рф/объекты-культурного-наследия/"
        f"памятники-культурного-наследия/объект-{slug}-костромская-область-{oid}/"
    )

    return {
        "id": str(oid),
        "name": str(name)[:120],
        "address": str(address)[:160],
        "status": status,
        "type": str(otype)[:40],
        "area": str(area) if area else "",
        "condition": str(condition)[:40],
        "photo": str(photo) if photo else "",
        "tags": tags,
        "link": link,
    }


def map_heritage_status(s: str) -> str:
    s_low = s.lower()
    if "конкурс" in s_low or "объявлен" in s_low:
        return "Конкурс объявлен"
    if "подготов" in s_low:
        return "Подготовка к торгам"
    if "инвестор" in s_low or "найден" in s_low:
        return "Инвестор найден"
    return "Решение отсутствует"


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
.tabs{display:flex;gap:8px;margin-top:16px}
.tab{display:inline-block;padding:8px 18px;border-radius:999px;font-weight:700;font-size:14px;
     background:rgba(255,255,255,.12);color:#c8d3ea;text-decoration:none}
.tab.on{background:var(--amber);color:var(--navy)}
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
.lot img,.obj img{width:100%;height:180px;object-fit:cover;border-radius:10px;background:#e5e7eb}
.badges{display:flex;flex-wrap:wrap;gap:6px}
.b{font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;background:#eef2ff;color:#1d4ed8}
.b.deal-Продажа{background:#dcfce7;color:#047857}
.b.deal-Аренда{background:#dbeafe;color:#1d4ed8}
.b.deal-Другое{background:#f3f4f6;color:#4b5563}
.b.form{background:#f3f4f6;color:#374151}
.b.tag{background:#fef3c7;color:#92400e}
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


def render_torgi(lots: list[dict], updated: str) -> str:
    counts = {"Продажа": 0, "Аренда": 0, "Другое": 0}
    for L in lots:
        counts[L["deal"]] = counts.get(L["deal"], 0) + 1

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
                urgent = f'<span class="urgent">осталось 0 дн.</span>'
            elif L["days_left"] <= 3:
                urgent = f'<span class="urgent">осталось {L["days_left"]} дн.</span>'
            else:
                urgent = f'<span>осталось {L["days_left"]} дн.</span>'
        search = f"{L['name']} {L['snip']} {L['nn']} {L['notice']}"
        cards.append(f'''
<article class="lot" data-card data-cat="{L['deal']}" data-search="{esc(search)}">
  <div class="badges">
    <span class="b deal-{L['deal']}">{esc(L['deal'])}</span>
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
       Данные: портал торгов <strong>torgi.gov.ru</strong>.</p>
    <div class="tabs">
      <a class="tab on" href="index.html">Торги</a>
      <a class="tab" href="heritage.html">Наследие</a>
    </div>
    <div class="meta">Обновлено: {esc(updated)} · активных лотов: {len(lots)}
      (Аренда: {counts.get('Аренда',0)} · Другое: {counts.get('Другое',0)} · Продажа: {counts.get('Продажа',0)})
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


def render_heritage(objs: list[dict], updated: str) -> str:
    status_order = ["Конкурс объявлен", "Подготовка к торгам", "Инвестор найден", "Решение отсутствует"]
    counts = {s: 0 for s in status_order}
    for o in objs:
        counts[o["status"]] = counts.get(o["status"], 0) + 1

    cards = []
    for o in objs:
        tags = "".join(f'<span class="b tag">{esc(t)}</span>' for t in o["tags"])
        photo = f'<img src="{esc(o["photo"])}" alt="" loading="lazy">' if o["photo"] else ""
        area = f'{esc(o["area"])} м²' if o["area"] else ""
        cond = f'состояние: {esc(o["condition"])}' if o["condition"] else ""
        meta_line = " · ".join(x for x in [area, cond] if x)
        search = f"{o['name']} {o['address']} {o['id']}"
        cards.append(f'''
<article class="obj" data-card data-cat="{esc(o['status'])}" data-search="{esc(search)}">
  {photo}
  <div class="badges">
    <span class="b">{esc(o['status'])}</span>
    <span class="b form">{esc(o['type'])}</span>
    {tags}
  </div>
  <h3>{esc(o['name'])}</h3>
  <p class="snip">{esc(o['address'])}</p>
  <p class="snip">{meta_line}</p>
  <div class="foot">
    <a href="{esc(o['link'])}" target="_blank" rel="noopener">Карточка на ДОМ.РФ ↗</a>
    <span class="nn">ID {esc(o['id'])}</span>
  </div>
</article>''')

    chips = ["Все"] + status_order
    chip_html = "".join(
        f'<button type="button" class="chip{" on" if c=="Все" else ""}" data-filter="{c}">{c}</button>'
        for c in chips
    )
    stats = " · ".join(f"{s}: {counts.get(s,0)}" for s in status_order)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Наследие Костромской области — объекты для инвесторов | ЛОТ 44</title>
<meta name="description" content="Объекты культурного наследия Костромской области: статус, состояние, площадь. Данные наследие.дом.рф.">
<style>{CSS}</style>
</head>
<body>
<header class="hero">
  <div class="wrap">
    <div class="brandrow"><div class="l">ЛОТ <span class="n">44</span></div>
      <span style="color:#9fb0d0;font-size:14px">агрегатор</span></div>
    <h1>Наследие Костромской области — объекты для инвесторов</h1>
    <p>Объекты культурного наследия региона: статус, состояние, площадь.
       Данные: платформа «Наследие» ДОМ.РФ.</p>
    <div class="tabs">
      <a class="tab" href="index.html">Торги</a>
      <a class="tab on" href="heritage.html">Наследие</a>
    </div>
    <div class="meta">Обновлено: {esc(updated)} · объектов: {len(objs)} ({stats})
      · канал: <a href="https://vk.ru/lot44" target="_blank" rel="noopener">vk.ru/lot44</a></div>
  </div>
</header>
<div class="controls">
  <input type="search" id="q" placeholder="Поиск: название, адрес…" autocomplete="off">
  <div class="chips">{chip_html}</div>
  <span class="count" id="count">Показано: {len(objs)} из {len(objs)}</span>
</div>
<main>
  <div class="grid">
    {''.join(cards) if cards else '<div class="empty">Объекты не загружены.</div>'}
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
      Неофициальный агрегатор торгов и объектов культурного наследия Костромской области.<br>
      Данные: torgi.gov.ru и платформа «Наследие» ДОМ.РФ.
      Не является офертой и юридической консультацией. Решения принимаете вы.
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
    try:
        lots = fetch_torgi_lots()
        if lots:
            save_cache("torgi.json", lots)
    except Exception as e:
        print(f"[torgi] fatal: {e}", file=sys.stderr)
    if not lots:
        cached = load_cache("torgi.json")
        if cached:
            print("[torgi] using cache", len(cached))
            lots = cached
        else:
            print("[torgi] no data", file=sys.stderr)

    # --- наследие ---
    objs = []
    try:
        objs = fetch_heritage()
        if objs:
            save_cache("heritage.json", objs)
    except Exception as e:
        print(f"[heritage] fatal: {e}", file=sys.stderr)
    if not objs:
        cached = load_cache("heritage.json")
        if cached:
            print("[heritage] using cache", len(cached))
            objs = cached

    (SITE / "index.html").write_text(render_torgi(lots, updated), encoding="utf-8")
    (SITE / "heritage.html").write_text(render_heritage(objs, updated), encoding="utf-8")
    print(f"[ok] site/index.html ({len(lots)} lots), site/heritage.html ({len(objs)} objs)")
    print(f"[ok] updated {updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
