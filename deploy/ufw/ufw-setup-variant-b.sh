#!/bin/bash
# UFW конфигурация для Варианта Б (Nginx Reverse Proxy с SSL)
# 📚 Что здесь происходит:
# Nginx выступает единой точкой входа через порты 80 (HTTP) и 443 (HTTPS).
# Все observability-сервисы биндятся на 127.0.0.1 и доступны только через Nginx.
# Basic Auth и SSL обеспечивают защиту на уровне приложения,
# а UFW — дополнительный уровень на сетевом уровне.

set -euo pipefail

echo "🔒 Настройка UFW для Варианта Б (Nginx Reverse Proxy)"
echo ""

# Установка UFW если не установлен
if ! command -v ufw &> /dev/null; then
    echo "Установка UFW..."
    sudo apt update && sudo apt install -y ufw
fi

# Дефолтные правила
sudo ufw --force default deny incoming
sudo ufw --force default allow outgoing

# Разрешить SSH
sudo ufw allow 22/tcp comment 'SSH access'

# 📚 Порт 80 (HTTP) нужен для:
# - Let's Encrypt ACME challenge (получение SSL-сертификатов)
# - Редирект на HTTPS
sudo ufw allow 80/tcp comment 'HTTP for Let\'s Encrypt and redirect'

# 📚 Порт 443 (HTTPS) — основной вход для:
# - Grafana (через grafana.your-domain.com)
# - Prometheus (через prometheus.your-domain.com)
# - Loki (через loki.your-domain.com)
sudo ufw allow 443/tcp comment 'HTTPS for Nginx reverse proxy'

# 📚 Observability-порты (3000, 9090, 3100, 6379) НЕ открываются,
# так как они биндятся на 127.0.0.1 и доступны только через Nginx.
# Это гарантирует, что обход Basic Auth/SSL невозможен.

echo ""
echo "Текущие правила UFW:"
sudo ufw show added
echo ""

read -p "⚠️  ВНИМАНИЕ: После активации UFW убедитесь, что SSH работает! Продолжить? (y/n): " CONFIRM

if [ "$CONFIRM" != "y" ]; then
    echo "Отменено"
    exit 0
fi

# Активация UFW
sudo ufw --force enable

echo ""
echo "✅ UFW настроен и активирован для Варианта Б"
echo ""
echo "Текущий статус:"
sudo ufw status verbose
echo ""
echo "📋 Проверка:"
echo "1. SSH-доступ должен работать: ssh root@<PUBLIC_IP>"
echo "2. HTTP доступен (для Let's Encrypt): curl http://<PUBLIC_IP>"
echo "3. HTTPS доступен: curl https://grafana.your-domain.com"
echo "4. Прямой доступ к Grafana заблокирован: curl http://<PUBLIC_IP>:3000 (timeout)"
echo ""
