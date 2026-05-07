#!/bin/bash
# UFW конфигурация для Варианта В (DigitalOcean Cloud Firewall + IP-whitelist)
# 📚 Что здесь происходит:
# UFW дублирует защиту Cloud Firewall на уровне ОС.
# Если Cloud Firewall будет случайно отключен, UFW продолжит защиту.
# Observability-порты открыты только для разрешенных IP (whitelist).

set -euo pipefail

echo "🔒 Настройка UFW для Варианта В (Cloud Firewall + Whitelist)"
echo ""

# Запрос IP для whitelist
read -p "Введите ваш публичный IP для whitelist (например, 203.0.113.42): " WHITELIST_IP

if [ -z "$WHITELIST_IP" ]; then
    echo "❌ IP не указан"
    exit 1
fi

echo ""
echo "Текущий публичный IP вашей машины:"
curl -s ifconfig.me
echo ""

read -p "Использовать автоопределенный IP выше? (y/n): " USE_AUTO_IP
if [ "$USE_AUTO_IP" == "y" ]; then
    WHITELIST_IP=$(curl -s ifconfig.me)
    echo "Используется IP: $WHITELIST_IP"
fi

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

# 📚 Grafana (порт 3000) — только с whitelist IP
# Basic Auth в Grafana дает дополнительную защиту,
# но первый уровень — блокировка на сетевом уровне.
sudo ufw allow from "$WHITELIST_IP" to any port 3000 proto tcp comment 'Grafana whitelist'

# 📚 Prometheus (порт 9090) — только с whitelist IP
# Prometheus не имеет встроенной аутентификации,
# поэтому блокировка по IP — единственная защита.
sudo ufw allow from "$WHITELIST_IP" to any port 9090 proto tcp comment 'Prometheus whitelist'

# 📚 Loki (порт 3100) — только с whitelist IP
# Обычно Loki используется только через Grafana,
# но на всякий случай разрешаем прямой доступ.
sudo ufw allow from "$WHITELIST_IP" to any port 3100 proto tcp comment 'Loki whitelist'

# ⚠️  Redis (порт 6379) НЕ открывается ни для кого
# Redis должен быть доступен только с локального хоста (127.0.0.1)
echo "⚠️  Redis порт 6379 не добавлен в правила (должен быть закрыт публично)"

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
echo "✅ UFW настроен и активирован для Варианта В"
echo ""
echo "Текущий статус:"
sudo ufw status verbose
echo ""
echo "📋 Проверка:"
echo "1. SSH-доступ должен работать: ssh root@<PUBLIC_IP>"
echo "2. Grafana доступен с вашего IP: curl http://<PUBLIC_IP>:3000/api/health"
echo "3. Grafana заблокирован с других IP (используйте VPN для проверки)"
echo ""
echo "📝 Для добавления нового IP выполните:"
echo "   sudo ufw allow from <NEW_IP> to any port 3000 proto tcp"
echo "   sudo ufw allow from <NEW_IP> to any port 9090 proto tcp"
echo "   sudo ufw allow from <NEW_IP> to any port 3100 proto tcp"
echo ""
echo "📝 Для удаления старого IP:"
echo "   sudo ufw status numbered"
echo "   sudo ufw delete <НОМЕР_ПРАВИЛА>"
echo ""
