# Техническая документация проекта Who Is The Spy

## 1. Назначение проекта

`Who Is The Spy` — Telegram-бот для игры "Кто шпион", где:
- игровой цикл идет в групповом чате (лобби, запуск раунда, голосование);
- персональные роли и карточки отправляются игрокам в личные сообщения;
- контент персонажей берется из локальной SQLite-базы с разметкой изображений.

Дополнительно в репозитории есть отдельный CLI-сервис разметки карточек (`src/labeling/cli.py`), который:
- ingest-ит изображения в базу;
- вызывает OpenAI для тегирования внешности и построения embeddings;
- подбирает пары персонажей;
- экспортирует изображения и статистику.

## 2. Сценарии использования

### 2.1 Основной игровой сценарий
- Игроки пишут боту в личку `/start` (иначе не смогут нажать `Join` в группе).
- Админ группы запускает `/newgame`.
- Игроки нажимают кнопку `Join`.
- Админ при необходимости выбирает категории.
- Админ запускает `/startgame`.
- Бот рассылает карточки в личку, затем в группе идет обсуждение.
- Админ запускает `/vote`, затем `/endvote` (или голосование завершается автоматически, если проголосовали все).

### 2.2 Подготовка/поддержка контента
- Разработчик/контент-менеджер запускает команды `python -m src.labeling.cli ...`.
- Данные пишутся в `LABELING_DB_PATH` (по умолчанию `data/images/cards.db`).
- Эта же БД используется игровым `ContentProvider` при выборе пары персонажей.

### 2.3 Тестовый сценарий в личке
- Команда `/testpair` в личке запускает тест-лобби.
- Можно переключать категории и сгенерировать тестовую пару (мирный + шпион) без группового чата.

## 3. Архитектура

### 3.1 Высокоуровневая схема

Система разделена на 2 подсистемы:
1. **Game Bot Runtime** (`src/main.py` + `handlers` + `game` + Redis/FSM).
2. **Labeling Service** (`src/labeling/*` + SQLite + OpenAI).

### 3.2 Слои и зависимости

1. **Конфигурация**
   - `src/config.py` (`Settings`, `get_settings()`).
   - Читает `.env` через `pydantic-settings`.

2. **Инфраструктура приложения**
   - `src/bot.py`: создание `Bot`, `Dispatcher`, Redis-клиентов и FSM storage.
   - `src/main.py`: подключение роутеров и запуск polling.

3. **Прикладная логика игры**
   - `src/handlers/group.py`: групповые команды `/newgame`, `/startgame`, `/vote`, `/endvote`, `/cancel`.
   - `src/handlers/private.py`: `/start`, `/help`, `/testpair`, обработка приватного test-lobby.
   - `src/handlers/callbacks.py`: callback-кнопки `join`, `category`, `vote`.
   - `src/game/engine.py`: подготовка раунда, рассылка ролей, подсчет голосования.
   - `src/game/content.py`: выбор пары из БД на базе тегов/истории.
   - `src/game/repo.py`: хранение текущей игры в Redis.
   - `src/game/models.py`: доменные сущности (`Game`, `Player`, `GameState`, `GameMode`).

4. **Сервис разметки**
   - `src/labeling/cli.py`: CLI-команды.
   - `src/labeling/pipeline.py`: ingest/relabel/re-embed pipeline.
   - `src/labeling/storage.py`: SQLite-слой (`cards`, `card_tags`, `pair_history`).
   - `src/labeling/llm/openai_tagger.py`: интеграция с OpenAI (vision + embeddings).
   - `src/labeling/models.py`, `src/labeling/taxonomy.py`: схемы тегов и доменные модели.
   - `src/labeling/similarity.py`: косинусная похожесть и выбор пары.

### 3.3 Ключевые внешние зависимости

- `aiogram` — Telegram bot framework.
- `redis` — state/game persistence.
- `pydantic-settings` — конфигурация из окружения.
- `openai` — разметка изображения и embeddings.
- `pillow` — нормализация изображений.
- `typer` — CLI.
- `numpy` — работа с embedding-векторами.
- `matplotlib` — визуализация embeddings (опционально, для `plot-embeddings`).

## 4. Структура директорий и ключевых файлов

- `src/main.py` — точка входа Python-процесса бота.
- `src/bot.py` — сборка app context.
- `src/config.py` — все env-переменные и их default.
- `src/handlers/` — Telegram handlers и callbacks.
- `src/game/` — игровая модель, engine, контент-провайдер, repo.
- `src/fsm/states.py` — FSM-состояния для приватных сценариев.
- `src/utils/keyboards.py` — инлайн-клавиатуры.
- `src/labeling/` — сервис разметки изображений и CLI.
- `data/images/` — SQLite-БД и визуализации embeddings.
- `docker-compose.yml` — запуск `redis` + `bot`.
- `requirements.txt` — Python-зависимости.
- `README.md` — пользовательское описание.
- `PRODUCTION_RUNBOOK.md` — эксплуатационный runbook.

## 5. End-to-end поток данных

### 5.1 Поток игры (группа + личка)

1. Пользователь пишет `/start` в личку -> `GameRepo.set_user_started(user_id)`.
2. Админ в группе вызывает `/newgame`:
   - создается `Game` (state=`LOBBY`, mode=`IMAGE_DB`);
   - игра сохраняется в Redis (`game:{chat_id}`).
3. Игроки жмут `Join`:
   - callback проверяет `user_started:{user_id}` в Redis;
   - добавляет `Player` в `game.players`.
4. `/startgame`:
   - `ContentProvider.get_random_image_pair(..., chat_id=game.chat_id)` выбирает пару из SQLite;
   - для `IMAGE_DB` в групповом чате включен anti-repeat TTL 24 часа по `chat_id`;
   - если в окне TTL нет доступных кандидатов, выбирается самая ранняя доступная пара в этом чате;
   - `prepare_game_round` определяет шпиона, формирует speaking order, кладет payload;
   - `send_roles` отправляет фото+caption в лички.
5. `/vote` открывает голосование (`state=VOTING`), показывает клавиатуру.
6. Голоса пишутся в `game.votes` через callback `vote:*`.
7. `finish_voting` считает результат, определяет победителя, завершает игру.

### 5.2 Поток разметки (CLI -> БД)

1. CLI берет изображение (`ingest`/`ingest-batch`).
2. `LabelingStorage.normalize_image`:
   - конвертирует в JPEG RGB;
   - делает full (до 1024x1024) и thumbnail (до 256x256).
3. SHA256 normalized image -> дедупликация (`image_sha256` UNIQUE).
4. `OpenAITagger.tag_image` -> `CardTags` JSON.
5. `build_appearance_text` строит текстовое описание.
6. `embed_text` генерирует embedding-вектор.
7. `save_card` записывает `cards` + `card_tags`, обновляет timestamp.
8. Игровой `ContentProvider` читает эти же записи для подбора пар.

## 6. Подробная документация CLI (`src/labeling/cli.py`)

Запуск:
- `python -m src.labeling.cli --help`
- `python -m src.labeling.cli <command> --help`

> Важно: команды, использующие LLM (`ingest`, `ingest-batch`, `relabel`, `re-embed`), требуют `OPENAI_API_KEY`.

### 6.1 `ingest`

Добавляет одну карточку.

Параметры:
- `--image PATH` (обязательный): путь к изображению.
- `--name TEXT` (обязательный): отображаемое имя.
- `--wiki TEXT` (опционально): URL Wikipedia.
- `--id TEXT` (опционально): card id (иначе slug от `name`).
- `--category TEXT` (повторяемый): dataset category.
- `--force` (флаг): перезаписать при дубле sha256.

Пример:
- `python -m src.labeling.cli ingest --image ./samples/bruce.jpg --name "Bruce Willis" --category movies_series`

### 6.2 `ingest-batch`

Пакетная загрузка изображений из каталога.

Параметры:
- `--dir PATH` (обязательный): папка с изображениями.
- `--category TEXT` (повторяемый): категории по умолчанию для batch.
- `--force` (флаг): принудительная перезапись.

Поддерживаемые расширения: `.jpg`, `.jpeg`, `.png`, `.webp`.

Sidecar `photo.json` (опционально, рядом с `photo.jpg`):
```json
{
  "name": "Bruce Willis",
  "wiki_url": "https://ru.wikipedia.org/wiki/Уиллис,_Брюс",
  "id": "bruce-willis",
  "categories": ["movies_series", "adult"]
}
```

Пример:
- `python -m src.labeling.cli ingest-batch --dir ./samples --category adult`

### 6.3 `relabel`

Перегенерирует теги карточки через vision model.

Параметры:
- `--id TEXT`: конкретная карточка.
- `--all` (флаг): все карточки.
- `--vision-model TEXT` (опционально): override модели vision.

Ограничение: нужно передать либо `--id`, либо `--all`, иначе ошибка `BadParameter`.

### 6.4 `re-embed`

Перегенерирует embedding по текущему `appearance_text`.

Параметры:
- `--id TEXT`: конкретная карточка.
- `--all` (флаг): все карточки.

### 6.5 `list`

Список карточек.

Параметры:
- `--format [table|json]` (default: `table`).
- `--filter key=value` (опционально).

Особенность:
- для `dataset_category` фильтрация идет по `card.dataset_categories`;
- для остальных ключей фильтр пытается матчить и поля `card.tags`, и поля `CardRecord`.

### 6.6 `show`

Показывает одну карточку JSON + размеры бинарных полей.

Параметры:
- `--id TEXT` (обязательный).

### 6.7 `pair`

Подбирает пару через `PairSelector`.

Параметры:
- `--seed-id TEXT` (опционально): фиксировать seed card.

Учитываются:
- `PAIR_SIMILARITY_THRESHOLD`;
- `PAIR_HISTORY_SIZE`.
- `PAIR_SELECTION_MODE` (`pairwise_topk`/`seed_topk`, плюс алиасы `pairwise_logprob`/`seed_logprob`).
- `PAIR_SEED_RETRY_LIMIT` (количество попыток выбора seed до fallback).
- `PAIR_LOGPROB_THRESHOLD` (минимальный logprob для валидации пары; дефолт `-2.3`).

### 6.8 `export-images`

Экспорт изображений из БД в директорию.

Параметры:
- `--dir PATH` (обязательный): куда писать `.jpg`.
- `--ids id1,id2,...` (опционально): фильтр по id.

### 6.9 `stats`

Считает top-20 частых tag values.

Вывод:
- `cards=<n>`;
- далее пары `tag:value -> count`.

### 6.10 `plot-embeddings`

Строит PCA 2D scatter plot embeddings.

Параметры:
- `--out PATH` (default `data/images/embeddings_2d.png`).
- `--category TEXT` (повторяемый): фильтр категорий.
- `--with-labels` (флаг): подписи имён на графике.

Ошибки:
- если нет `matplotlib` -> `BadParameter`;
- если <2 карточек/векторов -> `BadParameter`.

## 7. Конфигурация окружения (.env)

Источники:
- фактический набор переменных задан в `src/config.py`;
- шаблон находится в `.env.example`.

### 7.1 Переменные

- `BOT_TOKEN` (обязательная): токен Telegram-бота.
  - Используется в `src/bot.py` при создании `Bot`.
- `REDIS_URL` (default `redis://localhost:6379/0`):
  - Используется в `src/bot.py` для game repo и FSM storage.
- `LOG_LEVEL` (default `INFO`):
  - Используется в `src/main.py` для `logging.basicConfig`.
- `OPENAI_API_KEY` (опциональная на уровне settings, но практически обязательна для labeling CLI):
  - Используется в `src/labeling/cli.py` при создании `OpenAITagger`.
- `OPENAI_VISION_MODEL` (default `gpt-4o-mini`):
  - `src/labeling/cli.py` -> `OpenAITagger.vision_model`.
- `OPENAI_EMBEDDING_MODEL` (default `text-embedding-3-small`):
  - `src/labeling/cli.py` -> `OpenAITagger.embedding_model`.
- `LABELING_DB_PATH` (default `data/images/cards.db`):
  - Используется в `group/private handlers` и в labeling storage.
- `PAIR_SIMILARITY_THRESHOLD` (default `0.55`):
  - Используется в CLI `pair`.
- `PAIR_HISTORY_SIZE` (default `50`):
  - Используется в `ContentProvider` и CLI `pair`.
- `PAIR_SELECTION_MODE` (default `pairwise_topk`):
  - Используется в `ContentProvider` (group/private handlers) и CLI `pair`.
  - Поддерживает `pairwise_topk`/`seed_topk` и алиасы `pairwise_logprob`/`seed_logprob`.
  - Невалидные значения автоматически переводятся в `pairwise_topk`.
- `PAIR_SEED_RETRY_LIMIT` (default `3`):
  - Используется в `ContentProvider` и CLI `pair` для `seed_topk`.
- `PAIR_LOGPROB_THRESHOLD` (default `-2.3`):
  - Используется в `ContentProvider` и CLI `pair` для logprob-валидации кандидатов.

### 7.2 Безопасность

- В `.env` содержатся чувствительные данные (токены/API keys).
- Не коммитить `.env` в VCS.
- При утечке токена/API key нужно выполнить ротацию у провайдера.

## 8. Установка и локальный запуск

## 8.1 Вариант A: Docker Compose

1. Создать `.env` по `.env.example`.
2. Для Docker указать `REDIS_URL=redis://redis:6379/0`.
3. Запустить:
   - `docker compose up --build`

Что поднимается:
- `redis` (`redis:7-alpine`);
- `bot` (`python:3.12-slim`, команда: установка requirements + `python -m src.main`).

## 8.2 Вариант B: локально без Docker

1. Создать venv и установить зависимости:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Поднять Redis локально.
3. Указать в `.env`:
   - `REDIS_URL=redis://localhost:6379/0`
4. Запустить:
   - `python -m src.main`

## 8.3 Локальный запуск labeling CLI

Требуется:
- доступ к `LABELING_DB_PATH`;
- `OPENAI_API_KEY` для LLM-команд.

Пример smoke:
- `python -m src.labeling.cli list`
- `python -m src.labeling.cli stats`

## 9. Форматы входных и выходных данных

### 9.1 Входы Telegram-бота

- Group commands: `/newgame`, `/startgame`, `/vote`, `/endvote`, `/cancel`.
- Private commands: `/start`, `/help`, `/testpair`.
- Callback data:
  - `join:{chat_id}`
  - `category:{chat_id}:{category}`
  - `vote:{chat_id}:{target_id}`
  - `testround:*`

### 9.2 Входы labeling CLI

- Изображения: `.jpg/.jpeg/.png/.webp`.
- Sidecar JSON в batch (см. раздел CLI).

### 9.3 SQLite-структура (`LabelingStorage.init_db`)

Таблицы:
- `cards`: карточка + BLOB изображения/thumbnail + JSON tags + embedding.
- `card_tags`: нормализованные теги (`card_id`, `category`, `value`).
- `pair_history`: история использованных пар (для анти-повторов).
  - Поля: `used_at`, `card_a`, `card_b`, `chat_id`.
  - Scope истории: по `chat_id` (общая история для каждого группового чата).
  - Нормализация пары: `(A,B)` и `(B,A)` сохраняются как одна и та же пара.
  - Для группового `IMAGE_DB` используется TTL-фильтр 24 часа.

### 9.4 Выходы

- В Telegram: тексты/кнопки в group, фото и подписи в private.
- В CLI: строковый вывод, JSON (`list --format json`, `show`), экспорт `.jpg`, PNG-график embeddings.

## 10. Типичный workflow (пошагово)

### 10.1 Подготовка контента

1. `python -m src.labeling.cli ingest-batch --dir ./samples --category movies_series`
2. Проверка:
   - `python -m src.labeling.cli list`
   - `python -m src.labeling.cli stats`
3. Опционально:
   - `python -m src.labeling.cli plot-embeddings --out data/images/embeddings_2d.png`

### 10.2 Запуск игры

1. Запустить бот (`docker compose up --build` или локально).
2. Каждый игрок пишет `/start` в личку бота.
3. В группе:
   - `/newgame`
   - `Join`
   - `/startgame`
   - `/vote`
   - `/endvote`

### 10.3 Операционное сопровождение

- Логи: `docker compose logs -f bot`
- Перезапуск: `docker compose restart bot`
- Бэкап БД: `cp data/images/cards.db data/images/cards.db.backup.<timestamp>`

## 11. Обработка ошибок и ограничения

### 11.1 Обработка ошибок (реализовано)

- `startgame`:
  - проверка администратора;
  - минимум 3 игрока;
  - перехват ошибок подбора пары (`ValueError` из `ContentProvider`).
- `send_roles`:
  - перехват `TelegramForbiddenError` (игрок не открыл личку бота/заблокировал).
- Callback `vote`:
  - проверка участника;
  - проверка валидности target.
- CLI:
  - `BadParameter` при некорректных аргументах;
  - обработка ошибок по каждому файлу в `ingest-batch`.
- OpenAI:
  - retry на rate limit в `openai_tagger.py` (до 8 попыток).

### 11.2 Ограничения/расхождения (подтверждено кодом)

- В коде реально используется только `GameMode.IMAGE_DB` (остальные enum-режимы не задействованы в runtime).
- Обработчики `CustomSetup` присутствуют, но в текущем коде не найдена точка, где FSM переводится в `CustomSetup.waiting_civilian_payload`; значит полный сценарий "кастом" в runtime не активируется автоматически.
- Автотесты проекта в `src` не найдены.
- Нет миграций БД (schema эволюция вручную).
- Нет отдельного healthcheck endpoint (бот работает через long polling).

## 12. Для разработчиков: как расширять проект

### 12.1 Добавление новой команды бота

1. Создать handler в `src/handlers/group.py` или `src/handlers/private.py`.
2. Добавить кнопки в `src/utils/keyboards.py` при необходимости.
3. Обновить `src/handlers/callbacks.py`, если есть callback-логика.
4. Убедиться, что `router` уже подключен в `src/main.py` (или подключить новый).

### 12.2 Добавление нового источника/логики контента

1. Расширять `src/game/content.py` (новая стратегия выбора пары/источник данных).
2. При необходимости добавить новый storage/repository слой.
3. Сохранять совместимость с контрактом:
   - `get_random_image_pair(...)`;
   - `get_image_bytes(card_id)`.

### 12.3 Добавление новых тегов/моделей разметки

1. Расширить enum/категории в `src/labeling/taxonomy.py`.
2. Обновить `CardTags` в `src/labeling/models.py`.
3. Проверить генерацию schema и strict JSON в `openai_tagger.py`.
4. Актуализировать формирование `appearance_text`.
5. Проверить сохранение/чтение в `LabelingStorage`.

### 12.4 Добавление новой CLI-команды

1. Добавить функцию с `@app.command(...)` в `src/labeling/cli.py`.
2. Использовать `_storage()` или `_pipeline()` по необходимости.
3. Добавить секцию в данную документацию и в `README.md`.

### 12.5 Практики развития

- Писать отдельные тесты (минимум smoke на handlers/content/pipeline).
- Добавить pre-commit/линтеры (в репозитории не найдено явной конфигурации линтера).
- Разделить runtime-конфиг для `dev/prod` (сейчас через `.env` и defaults).

## 13. Тестирование и проверка качества

На текущий момент:
- добавлены тесты парсинга режима `PAIR_SELECTION_MODE`;
- добавлены тесты seed anti-repeat весов и retry/fallback цепочки в `ContentProvider`;
- добавлены тесты chat-scoped TTL (24h) и fallback на самую раннюю пару;
- добавлен тест нормализации/TTL/chat-scope для `pair_history` в `LabelingStorage`;
- ручная проверка Telegram/CLI остается полезной как smoke.

Рекомендуемый минимальный набор проверок:
1. `python -m src.labeling.cli list` (доступ к БД).
2. `python -m src.labeling.cli pair` (работает similarity logic).
3. `/start` в личке, `/newgame` + `Join` + `/startgame` в группе.
4. `/vote` + голосование кнопками + `/endvote`.

## 14. Troubleshooting / FAQ

### Q1. Ошибка `OPENAI_API_KEY is required for labeling commands`
Причина: не задан `OPENAI_API_KEY`.
Решение: заполнить переменную в `.env`.

### Q2. `/startgame` отвечает "Нужно минимум 3 игрока"
Причина: недостаточно участников в `game.players`.
Решение: игроки должны открыть личку бота (`/start`) и нажать `Join`.

### Q3. "Не удалось отправить роли..."
Причина: бот не может писать игрокам в личку (`TelegramForbiddenError`).
Решение: каждый игрок должен начать диалог с ботом в личке и не блокировать его.

### Q4. `Недостаточно карточек в выбранных категориях`
Причина: в `LABELING_DB_PATH` мало данных по выбранным категориям.
Решение: добавить карточки через `ingest`/`ingest-batch` или ослабить фильтр категорий.

### Q5. Rate limit/OpenAI ошибки в batch
Причина: лимиты внешнего API.
Решение: повторить позже, уменьшить интенсивность, при необходимости сменить модель/план API.

### Q6. Бот в Docker не подключается к Redis
Проверить:
- `REDIS_URL=redis://redis:6379/0` в `.env` для docker-compose;
- статус контейнера `redis` (`docker compose ps`).

## 15. Что не найдено / не реализовано

- Не найдены миграции БД.
- Не найден отдельный механизм переключения runtime в `GameMode.WORDS/BLANK/CUSTOM` (в текущем потоке используется `IMAGE_DB`).
- Не найден endpoint для health checks.

---

Документ подготовлен по текущему состоянию кода в репозитории (модули `src/*`, конфигурация, CLI, docker/runbook), без предположений о несуществующих функциях.
