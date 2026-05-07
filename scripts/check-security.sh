#!/bin/bash
# Скрипт проверки безопасности продакшен-развертывания
# Использование: bash scripts/check-security.sh

set -euo pipefail

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAIL_COUNT=0
PASS_COUNT=0
WARN_COUNT=0

function check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASS_COUNT++))
}

function check_fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAIL_COUNT++))
}

function check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARN_COUNT++))
}

echo "=========================================="
echo "🔒 Проверка безопасности Who Is The Spy"
echo "=========================================="
echo ""

# ============================================================
# 1. Проверка биндинга портов
# ============================================================

echo "1️⃣  Проверка биндинга портов..."
echo ""

GRAFANA_BIND=$(sudo netstat -tulpn 2>/dev/null | grep ":3000" | head -n1 || echo "")
PROMETHEUS_BIND=$(sudo netstat -tulpn 2>/dev/null | grep ":9090" | head -n1 || echo "")
LOKI_BIND=$(sudo netstat -tulpn 2>/dev/null | grep ":3100" | head -n1 || echo "")
REDIS_BIND=$(sudo netstat -tulpn 2>/dev/null | grep ":6379" | head -n1 || echo "")

if echo "$GRAFANA_BIND" | grep -q "127.0.0.1:3000"; then
    check_pass "Grafana биндится на 127.0.0.1 (безопасно)"
elif echo "$GRAFANA_BIND" | grep -q "0.0.0.0:3000"; then
    check_fail "Grafana биндится на 0.0.0.0 (ПУБЛИЧНО ДОСТУПЕН)"
else
    check_warn "Grafana порт 3000 не найден (контейнер не запущен?)"
fi

if echo "$PROMETHEUS_BIND" | grep -q "127.0.0.1:9090"; then
    check_pass "Prometheus биндится на 127.0.0.1 (безопасно)"
elif echo "$PROMETHEUS_BIND" | grep -q "0.0.0.0:9090"; then
    check_fail "Prometheus биндится на 0.0.0.0 (ПУБЛИЧНО ДОСТУПЕН)"
else
    check_warn "Prometheus порт 9090 не найден (контейнер не запущен?)"
fi

if echo "$LOKI_BIND" | grep -q "127.0.0.1:3100"; then
    check_pass "Loki биндится на 127.0.0.1 (безопасно)"
elif echo "$LOKI_BIND" | grep -q "0.0.0.0:3100"; then
    check_fail "Loki биндится на 0.0.0.0 (ПУБЛИЧНО ДОСТУПЕН)"
else
    check_warn "Loki порт 3100 не найден (контейнер не запущен?)"
fi

if echo "$REDIS_BIND" | grep -q "127.0.0.1:6379"; then
    check_pass "Redis биндится на 127.0.0.1 (безопасно)"
elif echo "$REDIS_BIND" | grep -q "0.0.0.0:6379"; then
    check_fail "Redis биндится на 0.0.0.0 (КРИТИЧЕСКАЯ УЯЗВИМОСТЬ)"
else
    check_warn "Redis порт 6379 не найден (контейнер не запущен?)"
fi

echo ""

# ============================================================
# 2. Проверка паролей
# ============================================================

echo "2️⃣  Проверка стойкости паролей..."
echo ""

ENV_FILE="/root/who_is_the_spy/.env"

if [ ! -f "$ENV_FILE" ]; then
    check_fail ".env файл не найден"
else
    # Проверка Grafana пароля
    GRAFANA_PASSWORD=$(grep "^GRAFANA_ADMIN_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2 || echo "")
    if [ -z "$GRAFANA_PASSWORD" ]; then
        check_fail "GRAFANA_ADMIN_PASSWORD не задан в .env"
    elif [ "$GRAFANA_PASSWORD" == "admin" ]; then
        check_fail "GRAFANA_ADMIN_PASSWORD использует дефолтное значение 'admin' (КРИТИЧНО)"
    elif [ ${#GRAFANA_PASSWORD} -lt 20 ]; then
        check_warn "GRAFANA_ADMIN_PASSWORD короче 20 символов (текущая длина: ${#GRAFANA_PASSWORD})"
    else
        check_pass "GRAFANA_ADMIN_PASSWORD достаточно стойкий (длина: ${#GRAFANA_PASSWORD})"
    fi
    
    # Проверка Redis пароля
    REDIS_PASSWORD=$(grep "^REDIS_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2 || echo "")
    if [ -z "$REDIS_PASSWORD" ]; then
        check_fail "REDIS_PASSWORD не задан в .env (Redis без пароля)"
    elif [ ${#REDIS_PASSWORD} -lt 20 ]; then
        check_warn "REDIS_PASSWORD короче 20 символов (текущая длина: ${#REDIS_PASSWORD})"
    else
        check_pass "REDIS_PASSWORD достаточно стойкий (длина: ${#REDIS_PASSWORD})"
    fi
    
    # Проверка REDIS_URL
    REDIS_URL=$(grep "^REDIS_URL=" "$ENV_FILE" | cut -d'=' -f2 || echo "")
    if echo "$REDIS_URL" | grep -q "redis://:.*@"; then
        check_pass "REDIS_URL настроен с паролем"
    else
        check_fail "REDIS_URL не содержит пароль"
    fi
fi

echo ""

# ============================================================
# 3. Проверка UFW
# ============================================================

echo "3️⃣  Проверка UFW (Uncomplicated Firewall)..."
echo ""

if ! command -v ufw &> /dev/null; then
    check_fail "UFW не установлен"
else
    UFW_STATUS=$(sudo ufw status | head -n1)
    if echo "$UFW_STATUS" | grep -q "Status: active"; then
        check_pass "UFW активен"
        
        # Проверка правил SSH
        if sudo ufw status | grep -q "22/tcp.*ALLOW"; then
            check_pass "SSH доступ разрешен (порт 22)"
        else
            check_warn "SSH доступ не найден в правилах UFW"
        fi
        
        # Проверка observability портов
        if sudo ufw status | grep -qE "(3000|9090|3100).*ALLOW"; then
            check_warn "Обнаружены открытые observability-порты в UFW (убедитесь, что используется whitelist)"
        else
            check_pass "Observability-порты не открыты в UFW (защищены локальным биндингом)"
        fi
        
    else
        check_fail "UFW не активен"
    fi
fi

echo ""

# ============================================================
# 4. Проверка доступности извне (если есть публичный IP)
# ============================================================

echo "4️⃣  Проверка публичной доступности..."
echo ""

# Попытка определить публичный IP
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me || echo "")

if [ -z "$PUBLIC_IP" ]; then
    check_warn "Не удалось определить публичный IP (нет интернета или за NAT)"
else
    echo "   Публичный IP: $PUBLIC_IP"
    
    # Проверка Grafana
    if curl -s --max-time 3 "http://$PUBLIC_IP:3000" > /dev/null 2>&1; then
        check_fail "Grafana ДОСТУПЕН по публичному IP (http://$PUBLIC_IP:3000)"
    else
        check_pass "Grafana недоступен по публичному IP"
    fi
    
    # Проверка Prometheus
    if curl -s --max-time 3 "http://$PUBLIC_IP:9090" > /dev/null 2>&1; then
        check_fail "Prometheus ДОСТУПЕН по публичному IP (http://$PUBLIC_IP:9090)"
    else
        check_pass "Prometheus недоступен по публичному IP"
    fi
    
    # Проверка Redis
    if timeout 3 bash -c "echo -e '*1\r\n\$4\r\nPING\r\n' | nc $PUBLIC_IP 6379" > /dev/null 2>&1; then
        check_fail "Redis ДОСТУПЕН по публичному IP (КРИТИЧЕСКАЯ УЯЗВИМОСТЬ)"
    else
        check_pass "Redis недоступен по публичному IP"
    fi
fi

echo ""

# ============================================================
# 5. Проверка Docker volumes бэкапов
# ============================================================

echo "5️⃣  Проверка бэкапов volumes..."
echo ""

if [ -f "/root/backup-observability.sh" ]; then
    check_pass "Скрипт бэкапа найден: /root/backup-observability.sh"
    
    if crontab -l 2>/dev/null | grep -q "backup-observability.sh"; then
        check_pass "Cron job для автоматических бэкапов настроен"
    else
        check_warn "Cron job для бэкапов не найден"
    fi
    
    BACKUP_DIR="/root/backups/observability"
    if [ -d "$BACKUP_DIR" ]; then
        BACKUP_COUNT=$(find "$BACKUP_DIR" -name "*.tar.gz" 2>/dev/null | wc -l)
        if [ "$BACKUP_COUNT" -gt 0 ]; then
            check_pass "Найдено $BACKUP_COUNT бэкапов в $BACKUP_DIR"
            LATEST_BACKUP=$(find "$BACKUP_DIR" -name "*.tar.gz" -printf '%T+ %p\n' 2>/dev/null | sort -r | head -n1 | awk '{print $2}')
            echo "   Последний бэкап: $(basename $LATEST_BACKUP)"
        else
            check_warn "Бэкапы не найдены в $BACKUP_DIR (скрипт еще не запускался?)"
        fi
    else
        check_warn "Директория бэкапов не найдена: $BACKUP_DIR"
    fi
else
    check_warn "Скрипт бэкапа не найден (рекомендуется настроить)"
fi

echo ""

# ============================================================
# 6. Проверка Docker контейнеров
# ============================================================

echo "6️⃣  Проверка Docker контейнеров..."
echo ""

if docker ps --format "{{.Names}}" | grep -q "who-is-the-spy-redis"; then
    check_pass "Контейнер Redis запущен"
    
    # Проверка Redis аутентификации
    if docker exec who-is-the-spy-redis redis-cli PING 2>&1 | grep -q "NOAUTH"; then
        check_pass "Redis требует аутентификацию (безопасно)"
    elif docker exec who-is-the-spy-redis redis-cli PING 2>&1 | grep -q "PONG"; then
        check_fail "Redis НЕ требует аутентификацию (пароль не установлен)"
    fi
else
    check_warn "Контейнер Redis не запущен"
fi

if docker ps --format "{{.Names}}" | grep -q "who-is-the-spy-grafana"; then
    check_pass "Контейнер Grafana запущен"
else
    check_warn "Контейнер Grafana не запущен (observability профиль не активен?)"
fi

if docker ps --format "{{.Names}}" | grep -q "who-is-the-spy-prometheus"; then
    check_pass "Контейнер Prometheus запущен"
else
    check_warn "Контейнер Prometheus не запущен (observability профиль не активен?)"
fi

echo ""

# ============================================================
# 7. Проверка Nginx (если используется)
# ============================================================

echo "7️⃣  Проверка Nginx Reverse Proxy..."
echo ""

if docker ps --format "{{.Names}}" | grep -q "who-is-the-spy-nginx"; then
    check_pass "Контейнер Nginx запущен"
    
    # Проверка htpasswd
    if [ -f "/root/who_is_the_spy/deploy/nginx/.htpasswd" ]; then
        check_pass "Файл .htpasswd найден (Basic Auth настроен)"
    else
        check_warn "Файл .htpasswd не найден"
    fi
    
    # Проверка SSL сертификатов
    SSL_DIR="/root/who_is_the_spy/deploy/nginx/ssl/live"
    if [ -d "$SSL_DIR" ] && [ "$(ls -A $SSL_DIR 2>/dev/null)" ]; then
        check_pass "SSL-сертификаты найдены"
    else
        check_warn "SSL-сертификаты не найдены (требуется настройка Let's Encrypt)"
    fi
else
    check_warn "Nginx не используется (Вариант А или В выбран)"
fi

echo ""

# ============================================================
# Итоговый отчет
# ============================================================

echo "=========================================="
echo "📊 Итоговый отчет"
echo "=========================================="
echo ""
echo -e "${GREEN}✓ Пройдено:${NC} $PASS_COUNT"
echo -e "${YELLOW}⚠ Предупреждений:${NC} $WARN_COUNT"
echo -e "${RED}✗ Ошибок:${NC} $FAIL_COUNT"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}✅ Безопасность настроена корректно!${NC}"
    exit 0
elif [ $FAIL_COUNT -le 2 ]; then
    echo -e "${YELLOW}⚠️  Обнаружены некритичные проблемы безопасности${NC}"
    echo "Рекомендуется исправить их перед продакшен-запуском"
    exit 1
else
    echo -e "${RED}🚨 КРИТИЧЕСКИЕ ПРОБЛЕМЫ БЕЗОПАСНОСТИ!${NC}"
    echo "НЕ запускайте в продакшене без исправления!"
    exit 2
fi
