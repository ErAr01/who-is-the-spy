# 🔒 Security Quick Reference

Краткая шпаргалка по безопасности для продакшен-развертывания Who Is The Spy.

---

## 🚀 Быстрый старт (5 минут)

```bash
# 1. Клонировать репозиторий
git clone <URL> && cd who_is_the_spy

# 2. Запустить автоматическую настройку безопасности
sudo bash scripts/setup-security.sh

# 3. Выбрать вариант защиты (А/Б/В)

# 4. Запустить бота
docker compose -f docker-compose.secure.yml --profile observability up -d

# 5. Проверить безопасность
bash scripts/check-security.sh
```

✅ **Готово!** Observability-стек защищен.

---

## 📊 Сравнение вариантов защиты

| Критерий | А: SSH-туннель | Б: Nginx+SSL | В: Cloud FW |
|----------|----------------|--------------|-------------|
| **Сложность** | ⭐ Низкая | ⭐⭐⭐ Высокая | ⭐⭐ Средняя |
| **Команда** | ❌ Один админ | ✅ Вся команда | ⚠️ Whitelist |
| **SSL** | ✅ В SSH | ✅ Let's Encrypt | ❌ Нет |
| **Домен** | ❌ Не нужен | ✅ Обязателен | ❌ Не нужен |
| **Стоимость** | $0 | $0 | $0 |

---

## 🔐 Генерация паролей

```bash
# Redis пароль (20+ символов)
openssl rand -base64 32 | tr -d '/+=' | cut -c1-32

# Grafana пароль (20+ символов)
openssl rand -base64 32 | tr -d '/+=' | cut -c1-32
```

---

## 🛡️ Вариант А: SSH-туннель

### Настройка на сервере

```bash
bash deploy/ufw/ufw-setup-variant-a.sh
docker compose -f docker-compose.secure.yml --profile observability up -d
```

### Доступ с локальной машины

```bash
# Открыть SSH-туннель
ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 root@<PUBLIC_IP>

# Открыть в браузере
http://localhost:3000  # Grafana
http://localhost:9090  # Prometheus
```

**Для удобства:** Добавьте в `~/.ssh/config`

```
Host spy-prod
  HostName <PUBLIC_IP>
  User root
  LocalForward 3000 127.0.0.1:3000
  LocalForward 9090 127.0.0.1:9090
```

Теперь просто: `ssh spy-prod`

---

## 🔒 Вариант Б: Nginx + SSL

### Настройка на сервере

```bash
# 1. Настроить DNS (A-записи для поддоменов)
# grafana.example.com → <PUBLIC_IP>

# 2. Создать htpasswd
htpasswd -c deploy/nginx/.htpasswd admin

# 3. Получить SSL-сертификаты (см. deploy/nginx/README.md)

# 4. Запустить
bash deploy/ufw/ufw-setup-variant-b.sh
docker compose -f docker-compose.secure.yml --profile observability up -d
```

### Доступ

```
https://grafana.example.com  # Basic Auth → Grafana Login
https://prometheus.example.com
```

---

## 🌐 Вариант В: Cloud Firewall

### Настройка в DigitalOcean

1. **Networking → Firewalls → Create**
2. **Inbound Rules:**
   - SSH (22): All IPv4/IPv6
   - Grafana (3000): `<ВАШ_IP>/32`
   - Prometheus (9090): `<ВАШ_IP>/32`
   - Loki (3100): `<ВАШ_IP>/32`
3. **Apply to Droplets:** Выбрать сервер

### Настройка на сервере

```bash
bash deploy/ufw/ufw-setup-variant-c.sh
docker compose --profile observability up -d
```

### Доступ

```
http://<PUBLIC_IP>:3000  # Только с вашего IP
```

---

## ✅ Проверка безопасности

```bash
# Автоматическая проверка
bash scripts/check-security.sh

# Ожидаемый результат: 0 ошибок
# ✓ Пройдено: 15
# ⚠ Предупреждений: 0
# ✗ Ошибок: 0
```

### Ручная проверка

```bash
# 1. Биндинг портов (должен быть 127.0.0.1)
sudo netstat -tulpn | grep -E ':(3000|9090|3100|6379)'

# 2. Публичная доступность (должен отваливаться)
curl --max-time 5 http://<PUBLIC_IP>:3000
# ❌ Connection timed out

# 3. Redis аутентификация
docker exec who-is-the-spy-redis redis-cli PING
# ❌ (error) NOAUTH Authentication required.
```

---

## 🔄 Ротация паролей

```bash
# Grafana (каждые 90 дней)
sudo bash scripts/rotate-passwords.sh grafana

# Redis (каждые 180 дней)
sudo bash scripts/rotate-passwords.sh redis

# Все пароли сразу
sudo bash scripts/rotate-passwords.sh all
```

---

## 💾 Бэкапы

```bash
# Ручной бэкап
sudo bash /root/backup-observability.sh

# Проверка автоматических бэкапов
crontab -l | grep backup
ls -lh /root/backups/observability/

# Восстановление
docker compose --profile observability down
docker run --rm \
  -v who_is_the_spy_grafana-data:/target \
  -v /root/backups/observability:/backup \
  alpine sh -c "rm -rf /target/* && tar xzf /backup/grafana-YYYYMMDD.tar.gz -C /target"
docker compose --profile observability up -d
```

---

## 🚨 Инцидентная реакция

### Компрометация Grafana

```bash
docker compose stop grafana
sudo bash scripts/rotate-passwords.sh grafana
docker compose logs grafana | grep -i "auth"
```

### Атака на Redis

```bash
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" CLIENT LIST
sudo bash scripts/rotate-passwords.sh redis
sudo netstat -tulpn | grep 6379  # Проверить биндинг
```

### Утечка OpenAI ключа

```bash
# 1. Отозвать в OpenAI Dashboard
# 2. Обновить .env
nano .env  # OPENAI_API_KEY=sk-новый-ключ
docker compose restart bot
# 3. Очистить логи
docker compose exec loki rm -rf /loki/chunks/*
docker compose restart loki
```

---

## 📌 Критические порты

| Порт | Сервис | Биндинг | Защита |
|------|--------|---------|--------|
| 22 | SSH | 0.0.0.0 | ✅ UFW open |
| 3000 | Grafana | **127.0.0.1** | ✅ Закрыт |
| 9090 | Prometheus | **127.0.0.1** | ✅ Закрыт |
| 3100 | Loki | **127.0.0.1** | ✅ Закрыт |
| 6379 | Redis | **127.0.0.1** | ✅ Закрыт |
| 8001 | Bot metrics | 0.0.0.0 | ⚠️ Внутри Docker |

---

## 🔍 Полезные команды

```bash
# Статус контейнеров
docker compose ps

# Логи бота
docker compose logs --tail 200 -f bot

# Проверка UFW
sudo ufw status numbered

# Использование ресурсов
docker stats

# Размер volumes
docker system df -v

# Healthcheck
curl http://localhost:3000/api/health
curl http://localhost:9090/-/ready
```

---

## 📖 Полная документация

- **[docs/SECURITY.md](docs/SECURITY.md)** — Детальное руководство по безопасности
- **[PRODUCTION_RUNBOOK.md](PRODUCTION_RUNBOOK.md)** — Инструкция по развертыванию
- **[scripts/README.md](scripts/README.md)** — Описание утилит безопасности
- **[deploy/nginx/README.md](deploy/nginx/README.md)** — Настройка Nginx (Вариант Б)
- **[deploy/digitalocean/cloud-firewall-setup.md](deploy/digitalocean/cloud-firewall-setup.md)** — Настройка Cloud Firewall (Вариант В)

---

## ⚡ Одна команда для всего

```bash
# Полная автоматическая настройка безопасности
curl -sSL https://raw.githubusercontent.com/.../scripts/setup-security.sh | sudo bash
```

---

**Версия:** 1.0  
**Дата:** 2026-05-07  
**Поддержка:** [docs/SECURITY.md](docs/SECURITY.md)
