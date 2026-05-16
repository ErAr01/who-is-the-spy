# 11-15. Ошибки, развитие, тестирование и FAQ

[<- К оглавлению](../TECHNICAL_DOCUMENTATION_RU.md)

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

### Q7. Ошибка `Card ID '<id>' does not exist in legacy labeling DB`
Причина: для `image-embed-*` команд передан `card_id`, которого нет в `LABELING_DB_PATH`.
Решение:
- проверить наличие карточки: `python -m src.labeling.cli list`;
- создать карточку через `ingest`/`ingest-batch` или передать корректный `--id`;
- для batch-режима убедиться, что `stem` имени файла совпадает с существующим `card_id`.

### Q8. Ошибка про отсутствие `torch`/`transformers` при `local_clip`
Причина: не установлены зависимости локального CLIP-провайдера.
Решение:
- активировать venv и установить пакеты: `pip install torch transformers`;
- повторить запуск `image-embed-ingest` с `--provider local_clip`.

### Q9. Ошибка `Unsupported IMAGE_EMBEDDING_PROVIDER='...'`
Причина: задано невалидное значение провайдера в env или в `--provider`.
Решение:
- использовать только `local_clip` или `openai`;
- проверить `IMAGE_EMBEDDING_PROVIDER` в `.env`;
- при необходимости переопределить параметром `--provider local_clip`.

### Q10. `image-embed-list` ничего не выводит (пустая image DB)
Причина:
- image-embedding ingest ещё не запускался;
- все записи упали с ошибкой при batch;
- выбран другой файл БД в `IMAGE_EMBEDDING_DB_PATH`.
Решение:
- запустить `image-embed-ingest` или `image-embed-ingest-batch`;
- проверить итоговую сводку `processed/failed` в batch;
- убедиться, что путь `IMAGE_EMBEDDING_DB_PATH` совпадает с ожидаемым.

## 15. Что не найдено / не реализовано

- Не найдены миграции БД.
- Не найден отдельный механизм переключения runtime в `GameMode.WORDS/BLANK/CUSTOM` (в текущем потоке используется `IMAGE_DB`).
- Не найден endpoint для health checks.

---

Документ подготовлен по текущему состоянию кода в репозитории (модули `src/*`, конфигурация, CLI, docker/runbook), без предположений о несуществующих функциях.
