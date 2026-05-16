# 7-8. Конфигурация окружения и запуск

[<- К оглавлению](../TECHNICAL_DOCUMENTATION_RU.md)

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
- `IMAGE_EMBEDDING_DB_PATH` (default `data/images/image_embeddings.db`):
  - Используется отдельным image-embedding pipeline/storage (`src/labeling/image_embedding_*`).
- `IMAGE_EMBEDDING_PROVIDER` (default `local_clip`):
  - Выбор провайдера image embeddings (`local_clip` или `openai`) для CLI-команд `image-embed-*`.
- `LOCAL_CLIP_MODEL_NAME` (default `openai/clip-vit-base-patch32`):
  - Локальная CLIP-модель для `LocalClipImageEmbeddingProvider`.
- `IMAGE_EMBEDDING_DEVICE` (default `cpu`):
  - Устройство инференса для локального CLIP (`cpu`, `mps`, `cuda`).
- `IMAGE_EMBEDDING_BATCH_SIZE` (default `8`):
  - Размер batch для image-embedding сценариев.
- `ENABLE_IMAGE_EMBEDDING_MATCHER` (default `false`):
  - Включает runtime-подбор пары через image embeddings; при `false` используется legacy tag-based путь.
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

### 7.3 Переменные image-embedding контура

Минимальный набор для локального CLIP:

```env
LABELING_DB_PATH=data/images/cards.db
IMAGE_EMBEDDING_DB_PATH=data/images/image_embeddings.db
IMAGE_EMBEDDING_PROVIDER=local_clip
LOCAL_CLIP_MODEL_NAME=openai/clip-vit-base-patch32
IMAGE_EMBEDDING_DEVICE=cpu
IMAGE_EMBEDDING_BATCH_SIZE=8
ENABLE_IMAGE_EMBEDDING_MATCHER=false
```

Пояснения:
- `LABELING_DB_PATH` — legacy БД карточек, где `card_id` должен уже существовать.
- `IMAGE_EMBEDDING_DB_PATH` — отдельная БД с image embeddings (не смешивается с `cards/card_tags/pair_history`).
- `IMAGE_EMBEDDING_PROVIDER` — провайдер для `image-embed-*` команд (`local_clip` или `openai`).
- `ENABLE_IMAGE_EMBEDDING_MATCHER` — feature flag runtime-подбора пары:
  - `false` (по умолчанию): работает legacy tag-based matcher;
  - `true`: включается image-embedding matcher в runtime.

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

## 8.4 Подготовка окружения для local CLIP

1. Создать/активировать venv:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Установить базовые зависимости проекта:
   - `pip install -r requirements.txt`
3. Убедиться, что доступны зависимости локального CLIP:
   - `pip install torch transformers`
4. Проверить провайдер и доступность модели:
   - `python -m src.labeling.cli image-embed-ingest --image ./samples/bruce.jpg --id bruce-willis --provider local_clip`

Примечания:
- для Apple Silicon можно использовать `IMAGE_EMBEDDING_DEVICE=mps`, для NVIDIA — `cuda`, при отсутствии ускорителя — `cpu`;
- если `torch`/`transformers` не установлены, local CLIP не поднимется (см. troubleshooting в разделе 14).

## 8.5 Подключение к Grafana на сервере с личного ноутбука

Ниже короткий сценарий: сервер уже развернут, доступ к Grafana идет через SSH-туннель.

### На сервере (один раз проверить)

```bash
cd /root/who_is_the_spy
docker compose --profile observability up -d
docker compose ps grafana
curl http://127.0.0.1:3000/api/health
```

### На личном ноутбуке (каждый раз для подключения)

```bash
# 1) Поднять SSH-туннель до серверной Grafana
ssh -N -L 3000:127.0.0.1:3000 root@<PUBLIC_IP>
```

Во втором окне терминала:

```bash
# 2) Открыть Grafana локально
open http://localhost:3000
```

Логин в Grafana:
- username: значение `GRAFANA_ADMIN_USER` на сервере;
- password: значение `GRAFANA_ADMIN_PASSWORD` на сервере.

Проверить креды на сервере:

```bash
cd /root/who_is_the_spy
rg "^GRAFANA_ADMIN_(USER|PASSWORD)=" .env
```

Быстрые команды:

```bash
# Туннель в фоне (чтобы не держать окно)
ssh -fN -L 3000:127.0.0.1:3000 root@<PUBLIC_IP>

# Остановить фоновый туннель
pkill -f "ssh -fN -L 3000:127.0.0.1:3000 root@<PUBLIC_IP>"
```
