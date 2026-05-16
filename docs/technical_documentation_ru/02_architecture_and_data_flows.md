# 3-5. Архитектура, структура и потоки данных

[<- К оглавлению](../TECHNICAL_DOCUMENTATION_RU.md)

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
