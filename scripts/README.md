# Скрипты для безопасного продакшен-развертывания

Эта папка содержит утилиты для автоматизации настройки безопасности и эксплуатации Who Is The Spy в продакшене.

---

## 🔒 Скрипты безопасности

### `setup-security.sh`

**Назначение:** Интерактивный мастер первичной настройки безопасности.

**Использование:**
```bash
sudo bash scripts/setup-security.sh
```

**Что делает:**
- Генерирует стойкие пароли для Redis и Grafana
- Обновляет `.env` с новыми паролями
- Настраивает UFW (firewall) в зависимости от выбранного варианта защиты
- Опционально настраивает Nginx и SSL-сертификаты (Вариант Б)
- Опционально настраивает автоматические бэкапы volumes

**Варианты защиты:**
1. **Вариант А:** SSH-туннель (локальный биндинг портов)
2. **Вариант Б:** Nginx Reverse Proxy с SSL и Basic Auth
3. **Вариант В:** DigitalOcean Cloud Firewall с IP-whitelist

**Требования:**
- Права root (sudo)
- Установленный Docker и Docker Compose
- Созданный файл `.env` (или `.env.example` для копирования)

---

### `check-security.sh`

**Назначение:** Автоматическая проверка безопасности текущей конфигурации.

**Использование:**
```bash
bash scripts/check-security.sh
```

**Проверяет:**
- ✅ Биндинг портов Grafana, Prometheus, Loki, Redis (127.0.0.1 vs 0.0.0.0)
- ✅ Стойкость паролей (длина минимум 20 символов)
- ✅ Статус UFW и корректность правил
- ✅ Публичную доступность observability-портов
- ✅ Аутентификацию Redis (requirepass)
- ✅ Наличие скриптов и cron jobs для бэкапов
- ✅ Конфигурацию Nginx и SSL-сертификатов (если используется)

**Выходные коды:**
- `0` — Все проверки пройдены, безопасность в норме
- `1` — Есть предупреждения, но критичных проблем нет
- `2` — Обнаружены критические проблемы безопасности

**Пример использования в CI/CD:**
```bash
bash scripts/check-security.sh || exit 1
```

---

### `rotate-passwords.sh`

**Назначение:** Автоматическая ротация паролей для Grafana и Redis.

**Использование:**
```bash
# Ротация только Grafana
sudo bash scripts/rotate-passwords.sh grafana

# Ротация только Redis (⚠️ потеря активных игровых сессий)
sudo bash scripts/rotate-passwords.sh redis

# Ротация всех паролей
sudo bash scripts/rotate-passwords.sh all
```

**Что делает:**
- Генерирует новый стойкий пароль (32 символа)
- Обновляет `.env` (создает .env.backup для отката)
- Пересоздает контейнеры с новыми паролями
- Проверяет корректность нового пароля
- Обновляет htpasswd для Nginx (если используется Вариант Б)

**Рекомендуемый график ротации:**
- Grafana: каждые 90 дней
- Redis: каждые 180 дней
- При подозрении на компрометацию: немедленно

**Требования:**
- Права root (sudo)
- Запущенный Docker Compose стек
- Создайте бэкап перед ротацией Redis!

---

## 🔧 Вспомогательные утилиты

### `/root/backup-observability.sh`

**Назначение:** Автоматический бэкап Docker volumes с метриками и логами.

**Создается:** Скриптом `setup-security.sh` (опционально)

**Расположение:** `/root/backup-observability.sh`

**Использование:**
```bash
# Ручной запуск
sudo bash /root/backup-observability.sh

# Автоматический запуск через cron (настраивается при установке)
crontab -l | grep backup-observability
```

**Что бэкапит:**
- Prometheus данные (метрики за последние 15 дней)
- Loki данные (логи)
- Grafana данные (дашборды, настройки, пользователи)

**Где хранятся бэкапы:**
- Директория: `/root/backups/observability/`
- Формат: `prometheus-data-YYYYMMDD_HHMMSS.tar.gz`
- Ротация: автоматическое удаление бэкапов старше 30 дней

**Восстановление из бэкапа:**
```bash
# Список доступных бэкапов
ls -lh /root/backups/observability/

# Восстановление (пример для Prometheus)
cd /root/who_is_the_spy
docker compose --profile observability down
docker run --rm \
  -v who_is_the_spy_prometheus-data:/target \
  -v /root/backups/observability:/backup \
  alpine sh -c "rm -rf /target/* && tar xzf /backup/prometheus-data-YYYYMMDD_HHMMSS.tar.gz -C /target"
docker compose --profile observability up -d
```

---

## 📋 Быстрый старт для продакшен-развертывания

### 1. Первичная настройка безопасности

```bash
# На сервере
cd /root/who_is_the_spy
sudo bash scripts/setup-security.sh
```

Следуйте интерактивным подсказкам для выбора варианта защиты.

### 2. Проверка безопасности

```bash
bash scripts/check-security.sh
```

Убедитесь, что все критические проверки пройдены (exit code 0).

### 3. Запуск бота

```bash
docker compose -f docker-compose.secure.yml --profile observability up -d
```

### 4. Проверка доступности

**С сервера (должно работать):**
```bash
curl http://localhost:3000/api/health
# {"database":"ok"}
```

**Извне (должно отваливаться):**
```bash
curl --max-time 5 http://<PUBLIC_IP>:3000
# curl: (28) Connection timed out
```

### 5. Настройка доступа (в зависимости от варианта)

**Вариант А (SSH-туннель):**
```bash
# С локальной машины
ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 root@<PUBLIC_IP>
# Открыть в браузере: http://localhost:3000
```

**Вариант Б (Nginx):**
```bash
# Настроить DNS A-записи
# Получить SSL-сертификаты (см. docs/SECURITY.md)
# Открыть в браузере: https://grafana.your-domain.com
```

**Вариант В (Cloud Firewall):**
```bash
# Настроить Firewall в DigitalOcean веб-интерфейсе
# Открыть в браузере: http://<PUBLIC_IP>:3000
```

---

## 🚨 Процедуры инцидентной реакции

### Компрометация Grafana

```bash
# 1. Немедленно остановить Grafana
docker compose stop grafana

# 2. Ротация пароля
sudo bash scripts/rotate-passwords.sh grafana

# 3. Проверка логов на подозрительную активность
docker compose logs grafana | grep -i "login\|auth"

# 4. Восстановление из бэкапа (если данные изменены)
# См. секцию "Восстановление из бэкапа" выше
```

### Атака на Redis

```bash
# 1. Проверить подключения
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" CLIENT LIST

# 2. Убить подозрительные подключения
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" CLIENT KILL ID <client-id>

# 3. Ротация пароля Redis
sudo bash scripts/rotate-passwords.sh redis

# 4. Проверить биндинг порта
sudo netstat -tulpn | grep 6379
# Должен быть: 127.0.0.1:6379, НЕ 0.0.0.0:6379
```

### Утечка OpenAI API ключа в логах

```bash
# 1. Немедленно отозвать ключ в OpenAI Dashboard
# https://platform.openai.com/api-keys

# 2. Создать новый ключ

# 3. Обновить .env
nano .env
# Изменить OPENAI_API_KEY=sk-новый-ключ

# 4. Перезапустить бота
docker compose restart bot

# 5. Очистить логи с старым ключом
docker compose exec loki rm -rf /loki/chunks/*
docker compose restart loki
```

---

## 📖 Дополнительная документация

- **[docs/SECURITY.md](../docs/SECURITY.md)** — Детальное руководство по безопасности с инструкциями для каждого варианта защиты
- **[PRODUCTION_RUNBOOK.md](../PRODUCTION_RUNBOOK.md)** — Полная инструкция по развертыванию и эксплуатации
- **[deploy/ufw/](../deploy/ufw/)** — Скрипты настройки UFW для каждого варианта защиты
- **[deploy/nginx/nginx.conf](../deploy/nginx/nginx.conf)** — Конфигурация Nginx с SSL и Basic Auth

---

## ❓ FAQ

### Какой вариант защиты выбрать?

- **Вариант А (SSH-туннель):** Один администратор, простая настройка
- **Вариант Б (Nginx + SSL):** Команда разработчиков, нужен веб-доступ из любой точки
- **Вариант В (Cloud Firewall):** Временное решение или фиксированный IP

### Как часто ротировать пароли?

- **Grafana:** каждые 90 дней (или при подозрении на компрометацию)
- **Redis:** каждые 180 дней (или немедленно при атаке)

### Что делать, если забыл пароль Grafana?

```bash
# Сгенерировать новый
NEW_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
echo "Новый пароль: $NEW_PASSWORD"

# Обновить .env
sed -i "s/GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$NEW_PASSWORD/" .env

# Пересоздать Grafana
docker compose --profile observability up -d --force-recreate grafana
```

### Как добавить нового пользователя в Nginx Basic Auth?

```bash
# Добавить пользователя (БЕЗ флага -c, чтобы не перезаписать файл)
htpasswd /root/who_is_the_spy/deploy/nginx/.htpasswd newuser

# Перезапустить Nginx
docker compose restart nginx
```

### Как проверить, что порты закрыты извне?

```bash
# С другого компьютера или через VPN
curl --max-time 5 http://<PUBLIC_IP>:3000
# Ожидается: Connection timed out (порт закрыт)

# Или используйте nmap
nmap -p 3000,9090,3100,6379 <PUBLIC_IP>
# Ожидается: filtered или closed
```

---

**Дата обновления:** 2026-05-07  
**Ревизия:** 1.0  
**Автор:** Security Expert Subagent
