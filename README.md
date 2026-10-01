# ЛОТ 44 — автосборка и деплой

Ежедневное обновление витрины торгов + наследия Костромской области.

- **Торги** → `torgi.gov.ru` (API)
- **Наследие** → `наследие.дом.рф` (API)
- **Хостинг** → Netlify
- **Расписание** → GitHub Actions, каждый день **08:00 МСК**

---

## Быстрый старт (15–20 минут)

### 1. Создай репозиторий на GitHub

1. github.com → **New repository**
2. Имя: `lot44` (или любое)
3. Public или Private — на твой выбор
4. **Не** ставь галочки README/license (файлы уже есть)

### 2. Залей этот проект

На своём компьютере:

```bash
# скачай/распакуй папку lot44-auto, зайди в неё
cd lot44-auto

git init
git add .
git commit -m "init: LOT 44 auto build"
git branch -M main
git remote add origin https://github.com/ТВОЙ_ЛОГИН/lot44.git
git push -u origin main
```

### 3. Подключи Netlify

**Вариант A — через сайт (проще):**

1. [app.netlify.com](https://app.netlify.com) → Add new site → Import from Git → GitHub → выбери `lot44`
2. Build settings:
   - Build command: *(оставь пустым или `echo ok`)*
   - Publish directory: `site`
3. Deploy. Получишь ссылку вида `https://xxx.netlify.app`

**Вариант B — только токен (для Actions):**

1. Netlify → User settings → Applications → Personal access tokens → New
2. Скопируй токен
3. Netlify → Site settings → General → Site details → **Site ID** (скопируй)

### 4. Секреты для GitHub Actions

В репозитории GitHub:

**Settings → Secrets and variables → Actions → New repository secret**

| Имя | Значение |
|-----|----------|
| `NETLIFY_AUTH_TOKEN` | Personal access token из Netlify |
| `NETLIFY_SITE_ID` | Site ID сайта |

### 5. Проверь

1. GitHub → вкладка **Actions** → **Daily build & deploy** → **Run workflow**
2. Дождись зелёной галочки
3. Открой сайт — дата «Обновлено» должна быть сегодняшней

Дальше Actions сам запускается каждый день в 08:00 МСК.

---

## Локальный запуск

```bash
python3 scripts/build.py
# открой site/index.html в браузере
```

При недоступности API используются файлы из `data/` (кэш).

---

## Структура

```
lot44-auto/
├── .github/workflows/daily-build.yml   # cron 08:00 МСК
├── scripts/build.py                    # сборщик
├── site/                               # готовый HTML (деплой)
│   ├── index.html                      # торги
│   └── heritage.html                   # наследие
├── data/                               # кэш JSON
├── netlify.toml
└── README.md
```

---

## Если API torgi/наследие недоступны из GitHub

Actions крутятся в США/ЕС — иногда гос. API режут. Тогда:

1. Кэш в `data/` сохраняется после удачных сборок
2. Можно запускать `build.py` у себя (Россия) по Windows Task Scheduler и пушить `site/` + `data/` в репо
3. Netlify будет деплоить то, что в репозитории

---

## Связка с каналом ВК

После успешной сборки можно добавить шаг: генерация «Лотов дня» в `automation/out/`.  
Пока вручную: смотри свежие лоты на сайте → пост в vk.ru/lot44.

---

Личный просветительский проект. Не оферта.
