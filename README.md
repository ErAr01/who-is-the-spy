# Who Is The Spy (Telegram MVP)

MVP-бот для игры «Кто шпион» в Telegram:
- общий чат для лобби и голосования;
- личные сообщения для выдачи ролей/материалов;
- режимы: обычный, пустой шпион, кастомный.

## Возможности MVP

- `/newgame` — создать лобби (только в группе).
- Кнопка `Join` — присоединиться к игре.
- Выбор режима кнопками:
  - `Слова` — мирные и шпион получают разные слова;
  - `Пустой шпион` — мирные получают слово, шпион получает пустое задание;
  - `Кастом` — админ задаёт материал для мирных и шпиона (текст или фото).
- `/startgame` — запустить игру (минимум 3 игрока).
- `/vote` — открыть голосование.
- `/endvote` — завершить голосование и показать результат.
- `/cancel` — отменить активную игру.
- `/testpair` — в личке открыть тест-лобби: выбрать категории и сгенерировать раунд (карточки мирного и шпиона с Wikipedia и Google).

## Инструкция для пользователей: запуск и игра

### 1) Подготовка Telegram-бота

1. Создай бота через [@BotFather](https://t.me/BotFather) и получи токен.
2. Отключи privacy mode у бота (`/setprivacy -> Disable`), чтобы бот видел команды в группе.
3. Создай `.env`:

```bash
cp .env.example .env
```

4. Заполни минимум эти поля:

```env
BOT_TOKEN=123456:ABC...
LOG_LEVEL=INFO
```

### 2) Запуск приложения

#### Вариант A (рекомендуется): Docker Compose

Для Docker укажи в `.env`:

```env
REDIS_URL=redis://redis:6379/0
METRICS_ENABLED=true
METRICS_HOST=0.0.0.0
METRICS_PORT=8001
```

Запуск:

```bash
docker compose up --build
```

Для запуска вместе с observability-стеком (Prometheus + Loki + Promtail + Grafana):

```bash
docker compose --profile observability up -d --build
```

UI/эндпоинты:
- Grafana: `http://localhost:3000` (`GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`, по умолчанию `admin/admin`)
- Prometheus: `http://localhost:9090`
- Loki API: `http://localhost:3100`
- Метрики бота (внутри сети Docker): `http://bot:8001/metrics`

### Dashboard и alerts (provisioning)

После старта профиля `observability` автоматически поднимаются:
- Grafana dashboard: `Who Is The Spy - Game KPI & Runtime` (папка `Who Is The Spy`);
- Prometheus recording rules: `deploy/observability/prometheus/rules/game-observability-rules.yml`;
- Prometheus alerts:
  - `BotErrorRateSpike` — всплеск ошибок хендлеров;
  - `BotAnalyticsEventsSilence` — отсутствие analytics-событий;
  - `StartToFinishConversionDegraded` — деградация `start -> finish` conversion.

Интерпретация основных KPI:
- `Rounds / day`: `round_finished` за последние сутки.
- `Join -> Start conversion`: доля `game_started` от `player_joined` (за сутки).
- `Start -> Finish conversion`: доля `round_finished` от `game_started` (за 1d и 1h).
- `Average round duration / day`: средняя длительность раунда по `round_duration_seconds`.
- `Error rate by exception/handler`: доля исключений хендлеров (`handler_exception`) за 5 минут.

Метрики с approximation/proxy:
- `Unique users / day (estimated)` — оценка daily unique пользователей через hash-buckets (`analytics_actor_bucket_touches_total{actor_type="user"}`).
- `Unique group chats / day (estimated)` — аналогичная оценка для групповых чатов (`actor_type="group_chat"`).

Пороговые значения алертов (дефолт):
- всплеск ошибок: `error_rate > 5%` в течение `5m`;
- тишина событий: нет analytics events в окне `20m` (с `for: 10m`);
- деградация conversion: `start->finish < 70%` при `>=5` стартов за `1h` (с `for: 15m`).

Проверка конфигов:

```bash
# Проверка итогового docker compose
docker compose --profile observability config

# Проверка правил Prometheus (если promtool установлен локально)
promtool check rules deploy/observability/prometheus/rules/game-observability-rules.yml
promtool check config deploy/observability/prometheus/prometheus.yml
```

#### Вариант B: локально без Docker

Для локального запуска укажи в `.env`:

```env
REDIS_URL=redis://localhost:6379/0
METRICS_ENABLED=false
```

Подними Redis и запусти бота:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

### Опционально: self-hosted PostHog (заготовка)

В репозитории есть отдельный compose-шаблон для базового self-hosted PostHog:

```bash
docker compose -f deploy/observability/posthog/docker-compose.posthog.yml up -d
```

Это стартовая конфигурация для пилота/теста. Для production-нагрузки рекомендуется донастроить хранилища и параметры по официальной документации PostHog.

### 3) Как сыграть один раунд в Telegram

1. Добавь бота в групповой чат.
2. Каждый игрок один раз пишет боту в личку: `/start`.
3. Админ в группе запускает: `/newgame`.
4. Игроки нажимают `Join`.
5. Админ (опционально) выбирает категории в лобби.
6. Админ запускает раунд: `/startgame`.
7. Игроки получают карточки в личку и обсуждают в группе.
8. Админ запускает голосование: `/vote`.
9. Игроки голосуют кнопками.
10. Админ завершает голосование: `/endvote` (или оно завершится автоматически, когда проголосуют все).

### 4) Быстрая проверка контента в личке

- Команда `/testpair` открывает тест-лобби в личке:
  - выбор категорий,
  - генерация тестового раунда,
  - выдача карточек мирного и шпиона с ссылками Wikipedia и Google.

## Кастомный режим

Если выбран `Кастом`, после `/startgame` бот пишет админу в личку:
1. пришли материал для мирных (текст или фото);
2. пришли материал для шпиона того же типа (текст/текст или фото/фото).

После сохранения админ повторно запускает `/startgame` в группе.

## Контент

- Игровой контент берется из SQLite-базы разметки: `data/images/cards.db`.

## Ограничения MVP

- Нет истории и лидербордов.
- Нет таймеров раунда.
- Нет нескольких шпионов.
- Покрытие тестами пока базовое (сфокусировано на выборе пар и fallback-логике).

## Analytics events taxonomy

В проекте добавлен единый слой `analytics_event`, который сейчас пишет JSON-события в stdout.
Это базовый транспорт: позже можно добавить отдельные эмиттеры для PostHog и Prometheus без изменения хендлеров.

### Общая схема события

Обязательные поля:
- `event_name`
- `timestamp` (timezone-aware, ISO-8601)
- `payload` (`dict[str, Any]`, должен быть JSON-сериализуемым)

Опциональные поля:
- `chat_id`
- `user_id`
- `game_id`
- `round_id`

### Словарь событий

- `game_created`
- `game_started`
- `round_finished`
- `game_cancelled`
- `player_joined`
- `vote_cast`
- `category_toggled`
- `user_started_private`
- `role_delivery_failed`
- `content_selection_failed`
- `handler_exception`

### Что должно быть в payload

- `game_created`: `admin_id`, `players_count`, `available_categories_count`
- `game_started`: `players_count`, `delivered_count`, `failed_count`, `selected_categories`
- `round_finished`: `votes_count`, `voted_out_id`, `is_spy_caught`, `round_duration_seconds` (+ `auto_finished` при автозавершении)
- `game_cancelled`: `state_before_cancel`, `players_count`
- `player_joined`: `players_count`
- `vote_cast`: `target_id`, `votes_count`
- `category_toggled`: `category`, `selected_categories`
- `user_started_private`: `command`
- `role_delivery_failed`: `failed_user_ids`, `failed_count`
- `content_selection_failed`: `error`
- `handler_exception`: `exception_type`, `exception_message`, `handler_name`, `update_type`

## Card Labeling Service (CLI)

Сервис разметки карточек работает отдельно от игрового движка и хранит данные в `data/images/cards.db`.
Картинки сохраняются в SQLite как BLOB вместе с тегами внешности и embedding-вектором.

### Переменные окружения

Добавь в `.env`:

```env
OPENAI_API_KEY=sk-...
OPENAI_VISION_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
LABELING_DB_PATH=data/images/cards.db
IMAGE_EMBEDDING_DB_PATH=data/images/image_embeddings.db
IMAGE_EMBEDDING_PROVIDER=local_clip
LOCAL_CLIP_MODEL_NAME=openai/clip-vit-base-patch32
IMAGE_EMBEDDING_DEVICE=cpu
IMAGE_EMBEDDING_BATCH_SIZE=8
ENABLE_IMAGE_EMBEDDING_MATCHER=false
PAIR_SIMILARITY_THRESHOLD=0.55
PAIR_HISTORY_SIZE=50
PAIR_SELECTION_MODE=pairwise_topk
PAIR_SEED_RETRY_LIMIT=3
PAIR_LOGPROB_THRESHOLD=-2.3
```

`PAIR_SELECTION_MODE` поддерживает `pairwise_topk` (дефолт) и `seed_topk`.
Также поддерживаются алиасы `pairwise_logprob` и `seed_logprob` для совместимой миграции.
Если значение невалидное, автоматически используется `pairwise_topk`.

Проверка валидности пары выполняется через `logprob` по нормализованным score кандидатов.
`PAIR_LOGPROB_THRESHOLD` задает минимальный logprob (рекомендуемый безопасный дефолт `-2.3`).

### Базовые команды

```bash
python -m src.labeling.cli ingest --image ./samples/bruce.jpg --name "Bruce Willis"
python -m src.labeling.cli ingest-batch --dir ./samples
python -m src.labeling.cli list
python -m src.labeling.cli show --id bruce-willis
python -m src.labeling.cli pair
python -m src.labeling.cli relabel --id bruce-willis
python -m src.labeling.cli re-embed --all
python -m src.labeling.cli export-images --dir ./exported
python -m src.labeling.cli stats
python -m src.labeling.cli image-embed-ingest --image ./samples/bruce.jpg --id bruce-willis
python -m src.labeling.cli image-embed-ingest-batch --dir ./samples
python -m src.labeling.cli image-embed-list
```

Новые команды `image-embed-*` записывают эмбеддинги изображений в отдельную БД
`IMAGE_EMBEDDING_DB_PATH` и не меняют таблицы `cards/card_tags/pair_history`.
Для локального режима по умолчанию используется CLIP-модель (`IMAGE_EMBEDDING_PROVIDER=local_clip`).
Runtime-матчер по image embeddings включается отдельно через `ENABLE_IMAGE_EMBEDDING_MATCHER=true`,
по умолчанию игра продолжает работать через tag-based механику.

### Быстрый запуск image embeddings (local CLIP)

1. Подготовить зависимости:
   - `pip install -r requirements.txt`
   - `pip install torch transformers`
2. Проверить env:
   - `IMAGE_EMBEDDING_PROVIDER=local_clip`
   - `IMAGE_EMBEDDING_DB_PATH=data/images/image_embeddings.db`
   - `ENABLE_IMAGE_EMBEDDING_MATCHER=false` (на этапе заполнения БД).
3. Заполнить отдельную image DB:
   - `python -m src.labeling.cli image-embed-ingest --image ./samples/bruce.jpg --id bruce-willis --provider local_clip`
   - `python -m src.labeling.cli image-embed-ingest-batch --dir ./samples --provider local_clip`
4. Проверить результат:
   - `python -m src.labeling.cli image-embed-list`
   - `python -m src.labeling.cli image-embed-list --format json`
5. После заполнения включить runtime matcher:
   - `ENABLE_IMAGE_EMBEDDING_MATCHER=true` и перезапустить бот.

Важно:
- для `image-embed-*` `card_id` должен существовать в `LABELING_DB_PATH`;
- при ошибке про provider используйте только `local_clip` или `openai`.

### Формат sidecar JSON для batch ingest

Для `photo.jpg` можно положить `photo.json` рядом:

```json
{
  "name": "Bruce Willis",
  "wiki_url": "https://ru.wikipedia.org/wiki/Уиллис,_Брюс",
  "id": "bruce-willis"
}
```

Если sidecar отсутствует, `name` берётся из имени файла.
