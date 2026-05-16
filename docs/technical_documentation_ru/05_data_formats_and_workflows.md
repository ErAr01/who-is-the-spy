# 9-10. Форматы данных и типичный workflow

[<- К оглавлению](../TECHNICAL_DOCUMENTATION_RU.md)

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

### 10.4 Заполнение отдельной БД image embeddings (local CLIP)

Цель: просчитать image embeddings и сохранить их в отдельную БД `IMAGE_EMBEDDING_DB_PATH`, не меняя legacy-таблицы.

1. Проверить env-конфигурацию:
   - `IMAGE_EMBEDDING_PROVIDER=local_clip`
   - `IMAGE_EMBEDDING_DB_PATH=data/images/image_embeddings.db`
   - `ENABLE_IMAGE_EMBEDDING_MATCHER=false` (если пока только готовим данные).
2. Подготовить зависимости local CLIP:
   - `pip install torch transformers`
3. Убедиться, что карточки уже существуют в `LABELING_DB_PATH`:
   - `python -m src.labeling.cli list`
4. Выполнить первичную загрузку:
   - одна карточка:
     - `python -m src.labeling.cli image-embed-ingest --image ./samples/bruce.jpg --id bruce-willis --provider local_clip`
   - пакетно (имя файла должно совпадать с `card_id`):
     - `python -m src.labeling.cli image-embed-ingest-batch --dir ./samples --provider local_clip`
5. При необходимости пересчитать конкретную запись:
   - `python -m src.labeling.cli image-embed-reembed --image ./samples/bruce.jpg --id bruce-willis --provider local_clip`
6. Проверить наполнение image DB:
   - `python -m src.labeling.cli image-embed-list`
   - `python -m src.labeling.cli image-embed-list --format json`
7. Включить runtime matcher, когда БД заполнена:
   - `ENABLE_IMAGE_EMBEDDING_MATCHER=true`
   - перезапустить бот/процесс после изменения `.env`.

#### Готовый набор команд (copy-paste)

```bash
# 0) Из корня проекта
cd /Users/artemermilov/PycharmProjects/who_is_the_spy

# 1) Поднять окружение и зависимости
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2) Подготовить .env (если еще нет)
cp .env.example .env

# 3) Настроить CLIP-контур в текущей shell-сессии
export PYTHONPATH=.
export IMAGE_EMBEDDING_PROVIDER=local_clip
export IMAGE_EMBEDDING_DB_PATH=data/images/image_embeddings.db
export LOCAL_CLIP_MODEL_NAME=openai/clip-vit-base-patch32
export IMAGE_EMBEDDING_DEVICE=cpu
export ENABLE_IMAGE_EMBEDDING_MATCHER=false

# 4) Просчет эмбеддинга для одной картинки
# Важно: --id должен существовать в legacy БД cards.db
python -m src.labeling.cli image-embed-ingest \
  --image ./samples/bruce.jpg \
  --id bruce-willis \
  --provider local_clip

# 5) Пакетный просчет по папке
# card_id берется из имени файла (stem)
python -m src.labeling.cli image-embed-ingest-batch \
  --dir ./samples \
  --provider local_clip

# 6) Принудительный пересчет для конкретной картинки
python -m src.labeling.cli image-embed-reembed \
  --image ./samples/bruce.jpg \
  --id bruce-willis \
  --provider local_clip

# 7) Проверка наполнения image-embedding БД
python -m src.labeling.cli image-embed-list
python -m src.labeling.cli image-embed-list --format json
```
