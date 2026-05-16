# 6. Подробная документация CLI (`src/labeling/cli.py`)

[<- К оглавлению](../TECHNICAL_DOCUMENTATION_RU.md)

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

### 6.11 `image-embed-ingest`

Создаёт/обновляет image embedding одной картинки в отдельной БД эмбеддингов.

Параметры:
- `--image PATH` (обязательный).
- `--id TEXT` (опционально, default: stem файла).
- `--force` (флаг): принудительный пересчёт.
- `--provider [local_clip|openai]` (опционально, override env).

Ограничение:
- `card_id` должен существовать в legacy `cards.db`, иначе команда вернёт ошибку.

Когда использовать:
- точечная загрузка/обновление одной карточки в `IMAGE_EMBEDDING_DB_PATH`;
- быстрая проверка, что локальный CLIP-провайдер работает в текущем окружении.

Пример:
- `python -m src.labeling.cli image-embed-ingest --image ./samples/bruce.jpg --id bruce-willis --provider local_clip`

### 6.12 `image-embed-ingest-batch`

Пакетная image-embedding разметка каталога (`.jpg/.jpeg/.png/.webp`), пишет только в `IMAGE_EMBEDDING_DB_PATH`.

Параметры:
- `--dir PATH` (обязательный).
- `--force` (флаг).
- `--provider [local_clip|openai]` (опционально).

Поведение:
- `card_id` берётся из имени файла (`stem`), поэтому имена файлов должны совпадать с `card_id` в legacy БД;
- в конце команда печатает сводку `Attempted/processed/failed/skipped_duplicates`.

Пример:
- `python -m src.labeling.cli image-embed-ingest-batch --dir ./samples --provider local_clip`

### 6.13 `image-embed-reembed`

Принудительный пересчёт image embedding одной картинки.

Параметры:
- `--image PATH` (обязательный).
- `--id TEXT` (опционально, default: stem файла).
- `--provider [local_clip|openai]` (опционально).

Когда использовать:
- если нужно принудительно пересчитать вектор уже существующей записи;
- после смены модели (`LOCAL_CLIP_MODEL_NAME`) или устройства (`IMAGE_EMBEDDING_DEVICE`).

Пример:
- `python -m src.labeling.cli image-embed-reembed --image ./samples/bruce.jpg --id bruce-willis --provider local_clip`

### 6.14 `image-embed-list`

Список image embeddings из отдельной БД.

Параметры:
- `--format [table|json]`.

Примеры:
- `python -m src.labeling.cli image-embed-list`
- `python -m src.labeling.cli image-embed-list --format json`

### 6.15 Быстрый runbook для image-embedding CLI

1. Проверить, что карточки уже есть в legacy БД:
   - `python -m src.labeling.cli list`
2. Загрузить/обновить image embeddings:
   - одна карточка: `image-embed-ingest`;
   - каталог: `image-embed-ingest-batch`.
3. Пересчитать выбранные записи при необходимости:
   - `image-embed-reembed`.
4. Проверить содержимое отдельной image DB:
   - `image-embed-list` (`table` или `json`).
