# Конфигурация Nginx Reverse Proxy (Вариант Б)

Эта директория содержит конфигурацию Nginx для Варианта Б — защиты observability-стека через HTTPS и Basic Auth.

---

## 📁 Структура файлов

```
deploy/nginx/
├── nginx.conf              # Основная конфигурация Nginx
├── .htpasswd               # Пароли для Basic Auth (создается вручную)
├── ssl/                    # SSL-сертификаты Let's Encrypt (создается автоматически)
│   └── live/
│       ├── grafana.your-domain.com/
│       ├── prometheus.your-domain.com/
│       └── loki.your-domain.com/
└── README.md               # Этот файл
```

---

## 🚀 Быстрый старт

### 1. Подготовка DNS

Настройте A-записи для ваших поддоменов:

```
grafana.your-domain.com    → <PUBLIC_IP>
prometheus.your-domain.com → <PUBLIC_IP>
loki.your-domain.com       → <PUBLIC_IP>
```

### 2. Создание файла паролей htpasswd

```bash
# Установка apache2-utils (если еще не установлен)
sudo apt install -y apache2-utils

# Создание первого пользователя
htpasswd -c /root/who_is_the_spy/deploy/nginx/.htpasswd admin
# Введите пароль дважды

# Добавление дополнительных пользователей (БЕЗ флага -c!)
htpasswd /root/who_is_the_spy/deploy/nginx/.htpasswd developer
```

### 3. Обновление nginx.conf

Замените `your-domain.com` на ваш реальный домен:

```bash
cd /root/who_is_the_spy
sed -i 's/your-domain.com/example.com/g' deploy/nginx/nginx.conf
```

### 4. Получение SSL-сертификатов

#### Шаг 1: Временный Nginx для ACME challenge

```bash
cd /root/who_is_the_spy

# Создать volume для certbot
docker volume create certbot-webroot

# Создать временный конфиг без SSL
cat > deploy/nginx/nginx-temp.conf << 'EOF'
events {
    worker_connections 1024;
}
http {
    server {
        listen 80;
        server_name grafana.example.com prometheus.example.com loki.example.com;
        
        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }
        
        location / {
            return 200 "OK";
        }
    }
}
EOF

# Запустить временный Nginx
docker run -d --name nginx-temp \
  -p 80:80 \
  -v $(pwd)/deploy/nginx/nginx-temp.conf:/etc/nginx/nginx.conf:ro \
  -v $(pwd)/deploy/nginx/ssl:/etc/letsencrypt \
  -v certbot-webroot:/var/www/certbot \
  nginx:1.27-alpine
```

#### Шаг 2: Получение сертификатов через Certbot

```bash
# Замените на ваши домены и email
docker run --rm \
  -v $(pwd)/deploy/nginx/ssl:/etc/letsencrypt \
  -v certbot-webroot:/var/www/certbot \
  certbot/certbot:v3.0.1 certonly \
  --webroot --webroot-path=/var/www/certbot \
  --email your-email@example.com \
  --agree-tos --no-eff-email \
  -d grafana.example.com \
  -d prometheus.example.com \
  -d loki.example.com
```

#### Шаг 3: Остановка временного Nginx и запуск основного стека

```bash
# Остановить временный Nginx
docker stop nginx-temp && docker rm nginx-temp

# Раскомментировать nginx сервис в docker-compose.secure.yml
# (см. инструкции в файле)

# Запустить основной стек
docker compose -f docker-compose.secure.yml --profile observability up -d
```

### 5. Проверка работоспособности

```bash
# Проверка конфигурации Nginx
docker compose exec nginx nginx -t

# Проверка SSL
curl -I https://grafana.example.com
# Должен вернуть 401 Unauthorized (требуется Basic Auth)

# Проверка с Basic Auth
curl -u admin:your_password https://grafana.example.com/api/health
# {"database":"ok"}

# Проверка редиректа HTTP → HTTPS
curl -I http://grafana.example.com
# Должен вернуть 301 Moved Permanently
```

---

## 🔒 Архитектура безопасности

### Уровни защиты

```
Интернет
   ↓
[UFW Firewall] ← Блокирует все, кроме 22, 80, 443
   ↓
[Nginx] ← SSL + Basic Auth + Rate Limiting
   ↓
[Grafana (127.0.0.1:3000)] ← Локальный биндинг + Grafana Auth
```

### Защищенные endpoints

| URL | Защита | Назначение |
|-----|--------|-----------|
| `https://grafana.example.com` | SSL + Basic Auth + Grafana Login | Дашборды, метрики, логи |
| `https://prometheus.example.com` | SSL + Basic Auth | Прямой доступ к Prometheus UI |
| `https://loki.example.com` | SSL + Basic Auth | Прямой доступ к Loki API (редко нужен) |

### Rate Limiting

Nginx ограничивает запросы на login endpoints для защиты от brute-force:

```nginx
limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=5r/m;
```

- **Лимит:** 5 запросов в минуту с одного IP
- **Burst:** до 3 дополнительных запросов без задержки
- **Блокировка:** HTTP 429 Too Many Requests при превышении

---

## 🔧 Настройка

### Добавление нового пользователя

```bash
# Добавить пользователя в htpasswd
htpasswd /root/who_is_the_spy/deploy/nginx/.htpasswd newuser

# Перезапустить Nginx
docker compose restart nginx
```

### Удаление пользователя

```bash
# Удалить пользователя из htpasswd
htpasswd -D /root/who_is_the_spy/deploy/nginx/.htpasswd olduser

# Перезапустить Nginx
docker compose restart nginx
```

### Изменение пароля пользователя

```bash
# Обновить пароль (флаг -b позволяет передать пароль без интерактивного ввода)
htpasswd -b /root/who_is_the_spy/deploy/nginx/.htpasswd admin new_password

# Перезапустить Nginx
docker compose restart nginx
```

### Автообновление SSL-сертификатов

Certbot автоматически обновляет сертификаты каждые 12 часов (контейнер в docker-compose.secure.yml).

**Ручное обновление:**

```bash
# Обновить сертификаты
docker compose exec certbot certbot renew

# Перезапустить Nginx для применения новых сертификатов
docker compose restart nginx
```

**Проверка срока действия сертификатов:**

```bash
echo | openssl s_client -connect grafana.example.com:443 2>/dev/null | openssl x509 -noout -dates
```

---

## 📊 Мониторинг и логирование

### Просмотр логов Nginx

```bash
# Access logs (все запросы)
docker compose logs nginx | grep "GET\|POST"

# Неуспешные попытки Basic Auth
docker compose exec nginx cat /var/log/nginx/grafana_auth_fail.log

# Tail логов в реальном времени
docker compose logs -f nginx
```

### Алерты в Prometheus

Добавьте правила для мониторинга неуспешных аутентификаций:

```yaml
# В deploy/observability/prometheus/rules/security-alerts.yml
groups:
  - name: nginx_security
    interval: 1m
    rules:
      - alert: HighFailedAuthRate
        expr: rate(nginx_http_requests_total{status="401"}[5m]) > 5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Множественные неуспешные попытки Basic Auth"
          description: "Обнаружено {{ $value }} попыток/сек"
```

### Fail2Ban (опционально)

Автоматическая блокировка IP после N неуспешных попыток:

```bash
# Установка
sudo apt install -y fail2ban

# Конфигурация фильтра
sudo tee /etc/fail2ban/filter.d/nginx-auth.conf > /dev/null << 'EOF'
[Definition]
failregex = ^<HOST> -.*"(GET|POST).*HTTP.*" 401
ignoreregex =
EOF

# Конфигурация jail
sudo tee /etc/fail2ban/jail.d/nginx-auth.conf > /dev/null << 'EOF'
[nginx-auth]
enabled = true
port = http,https
logpath = /var/log/nginx/access.log
maxretry = 5
findtime = 600
bantime = 3600
EOF

# Перезапуск
sudo systemctl restart fail2ban

# Проверка заблокированных IP
sudo fail2ban-client status nginx-auth
```

---

## 🚨 Troubleshooting

### Ошибка: "ssl_certificate: no such file or directory"

**Причина:** SSL-сертификаты не получены или неправильный путь в nginx.conf

**Решение:**
```bash
# Проверить наличие сертификатов
ls -la deploy/nginx/ssl/live/grafana.example.com/

# Если сертификатов нет — выполнить шаги 4.1-4.2 из "Быстрого старта"
```

### Ошибка: "401 Unauthorized" при правильном пароле

**Причина:** Файл .htpasswd не найден или неправильный формат

**Решение:**
```bash
# Проверить существование файла
ls -la deploy/nginx/.htpasswd

# Пересоздать файл
htpasswd -c deploy/nginx/.htpasswd admin

# Перезапустить Nginx
docker compose restart nginx
```

### Ошибка: "429 Too Many Requests"

**Причина:** Превышен лимит rate limiting (5 запросов/минуту на login endpoints)

**Решение:**
- Подождите 1 минуту перед следующей попыткой
- Или увеличьте лимит в nginx.conf: `rate=10r/m` вместо `5r/m`

### Grafana не работает через Nginx, но работает напрямую

**Причина:** Неправильная настройка WebSocket или GF_SERVER_ROOT_URL

**Решение:**
```bash
# Добавить в .env
GRAFANA_ROOT_URL=https://grafana.example.com

# Проверить nginx.conf (должны быть строки)
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";

# Перезапустить Grafana
docker compose restart grafana
```

---

## 📖 Дополнительные ресурсы

- **[docs/SECURITY.md](../../docs/SECURITY.md)** — Детальное руководство по безопасности
- **[Nginx Official Docs](https://nginx.org/en/docs/)** — Официальная документация Nginx
- **[Let's Encrypt Docs](https://letsencrypt.org/docs/)** — Документация по SSL-сертификатам
- **[Mozilla SSL Config Generator](https://ssl-config.mozilla.org/)** — Генератор безопасных SSL-конфигураций

---

**Дата обновления:** 2026-05-07  
**Совместимость:** Nginx 1.27+, Certbot 3.0+
