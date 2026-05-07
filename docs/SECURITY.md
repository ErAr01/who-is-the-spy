# Руководство по безопасности продакшен-развертывания

**[CONF: HIGH]** Документ описывает критические уязвимости при дефолтной конфигурации и три варианта их устранения для развертывания на DigitalOcean Ubuntu.

---

## 🔴 Критические уязвимости текущей конфигурации

### [Severity: CRITICAL] Публичная экспозиция метрик и административных интерфейсов

**Vector:**
```
Атакующий → Публичный IP сервера:3000 → Grafana (admin/admin)
Атакующий → Публичный IP сервера:9090 → Prometheus (без аутентификации)
Атакующий → Публичный IP сервера:3100 → Loki (без аутентификации)
Атакующий → Публичный IP сервера:6379 → Redis (без пароля)
```

**Impact:**
- **Grafana**: Полный доступ к дашбордам, метрикам, логам игровых сессий, API-ключам OpenAI в переменных окружения
- **Prometheus**: Раскрытие инфраструктуры, метрик производительности, возможность DoS через запросы
- **Loki**: Доступ к логам приложения, включая токены, ошибки, пользовательские данные
- **Redis**: Прямой доступ к игровым сессиям, возможность инъекции команд, DoS через FLUSHALL

**Proof of Concept:**
```bash
# Любой человек в интернете может выполнить:
curl http://<ВАШ_IP>:9090/api/v1/query?query=up
curl http://<ВАШ_IP>:3100/loki/api/v1/query?query={job="bot"}
redis-cli -h <ВАШ_IP> -p 6379 KEYS *
```

**Mitigation:** См. разделы ниже — три варианта защиты.

---

### [Severity: HIGH] Дефолтные учетные данные Grafana

**Vector:**
```env
GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
```

Пароль `admin` легко брутфорсится автоматизированными ботами.

**Mitigation:**
```bash
# Генерация стойкого пароля
openssl rand -base64 32 | tr -d '/+=' | cut -c1-32
```

---

### [Severity: HIGH] Redis без аутентификации

**Vector:**
Redis принимает подключения без пароля. При публичной экспозиции порта 6379 доступны команды:
```
CONFIG SET dir /root/.ssh/
CONFIG SET dbfilename authorized_keys
# Инъекция SSH-ключа для доступа к серверу
```

**Mitigation:**
```yaml
# В docker-compose.yml добавить команду с requirepass
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD}
```

```env
# В .env
REDIS_PASSWORD=<сгенерированный пароль>
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
```

---

## 🛡️ Три варианта защиты продакшен-развертывания

### Вариант А: SSH-туннель (Локальный биндинг) — для одного администратора

**Описание:**
Все порты observability-стека биндятся на `127.0.0.1` внутри сервера. Доступ получается через SSH-туннель с локальной машины.

**Плюсы:**
- ✅ Максимальная простота конфигурации
- ✅ Нулевые дополнительные зависимости (Nginx, SSL-сертификаты)
- ✅ Работает "из коробки" при наличии SSH-ключа

**Минусы:**
- ❌ Доступ только с одной машины одновременно (или нужны отдельные туннели)
- ❌ Нет SSL-шифрования на уровне HTTP (но есть в SSH)
- ❌ Неудобно для команды разработчиков

**Кому подходит:**
Один разработчик/администратор с постоянным SSH-доступом к серверу.

**Инструкция:**

#### 1. Обновление docker-compose.yml

Замените секцию `ports` для всех observability-сервисов:

```yaml
# ❌ Было (публичный биндинг):
ports:
  - "9090:9090"

# ✅ Стало (локальный биндинг):
ports:
  - "127.0.0.1:9090:9090"
```

Применить ко всем:
- `grafana`: `127.0.0.1:3000:3000`
- `prometheus`: `127.0.0.1:9090:9090`
- `loki`: `127.0.0.1:3100:3100`
- `redis`: `127.0.0.1:6379:6379`

#### 2. Перезапуск стека

```bash
cd /root/who_is_the_spy
docker compose --profile observability down
docker compose --profile observability up -d
```

#### 3. Проверка на сервере

```bash
# Эти команды должны работать:
curl http://127.0.0.1:3000/api/health
curl http://127.0.0.1:9090/-/ready

# Эти команды должны ОТВАЛИВАТЬСЯ по таймауту:
curl http://0.0.0.0:3000/api/health  # Connection refused
curl http://<PUBLIC_IP>:3000/api/health  # Timeout
```

#### 4. Настройка SSH-туннеля с локальной машины

**Одноразовый туннель:**
```bash
ssh -L 3000:127.0.0.1:3000 \
    -L 9090:127.0.0.1:9090 \
    -L 3100:127.0.0.1:3100 \
    root@<PUBLIC_IP>
```

**Постоянный туннель в фоне:**
```bash
ssh -fN -L 3000:127.0.0.1:3000 \
         -L 9090:127.0.0.1:9090 \
         -L 3100:127.0.0.1:3100 \
         root@<PUBLIC_IP>
```

**SSH-конфиг (~/.ssh/config) для упрощения:**
```
Host spy-prod
  HostName <PUBLIC_IP>
  User root
  LocalForward 3000 127.0.0.1:3000
  LocalForward 9090 127.0.0.1:9090
  LocalForward 3100 127.0.0.1:3100
```

Затем просто:
```bash
ssh spy-prod
```

#### 5. Доступ с локальной машины

Открыть в браузере:
- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090
- Loki: http://localhost:3100

---

### Вариант Б: Nginx Reverse Proxy с Basic Auth и SSL — для команды

**Описание:**
Nginx выступает единой точкой входа с HTTPS и базовой HTTP-аутентификацией. Все observability-сервисы доступны через поддомены или пути.

**Плюсы:**
- ✅ Полноценное SSL-шифрование (Let's Encrypt)
- ✅ Централизованная аутентификация (htpasswd)
- ✅ Доступ из любой точки мира через браузер
- ✅ Легко добавлять новых пользователей

**Минусы:**
- ❌ Требуется домен и DNS-настройка
- ❌ Сложнее настройка (Nginx конфиги, SSL-сертификаты)
- ❌ Дополнительный контейнер (Nginx + Certbot)

**Кому подходит:**
Команда разработчиков, нужен веб-доступ из разных локаций.

**Инструкция:**

#### 1. Подготовка DNS

Настройте A-записи для поддоменов:
```
grafana.your-domain.com   → <PUBLIC_IP>
prometheus.your-domain.com → <PUBLIC_IP>
loki.your-domain.com       → <PUBLIC_IP>
```

Или используйте единый домен с путями (см. конфиг Nginx ниже).

#### 2. Создание файла паролей htpasswd

```bash
# На сервере
sudo apt install -y apache2-utils
mkdir -p /root/who_is_the_spy/deploy/nginx

# Создание пользователя (admin)
htpasswd -c /root/who_is_the_spy/deploy/nginx/.htpasswd admin
# Введите пароль дважды

# Добавление еще пользователей (без флага -c)
htpasswd /root/who_is_the_spy/deploy/nginx/.htpasswd developer
```

#### 3. Обновление docker-compose.yml

**Изменить биндинг портов на локальный:**
```yaml
# Для grafana, prometheus, loki
ports:
  - "127.0.0.1:3000:3000"
  - "127.0.0.1:9090:9090"
  - "127.0.0.1:3100:3100"
```

**Добавить Nginx-сервис:**
```yaml
nginx:
  image: nginx:1.27-alpine
  container_name: who-is-the-spy-nginx
  profiles:
    - observability
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    - ./deploy/nginx/.htpasswd:/etc/nginx/.htpasswd:ro
    - ./deploy/nginx/ssl:/etc/nginx/ssl:ro
    - certbot-webroot:/var/www/certbot:ro
  depends_on:
    - grafana
    - prometheus
  restart: unless-stopped

certbot:
  image: certbot/certbot:v3.0.1
  profiles:
    - observability
  volumes:
    - ./deploy/nginx/ssl:/etc/letsencrypt
    - certbot-webroot:/var/www/certbot
  entrypoint: /bin/sh -c "trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done"

volumes:
  certbot-webroot:
  # ... остальные volumes
```

#### 4. Создание конфигурации Nginx

Создайте файл `/root/who_is_the_spy/deploy/nginx/nginx.conf`:

```nginx
events {
    worker_connections 1024;
}

http {
    # Rate limiting для защиты от brute-force
    limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=5r/m;
    
    # Базовые настройки безопасности
    server_tokens off;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Grafana
    server {
        listen 80;
        server_name grafana.your-domain.com;
        
        # Редирект на HTTPS
        location / {
            return 301 https://$host$request_uri;
        }
        
        # Для Let's Encrypt challenge
        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }
    }

    server {
        listen 443 ssl http2;
        server_name grafana.your-domain.com;

        ssl_certificate /etc/letsencrypt/live/grafana.your-domain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/grafana.your-domain.com/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        # Basic Auth
        auth_basic "Restricted Access";
        auth_basic_user_file /etc/nginx/.htpasswd;
        
        # Rate limiting на login endpoints
        location ~ ^/(login|api/login) {
            limit_req zone=auth_limit burst=3 nodelay;
            proxy_pass http://grafana:3000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        location / {
            proxy_pass http://grafana:3000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # WebSocket support для Grafana Live
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }
    }

    # Prometheus
    server {
        listen 443 ssl http2;
        server_name prometheus.your-domain.com;

        ssl_certificate /etc/letsencrypt/live/prometheus.your-domain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/prometheus.your-domain.com/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;

        auth_basic "Restricted Access";
        auth_basic_user_file /etc/nginx/.htpasswd;

        location / {
            proxy_pass http://prometheus:9090;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }

    # Loki (опционально, обычно не нужен прямой доступ)
    server {
        listen 443 ssl http2;
        server_name loki.your-domain.com;

        ssl_certificate /etc/letsencrypt/live/loki.your-domain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/loki.your-domain.com/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;

        auth_basic "Restricted Access";
        auth_basic_user_file /etc/nginx/.htpasswd;

        location / {
            proxy_pass http://loki:3100;
            proxy_set_header Host $host;
        }
    }
}
```

#### 5. Получение SSL-сертификатов Let's Encrypt

**Первичная настройка (перед запуском Nginx с SSL):**

```bash
# Временный конфиг Nginx без SSL для получения сертификатов
cat > /root/who_is_the_spy/deploy/nginx/nginx-temp.conf << 'EOF'
events {
    worker_connections 1024;
}
http {
    server {
        listen 80;
        server_name grafana.your-domain.com prometheus.your-domain.com loki.your-domain.com;
        
        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }
        
        location / {
            return 200 "OK";
        }
    }
}
EOF

# Запуск Nginx с временным конфигом
docker run -d --name nginx-temp \
  -p 80:80 \
  -v /root/who_is_the_spy/deploy/nginx/nginx-temp.conf:/etc/nginx/nginx.conf:ro \
  -v /root/who_is_the_spy/deploy/nginx/ssl:/etc/letsencrypt \
  -v certbot-webroot:/var/www/certbot \
  nginx:1.27-alpine

# Получение сертификатов
docker run --rm \
  -v /root/who_is_the_spy/deploy/nginx/ssl:/etc/letsencrypt \
  -v certbot-webroot:/var/www/certbot \
  certbot/certbot:v3.0.1 certonly \
  --webroot --webroot-path=/var/www/certbot \
  --email your-email@example.com \
  --agree-tos --no-eff-email \
  -d grafana.your-domain.com \
  -d prometheus.your-domain.com \
  -d loki.your-domain.com

# Остановка временного Nginx
docker stop nginx-temp && docker rm nginx-temp

# Теперь запустить основной стек с полным конфигом
docker compose --profile observability up -d
```

#### 6. Автообновление сертификатов

Сервис `certbot` в docker-compose уже настроен на автоматическое обновление каждые 12 часов.

Для ручного обновления:
```bash
docker compose exec certbot certbot renew
docker compose restart nginx
```

#### 7. Проверка безопасности

```bash
# Проверка SSL
curl -I https://grafana.your-domain.com
# Должен вернуть 401 Unauthorized (требуется Basic Auth)

# Проверка Basic Auth
curl -u admin:your_password https://grafana.your-domain.com/api/health
# Должен вернуть {"database":"ok"}

# Проверка прямого доступа (должен быть заблокирован)
curl http://<PUBLIC_IP>:3000
# Connection refused
```

---

### Вариант В: DigitalOcean Cloud Firewall — для минимальной конфигурации

**Описание:**
Использование встроенного firewall DigitalOcean для ограничения доступа по IP-whitelist. Порты остаются на `0.0.0.0`, но доступны только с разрешенных IP.

**Плюсы:**
- ✅ Простота настройки через веб-интерфейс DigitalOcean
- ✅ Не требует изменений в docker-compose.yml
- ✅ Защита на уровне сетевой инфраструктуры (до попадания на сервер)

**Минусы:**
- ❌ Привязка к провайдеру (vendor lock-in)
- ❌ Неудобно для динамических IP (домашний интернет)
- ❌ Нужно обновлять whitelist при смене IP

**Кому подходит:**
Временное решение или когда администратор работает с фиксированного IP (офис, VPN).

**Инструкция:**

#### 1. Создание Cloud Firewall в DigitalOcean

Перейдите в веб-интерфейс DigitalOcean:
1. **Networking → Firewalls → Create Firewall**
2. Название: `who-is-the-spy-observability-fw`

#### 2. Настройка Inbound Rules

**Разрешить SSH (обязательно):**
```
Type: SSH
Protocol: TCP
Port Range: 22
Sources: All IPv4, All IPv6
```

**Разрешить Grafana только с вашего IP:**
```
Type: Custom
Protocol: TCP
Port Range: 3000
Sources: <ВАШ_ПУБЛИЧНЫЙ_IP>/32
```

**Разрешить Prometheus только с вашего IP:**
```
Type: Custom
Protocol: TCP
Port Range: 9090
Sources: <ВАШ_ПУБЛИЧНЫЙ_IP>/32
```

**Разрешить Loki только с вашего IP:**
```
Type: Custom
Protocol: TCP
Port Range: 3100
Sources: <ВАШ_ПУБЛИЧНЫЙ_IP>/32
```

**БЛОКИРОВАТЬ Redis (или разрешить только локально):**
```
Type: Custom
Protocol: TCP
Port Range: 6379
Sources: (не добавлять правило — будет заблокирован)
```

#### 3. Outbound Rules (оставить по умолчанию)

```
Protocol: ICMP, TCP, UDP
Destination: All IPv4, All IPv6
```

#### 4. Применить к Droplet

В разделе **Apply to Droplets** выберите сервер с ботом.

#### 5. Проверка правил

**С вашего IP (должно работать):**
```bash
curl http://<PUBLIC_IP>:3000/api/health
# {"database":"ok"}
```

**С другого IP (Cloudflare, VPN):**
```bash
curl --max-time 5 http://<PUBLIC_IP>:3000
# curl: (28) Connection timed out
```

#### 6. Добавление дополнительных IP

При смене локации/VPN:
1. Узнать текущий публичный IP: `curl ifconfig.me`
2. В DigitalOcean → Firewalls → Edit Inbound Rules
3. Добавить новый IP в Sources для портов 3000, 9090, 3100

#### 7. Автоматизация обновления IP (опционально)

Скрипт для автообновления whitelist через API DigitalOcean:

```bash
#!/bin/bash
# update-fw-ip.sh

FIREWALL_ID="ваш-firewall-id"
DO_TOKEN="ваш-digitalocean-api-token"
CURRENT_IP=$(curl -s ifconfig.me)

curl -X POST "https://api.digitalocean.com/v2/firewalls/$FIREWALL_ID/rules" \
  -H "Authorization: Bearer $DO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "inbound_rules": [
      {
        "protocol": "tcp",
        "ports": "3000",
        "sources": {
          "addresses": ["'$CURRENT_IP'/32"]
        }
      }
    ]
  }'
```

---

## 🔐 Дополнительные меры безопасности

### 1. Защита Redis

**[CONF: HIGH]** Redis должен быть защищен паролем даже при локальном биндинге.

#### Обновление docker-compose.yml

```yaml
redis:
  image: redis:7-alpine
  container_name: who-is-the-spy-redis
  command: redis-server --requirepass ${REDIS_PASSWORD} --appendonly yes
  ports:
    - "127.0.0.1:6379:6379"  # Локальный биндинг
  volumes:
    - redis-data:/data
  restart: unless-stopped

volumes:
  redis-data:
```

#### Обновление .env

```env
REDIS_PASSWORD=<openssl rand -base64 32>
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
```

#### Проверка

```bash
# Без пароля — должна быть ошибка
docker compose exec redis redis-cli PING
# (error) NOAUTH Authentication required.

# С паролем — должно работать
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" PING
# PONG
```

---

### 2. UFW (Uncomplicated Firewall) — дублирование на уровне ОС

**[CONF: MEDIUM]** UFW работает независимо от Cloud Firewall и защищает даже при его отключении.

```bash
# Установка UFW (если не установлен)
sudo apt update && sudo apt install -y ufw

# Дефолтная политика: блокировать входящие, разрешить исходящие
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Разрешить SSH (КРИТИЧНО — не заблокируйте себя!)
sudo ufw allow 22/tcp

# Разрешить порты observability только с вашего IP
sudo ufw allow from <ВАШ_IP> to any port 3000 proto tcp
sudo ufw allow from <ВАШ_IP> to any port 9090 proto tcp
sudo ufw allow from <ВАШ_IP> to any port 3100 proto tcp

# Включение UFW
sudo ufw enable

# Проверка правил
sudo ufw status numbered
```

**Обновление разрешенного IP:**
```bash
# Удалить старое правило (номер из ufw status)
sudo ufw delete 3

# Добавить новое
sudo ufw allow from <НОВЫЙ_IP> to any port 3000 proto tcp
```

---

### 3. Ротация паролей и секретов

#### График ротации (рекомендуется):
- **Grafana пароль:** каждые 90 дней
- **Redis пароль:** каждые 180 дней
- **Telegram BOT_TOKEN:** при компрометации (немедленно через BotFather)
- **OpenAI API_KEY:** при утечке в логах/метриках (немедленно через OpenAI Dashboard)

#### Процедура ротации Grafana

```bash
# 1. Генерация нового пароля
NEW_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
echo "Новый пароль: $NEW_PASSWORD"

# 2. Обновление .env
sed -i "s/GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$NEW_PASSWORD/" .env

# 3. Пересоздание контейнера Grafana
docker compose --profile observability up -d --force-recreate grafana

# 4. Проверка доступа
curl -u admin:$NEW_PASSWORD http://localhost:3000/api/health
```

#### Процедура ротации Redis

```bash
# 1. Генерация нового пароля
NEW_REDIS_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)

# 2. Обновление .env
sed -i "s/REDIS_PASSWORD=.*/REDIS_PASSWORD=$NEW_REDIS_PASSWORD/" .env
sed -i "s|REDIS_URL=.*|REDIS_URL=redis://:$NEW_REDIS_PASSWORD@redis:6379/0|" .env

# 3. Пересоздание Redis (ВНИМАНИЕ: потеря текущих сессий)
docker compose stop bot
docker compose up -d --force-recreate redis
docker compose start bot

# 4. Проверка
docker compose exec redis redis-cli -a "$NEW_REDIS_PASSWORD" PING
```

---

### 4. Мониторинг попыток несанкционированного доступа

#### Логирование Nginx (для Варианта Б)

Добавить в `nginx.conf`:

```nginx
http {
    # Логирование неуспешных Basic Auth
    log_format auth_fail '$remote_addr - $remote_user [$time_local] '
                         '"$request" $status $body_bytes_sent '
                         '"$http_user_agent" auth_failed';

    server {
        # ...
        
        # Логирование 401 ошибок
        access_log /var/log/nginx/auth_failures.log auth_fail if=$auth_fail;
        
        location / {
            set $auth_fail 0;
            if ($status = 401) {
                set $auth_fail 1;
            }
            # ...
        }
    }
}
```

#### Алерты в Prometheus

Файл уже существует: `deploy/observability/prometheus/rules/game-observability-rules.yml`

Добавить правило для мониторинга несанкционированных запросов:

```yaml
groups:
  - name: security_alerts
    interval: 1m
    rules:
      - alert: UnauthorizedAccessAttempt
        expr: rate(nginx_http_requests_total{status="401"}[5m]) > 5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Множественные неуспешные попытки аутентификации"
          description: "Обнаружено {{ $value }} попыток доступа с кодом 401 за последние 5 минут"

      - alert: RedisConnectionSpike
        expr: rate(redis_connected_clients[5m]) > 10
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Подозрительная активность Redis"
          description: "Резкий рост подключений к Redis — возможная атака"
```

#### Fail2Ban (опционально)

Автоматическая блокировка IP после N неуспешных попыток:

```bash
sudo apt install -y fail2ban

# Создать фильтр для Nginx Basic Auth
sudo tee /etc/fail2ban/filter.d/nginx-auth.conf > /dev/null << 'EOF'
[Definition]
failregex = ^<HOST> -.*"(GET|POST).*HTTP.*" 401
ignoreregex =
EOF

# Настроить jail
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

### 5. Backup Strategy для volumes с метриками

#### Автоматический бэкап volumes

Создайте скрипт `/root/backup-observability.sh`:

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/root/backups/observability"
DATE=$(date +%Y%m%d_%H%M%S)
PROJECT_DIR="/root/who_is_the_spy"

mkdir -p "$BACKUP_DIR"

# Остановка сервисов для консистентности данных
cd "$PROJECT_DIR"
docker compose --profile observability stop prometheus loki grafana

# Бэкап volumes через Docker
docker run --rm \
  -v who_is_the_spy_prometheus-data:/source:ro \
  -v "$BACKUP_DIR":/backup \
  alpine tar czf "/backup/prometheus-data-$DATE.tar.gz" -C /source .

docker run --rm \
  -v who_is_the_spy_loki-data:/source:ro \
  -v "$BACKUP_DIR":/backup \
  alpine tar czf "/backup/loki-data-$DATE.tar.gz" -C /source .

docker run --rm \
  -v who_is_the_spy_grafana-data:/source:ro \
  -v "$BACKUP_DIR":/backup \
  alpine tar czf "/backup/grafana-data-$DATE.tar.gz" -C /source .

# Запуск сервисов
docker compose --profile observability start prometheus loki grafana

# Удаление бэкапов старше 30 дней
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete

echo "✅ Backup completed: $DATE"
```

#### Настройка cron

```bash
chmod +x /root/backup-observability.sh

# Добавить в crontab (каждый день в 3:00 AM)
(crontab -l 2>/dev/null; echo "0 3 * * * /root/backup-observability.sh >> /var/log/observability-backup.log 2>&1") | crontab -
```

#### Восстановление из бэкапа

```bash
#!/bin/bash
BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup-file.tar.gz>"
    exit 1
fi

VOLUME_NAME=$(basename "$BACKUP_FILE" | sed 's/-[0-9_]*.tar.gz//')

cd /root/who_is_the_spy
docker compose --profile observability down

docker run --rm \
  -v "who_is_the_spy_$VOLUME_NAME":/target \
  -v "$(dirname $BACKUP_FILE)":/backup \
  alpine sh -c "rm -rf /target/* && tar xzf /backup/$(basename $BACKUP_FILE) -C /target"

docker compose --profile observability up -d
```

---

## 📋 Чеклист перед продакшен-запуском

### Критические пункты (обязательно)

- [ ] Выбран и настроен один из трех вариантов защиты (А, Б или В)
- [ ] Все observability-порты недоступны публично (`curl http://<PUBLIC_IP>:3000` должен отваливаться)
- [ ] Redis защищен паролем и недоступен публично
- [ ] Grafana пароль изменен с дефолтного `admin` на стойкий (минимум 20 символов)
- [ ] UFW настроен и активен (`sudo ufw status` показывает правила)
- [ ] SSH-доступ работает (НЕ заблокируйте себя через UFW)
- [ ] Настроен автоматический бэкап volumes (cron)

### Рекомендуемые пункты

- [ ] SSL-сертификаты установлены и автообновляются (для Варианта Б)
- [ ] Настроен мониторинг попыток несанкционированного доступа (Prometheus alerts)
- [ ] Fail2Ban установлен и настроен (для Варианта Б)
- [ ] График ротации паролей задокументирован
- [ ] Резервный метод доступа протестирован (если основной IP заблокируется)

---

## 🧪 Команды для проверки безопасности

### Проверка биндинга портов

```bash
# На сервере
sudo netstat -tulpn | grep -E ':(3000|9090|3100|6379)'

# Ожидаемый вывод для Варианта А (локальный биндинг):
# tcp  0.0.0.0:3000  127.0.0.1:3000  LISTEN  12345/docker-proxy

# НЕожиданный вывод (ПУБЛИЧНЫЙ биндинг — УЯЗВИМОСТЬ):
# tcp  0.0.0.0:3000  0.0.0.0:3000  LISTEN  12345/docker-proxy
```

### Проверка доступности с внешнего IP

Используйте сервис проверки (с другого сервера/VPN):

```bash
# Эти команды должны ОТВАЛИВАТЬСЯ по таймауту
curl --max-time 5 http://<PUBLIC_IP>:3000
curl --max-time 5 http://<PUBLIC_IP>:9090
curl --max-time 5 http://<PUBLIC_IP>:3100

# Redis-проверка
timeout 5 redis-cli -h <PUBLIC_IP> -p 6379 PING
# Ожидается: timeout (порт недоступен)
```

### Проверка stойкости паролей

```bash
# Длина пароля Grafana (минимум 20 символов)
grep GRAFANA_ADMIN_PASSWORD .env | awk -F'=' '{print length($2)}'

# Длина пароля Redis
grep REDIS_PASSWORD .env | awk -F'=' '{print length($2)}'
```

### Проверка SSL (для Варианта Б)

```bash
# Проверка сертификата
openssl s_client -connect grafana.your-domain.com:443 -servername grafana.your-domain.com < /dev/null | grep "Verify return code"
# Ожидается: Verify return code: 0 (ok)

# Проверка срока действия
echo | openssl s_client -connect grafana.your-domain.com:443 2>/dev/null | openssl x509 -noout -dates
```

### Проверка UFW

```bash
sudo ufw status verbose

# Ожидаемый вывод:
# Status: active
# To                         Action      From
# --                         ------      ----
# 22/tcp                     ALLOW       Anywhere
# 3000/tcp                   ALLOW       <ВАШ_IP>
# 9090/tcp                   ALLOW       <ВАШ_IP>
```

---

## 🚨 Процедуры инцидентной реакции

### Сценарий 1: Обнаружена компрометация Grafana

```bash
# 1. Немедленно остановить Grafana
docker compose stop grafana

# 2. Изменить пароль
NEW_PASSWORD=$(openssl rand -base64 32)
sed -i "s/GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$NEW_PASSWORD/" .env

# 3. Проверить логи на подозрительную активность
docker compose logs grafana | grep -i "login\|auth\|admin"

# 4. Восстановить из бэкапа (если данные изменены)
# См. раздел "Восстановление из бэкапа"

# 5. Запустить с новым паролем
docker compose --profile observability up -d --force-recreate grafana

# 6. Обновить htpasswd (для Варианта Б)
htpasswd -b /root/who_is_the_spy/deploy/nginx/.htpasswd admin "$NEW_PASSWORD"
docker compose restart nginx
```

### Сценарий 2: Атака на Redis

```bash
# 1. Проверить подключения
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" CLIENT LIST

# 2. Убить подозрительные подключения
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" CLIENT KILL ID <client-id>

# 3. Изменить пароль Redis (см. раздел "Ротация паролей")

# 4. Проверить, что порт закрыт публично
sudo netstat -tulpn | grep 6379
# Должен быть биндинг на 127.0.0.1, НЕ на 0.0.0.0
```

### Сценарий 3: Утечка OpenAI API ключа в логах

```bash
# 1. Немедленно отозвать ключ в OpenAI Dashboard
# https://platform.openai.com/api-keys

# 2. Создать новый ключ

# 3. Обновить .env
sed -i "s/OPENAI_API_KEY=.*/OPENAI_API_KEY=sk-новый-ключ/" .env

# 4. Перезапустить бота
docker compose restart bot

# 5. Очистить логи с старым ключом
docker compose logs bot > /dev/null 2>&1
docker compose exec loki rm -rf /loki/chunks/*
docker compose restart loki
```

---

## 📊 Сравнительная таблица вариантов

| Критерий | Вариант А (SSH) | Вариант Б (Nginx) | Вариант В (Cloud FW) |
|---|---|---|---|
| **Сложность настройки** | ⭐ Низкая | ⭐⭐⭐ Высокая | ⭐⭐ Средняя |
| **Требования** | SSH-ключ | Домен + DNS + SSL | DigitalOcean аккаунт |
| **Многопользовательский доступ** | ❌ Один туннель | ✅ Неограничено | ⚠️ Только с whitelist IP |
| **SSL-шифрование** | ✅ В SSH | ✅ Let's Encrypt | ❌ Нет |
| **Vendor lock-in** | ✅ Нет | ✅ Нет | ❌ Да (DigitalOcean) |
| **Защита от brute-force** | ✅ SSH ключи | ✅ Fail2Ban + rate limit | ⚠️ Зависит от UFW |
| **Удобство для команды** | ❌ Низкое | ✅ Высокое | ⚠️ Среднее |
| **Стоимость** | $0 | $0 (Let's Encrypt) | $0 (встроено в DO) |
| **Recommended use case** | Один админ | Распределенная команда | Временное решение |

---

## 📞 Контрольный список после настройки

После завершения настройки любого варианта выполните:

```bash
# 1. Проверка основного функционала бота
# В личке Telegram:
/start
/testpair

# 2. Проверка observability
# Откройте Grafana (через туннель/домен)
# - Data Sources: Prometheus + Loki должны быть зеленые
# - Dashboard: откройте "Game KPI & Runtime"
# - Query Prometheus: up{job="bot"}

# 3. Проверка безопасности
curl --max-time 5 http://<PUBLIC_IP>:3000  # Должен отвалиться
nmap -p 3000,9090,3100,6379 <PUBLIC_IP>     # Все порты filtered/closed

# 4. Проверка бэкапов
ls -lh /root/backups/observability/

# 5. Документирование
# Сохраните в безопасном месте:
# - Пароль Grafana (из .env)
# - Пароль Redis (из .env)
# - Пароль htpasswd (для Варианта Б)
# - IP-whitelist (для Варианта В)
```

---

**[CONF: HIGH]** Все рекомендации основаны на OWASP Top 10, CIS Docker Benchmark и best practices для продакшен-развертывания observability-стеков.

**Дата составления:** 2026-05-07  
**Ревизия:** 1.0  
**Следующий пересмотр:** 2026-08-07 (через 3 месяца)
