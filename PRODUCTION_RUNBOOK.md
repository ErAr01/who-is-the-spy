# Запуск Who Is The Spy в продовом режиме

Ниже — рабочая инструкция для **безопасного** и стабильного запуска бота в проде через Docker Compose.

> ⚠️ **ВАЖНО**: Перед запуском в продакшене **обязательно** прочитайте [docs/SECURITY.md](docs/SECURITY.md) для защиты observability-стека от несанкционированного доступа.

## 1) Что нужно заранее

- Сервер Linux (Ubuntu/Debian) с установленными:
  - Docker (версия 20.10+)
  - Docker Compose Plugin v2 (`docker compose`)
- Telegram-бот, созданный через BotFather.
- Отключенный privacy mode у бота (`/setprivacy -> Disable`), если игра в группах.
- Доступ к репозиторию на сервере (SSH-ключ или пароль).
- **Стойкие пароли** для Redis и Grafana (см. шаг 2).

## 2) Подготовка проекта на сервере

```bash
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ>
cd who_is_the_spy
```

### 2.1) Автоматическая настройка безопасности (рекомендуется)

Используйте интерактивный скрипт для автоматической настройки:

```bash
sudo bash scripts/setup-security.sh
```

Скрипт выполнит:
- Генерацию стойких паролей для Redis и Grafana
- Создание и настройку `.env`
- Настройку UFW (firewall)
- Настройку выбранного варианта защиты (SSH-туннель, Nginx или Cloud Firewall)
- Опционально: настройку автоматических бэкапов

### 2.2) Ручная настройка

Если предпочитаете ручную настройку:

**Создайте `.env`:**

```bash
cp .env.example .env
```

**Сгенерируйте стойкие пароли:**

```bash
# Redis пароль (минимум 20 символов)
openssl rand -base64 32 | tr -d '/+=' | cut -c1-32

# Grafana пароль (минимум 20 символов)
openssl rand -base64 32 | tr -d '/+=' | cut -c1-32
```

**Заполните `.env` (минимум):**

```env
BOT_TOKEN=123456:ABC...
REDIS_PASSWORD=<сгенерированный_пароль_redis>
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
LOG_LEVEL=INFO
METRICS_ENABLED=true
METRICS_HOST=0.0.0.0
METRICS_PORT=8001
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<сгенерированный_пароль_grafana>
OPENAI_API_KEY=sk-...
OPENAI_VISION_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
LABELING_DB_PATH=data/images/cards.db
PAIR_SIMILARITY_THRESHOLD=0.55
PAIR_HISTORY_SIZE=50
```

⚠️ **Критически важно:**
- **НЕ используйте** дефолтный пароль `admin` для Grafana
- **НЕ оставляйте** Redis без пароля
- Для Docker используйте `REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0`
- Убедитесь, что `data/images/cards.db` уже содержит карточки

### 2.3) Выбор варианта защиты observability-стека

**Вариант А: SSH-туннель (рекомендуется для одного админа)**
```bash
# Используйте docker-compose.secure.yml с локальным биндингом портов
bash deploy/ufw/ufw-setup-variant-a.sh
```

**Вариант Б: Nginx Reverse Proxy с SSL (для команды)**
```bash
# Требуется домен и настройка DNS
bash deploy/ufw/ufw-setup-variant-b.sh
# Затем следуйте инструкциям в docs/SECURITY.md для настройки SSL
```

**Вариант В: DigitalOcean Cloud Firewall (простая защита)**
```bash
bash deploy/ufw/ufw-setup-variant-c.sh
# Затем настройте Cloud Firewall через веб-интерфейс DigitalOcean
```

📖 **Детальные инструкции для каждого варианта:** [docs/SECURITY.md](docs/SECURITY.md)

## 3) Первый запуск в проде

### 3.1) Безопасный запуск (рекомендуется)

Используйте `docker-compose.secure.yml` с встроенными настройками безопасности:

```bash
docker compose -f docker-compose.secure.yml up -d --build
```

Для запуска с observability-стеком:

```bash
docker compose -f docker-compose.secure.yml --profile observability up -d --build
```

### 3.2) Дефолтный запуск (требует ручной настройки безопасности)

⚠️ **Не рекомендуется** без предварительной настройки портов на `127.0.0.1` в `docker-compose.yml`

```bash
docker compose up -d --build
```

Для observability-стека:

```bash
docker compose --profile observability up -d --build
```

Проверка контейнеров:

```bash
docker compose ps
```

Проверка логов:

```bash
docker compose logs -f bot
```

Ожидаемое состояние:
- `redis` в статусе `Up`
- `bot` в статусе `Up`
- в логах бота нет падений по токену/Redis/импортам
- при включенном профиле `observability`: `prometheus`, `loki`, `promtail`, `grafana` тоже в `Up`

## 4) Проверка observability (если профиль включен)

Проверить, что сервисы доступны:

```bash
curl -fsS http://localhost:9090/-/ready
curl -fsS http://localhost:3100/ready
curl -fsS http://localhost:3000/api/health
```

Проверить метрики бота через Prometheus target:

1. Откройте `http://localhost:9090/targets`
2. Убедитесь, что `job="bot"` в статусе `UP`

Проверить Grafana:

- URL: `http://localhost:3000`
- логин/пароль: из `GRAFANA_ADMIN_USER` и `GRAFANA_ADMIN_PASSWORD`
- datasource `Prometheus` и `Loki` создаются автоматически через provisioning

## 5) Проверка после запуска (обязательно)

1. Напишите боту в личку `/start`.
2. В личке запустите `/testpair` и проверьте:
   - генерацию карточек,
   - ссылки Wikipedia/Google.
3. В группе:
   - `/newgame`
   - игроки `Join`
   - `/startgame`
   - `/vote`
   - `/endvote`

Если все шаги проходят — продовый запуск корректен.

## 6) Ежедневные команды эксплуатации

Статус:

```bash
docker compose ps
```

Логи бота:

```bash
docker compose logs --tail 200 bot
```

Перезапуск только бота:

```bash
docker compose restart bot
```

Остановка:

```bash
docker compose down
```

## 7) Обновление на новую версию

```bash
git pull
docker compose up -d --build
docker compose ps
docker compose logs --tail 200 bot
```

После обновления повторите короткий smoke:
- `/start` в личке
- `/testpair`
- один тестовый раунд в группе

## 8) Типовые проблемы и быстрые решения

- **`BOT_TOKEN` некорректен**  
  Проверьте токен в `.env`, затем `docker compose up -d --build`.

- **Бот не видит команды в группе**  
  Проверьте privacy mode у BotFather (должен быть `Disable`).

- **Ошибки `RateLimitError` от OpenAI**  
  Это внешний лимит API. Повторите позже или уменьшите интенсивность batch-разметки.

- **`Недостаточно карточек в выбранных категориях`**  
  Добавьте/переразметьте карточки в `cards.db` для нужной категории.

- **`job="bot"` в Prometheus не поднимается**  
  Проверьте `METRICS_ENABLED=true` и что контейнер `bot` запущен. Затем `docker compose logs --tail 200 bot`.

## 9) Резервное копирование (обязательно)

### 9.1) Бэкап БД карточек

```bash
cp data/images/cards.db "data/images/cards.db.backup.$(date +%Y%m%d_%H%M%S)"
```

Делайте бэкап:
- перед массовой переразметкой,
- перед крупным обновлением.

### 9.2) Бэкап observability volumes (метрики, логи, дашборды)

**Автоматический бэкап (настраивается скриптом setup-security.sh):**

```bash
# Проверка cron job
crontab -l | grep backup-observability

# Ручной запуск
sudo bash /root/backup-observability.sh
```

**Ручной разовый бэкап:**

```bash
# Бэкап Prometheus данных
docker run --rm \
  -v who_is_the_spy_prometheus-data:/source:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf "/backup/prometheus-$(date +%Y%m%d).tar.gz" -C /source .

# Бэкап Loki данных
docker run --rm \
  -v who_is_the_spy_loki-data:/source:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf "/backup/loki-$(date +%Y%m%d).tar.gz" -C /source .

# Бэкап Grafana данных (дашборды, настройки)
docker run --rm \
  -v who_is_the_spy_grafana-data:/source:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf "/backup/grafana-$(date +%Y%m%d).tar.gz" -C /source .
```

**Восстановление из бэкапа:**

```bash
# Остановить сервисы
docker compose --profile observability down

# Восстановить Prometheus
docker run --rm \
  -v who_is_the_spy_prometheus-data:/target \
  -v $(pwd)/backups:/backup \
  alpine sh -c "rm -rf /target/* && tar xzf /backup/prometheus-YYYYMMDD.tar.gz -C /target"

# Аналогично для Loki и Grafana

# Запустить сервисы
docker compose --profile observability up -d
```

## 10) Проверка безопасности (обязательно перед продакшен-запуском)

Используйте скрипт автоматической проверки безопасности:

```bash
bash scripts/check-security.sh
```

Скрипт проверит:
- ✅ Биндинг портов (127.0.0.1 vs 0.0.0.0)
- ✅ Стойкость паролей Grafana и Redis
- ✅ Статус UFW и правила firewall
- ✅ Публичную доступность портов
- ✅ Аутентификацию Redis
- ✅ Наличие бэкапов
- ✅ Конфигурацию Nginx (если используется)

**Ожидаемый результат:**

```
========================================
📊 Итоговый отчет
========================================

✓ Пройдено: 15
⚠ Предупреждений: 2
✗ Ошибок: 0

✅ Безопасность настроена корректно!
```

⚠️ **Если найдены критические ошибки** — НЕ запускайте в продакшене без их исправления!

## 11) Ротация паролей (рекомендуется каждые 90 дней)

Используйте скрипт автоматической ротации:

```bash
# Ротация только Grafana
sudo bash scripts/rotate-passwords.sh grafana

# Ротация только Redis (⚠️ потеря активных сессий)
sudo bash scripts/rotate-passwords.sh redis

# Ротация всех паролей
sudo bash scripts/rotate-passwords.sh all
```

## 12) Опционально: PostHog self-hosted (шаблон)

В проекте есть отдельная заготовка compose-файла:

```bash
docker compose -f deploy/observability/posthog/docker-compose.posthog.yml up -d
```

Перед запуском на проде обязательно задайте сильный `POSTHOG_SECRET_KEY` и вынесите значения БД в безопасные секреты.
