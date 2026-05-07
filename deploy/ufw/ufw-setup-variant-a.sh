#!/bin/bash
# UFW конфигурация для Варианта А (SSH-туннель)
# 📚 Что здесь происходит:
# При локальном биндинге портов (127.0.0.1) observability-сервисы недоступны извне.
# UFW блокирует весь входящий трафик, кроме SSH для администрирования.
# Доступ к метрикам/логам осуществляется через SSH-туннель.

set -euo pipefail

echo "🔒 Настройка UFW для Варианта А (SSH-туннель)"
echo ""

# Установка UFW если не установлен
if ! command -v ufw &> /dev/null; then
    echo "Установка UFW..."
    sudo apt update && sudo apt install -y ufw
fi

# Дефолтные правила: блокировать входящие, разрешить исходящие
sudo ufw --force default deny incoming
sudo ufw --force default allow outgoing

# ⚠️  КРИТИЧНО: Разрешить SSH, иначе потеряете доступ к серверу
sudo ufw allow 22/tcp comment 'SSH access'

# 📚 Observability-порты (3000, 9090, 3100, 6379) НЕ добавляются в правила,
# так как они биндятся на 127.0.0.1 и недоступны извне по умолчанию.
# Это дополнительный уровень защиты: даже если биндинг сломается,
# UFW заблокирует доступ.

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
echo "✅ UFW настроен и активирован для Варианта А"
echo ""
echo "Текущий статус:"
sudo ufw status verbose
echo ""
echo "📋 Проверка:"
echo "1. SSH-доступ должен работать: ssh root@<PUBLIC_IP>"
echo "2. Observability-порты заблокированы извне (биндинг на 127.0.0.1)"
echo "3. Доступ к Grafana через SSH-туннель:"
echo "   ssh -L 3000:127.0.0.1:3000 root@<PUBLIC_IP>"
echo "   Затем открыть: http://localhost:3000"
echo ""
