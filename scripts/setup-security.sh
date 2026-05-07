#!/bin/bash
# Интерактивный скрипт установки безопасности для who_is_the_spy
# Использование: sudo bash scripts/setup-security.sh

set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Проверка прав root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}❌ Этот скрипт должен запускаться с правами root (sudo)${NC}"
   exit 1
fi

echo "=========================================="
echo "🔒 Настройка безопасности Who Is The Spy"
echo "=========================================="
echo ""

# ============================================================
# Шаг 1: Выбор варианта защиты
# ============================================================

echo -e "${YELLOW}Выберите вариант защиты observability-стека:${NC}"
echo ""
echo "1) Вариант А: SSH-туннель (локальный биндинг портов)"
echo "   - Простая настройка"
echo "   - Для одного администратора"
echo "   - Доступ через SSH-туннель"
echo ""
echo "2) Вариант Б: Nginx Reverse Proxy с SSL и Basic Auth"
echo "   - Сложная настройка"
echo "   - Для команды разработчиков"
echo "   - Требуется домен и DNS"
echo ""
echo "3) Вариант В: DigitalOcean Cloud Firewall"
echo "   - Средняя сложность"
echo "   - Настройка через веб-интерфейс DO"
echo "   - IP-whitelist"
echo ""
read -p "Введите номер варианта (1/2/3): " VARIANT

# ============================================================
# Шаг 2: Генерация стойких паролей
# ============================================================

echo ""
echo -e "${GREEN}✓${NC} Генерация стойких паролей..."

REDIS_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)

echo ""
echo -e "${YELLOW}Сгенерированные пароли (сохраните их в безопасном месте):${NC}"
echo "REDIS_PASSWORD: $REDIS_PASSWORD"
echo "GRAFANA_ADMIN_PASSWORD: $GRAFANA_ADMIN_PASSWORD"
echo ""

# ============================================================
# Шаг 3: Обновление .env
# ============================================================

PROJECT_DIR="/root/who_is_the_spy"
ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}⚠${NC} Файл .env не найден, создаем из .env.example..."
    cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
fi

echo -e "${GREEN}✓${NC} Обновление .env с новыми паролями..."

# Обновление или добавление переменных
if grep -q "^REDIS_PASSWORD=" "$ENV_FILE"; then
    sed -i "s/^REDIS_PASSWORD=.*/REDIS_PASSWORD=$REDIS_PASSWORD/" "$ENV_FILE"
else
    echo "REDIS_PASSWORD=$REDIS_PASSWORD" >> "$ENV_FILE"
fi

if grep -q "^GRAFANA_ADMIN_PASSWORD=" "$ENV_FILE"; then
    sed -i "s/^GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD/" "$ENV_FILE"
else
    echo "GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD" >> "$ENV_FILE"
fi

# Обновление REDIS_URL для использования пароля
sed -i "s|^REDIS_URL=.*|REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0|" "$ENV_FILE"

# ============================================================
# Шаг 4: Настройка UFW (Universal Firewall)
# ============================================================

echo ""
echo -e "${GREEN}✓${NC} Настройка UFW..."

# Установка UFW если не установлен
if ! command -v ufw &> /dev/null; then
    echo "Установка UFW..."
    apt update && apt install -y ufw
fi

# Дефолтные правила
ufw --force default deny incoming
ufw --force default allow outgoing

# Разрешить SSH (КРИТИЧНО!)
ufw allow 22/tcp comment 'SSH access'

if [ "$VARIANT" == "1" ]; then
    # Вариант А: все observability-порты блокируются извне (биндинг на 127.0.0.1)
    echo -e "${GREEN}✓${NC} Вариант А выбран — observability-порты будут биндиться на 127.0.0.1"
    
elif [ "$VARIANT" == "2" ]; then
    # Вариант Б: разрешить HTTP/HTTPS для Nginx
    ufw allow 80/tcp comment 'HTTP for Let\'s Encrypt'
    ufw allow 443/tcp comment 'HTTPS for Nginx'
    echo -e "${GREEN}✓${NC} Вариант Б выбран — разрешены порты 80 и 443 для Nginx"
    
elif [ "$VARIANT" == "3" ]; then
    # Вариант В: запросить IP для whitelist
    echo ""
    read -p "Введите ваш публичный IP для whitelist (например, 203.0.113.42): " WHITELIST_IP
    
    ufw allow from "$WHITELIST_IP" to any port 3000 proto tcp comment 'Grafana whitelist'
    ufw allow from "$WHITELIST_IP" to any port 9090 proto tcp comment 'Prometheus whitelist'
    ufw allow from "$WHITELIST_IP" to any port 3100 proto tcp comment 'Loki whitelist'
    
    echo -e "${GREEN}✓${NC} Вариант В выбран — whitelist настроен для IP: $WHITELIST_IP"
    echo -e "${YELLOW}⚠${NC} Не забудьте также настроить DigitalOcean Cloud Firewall!"
fi

# Включение UFW
ufw --force enable

echo ""
echo -e "${GREEN}✓${NC} UFW настроен и активирован"
ufw status numbered

# ============================================================
# Шаг 5: Выбор docker-compose файла и запуск
# ============================================================

echo ""
echo -e "${YELLOW}Какой docker-compose использовать?${NC}"
echo "1) docker-compose.secure.yml (рекомендуется — с безопасными настройками)"
echo "2) docker-compose.yml (дефолтный — требует ручного редактирования)"
read -p "Введите номер (1/2): " COMPOSE_CHOICE

cd "$PROJECT_DIR"

if [ "$COMPOSE_CHOICE" == "1" ]; then
    COMPOSE_FILE="docker-compose.secure.yml"
    echo -e "${GREEN}✓${NC} Используется $COMPOSE_FILE"
else
    COMPOSE_FILE="docker-compose.yml"
    echo -e "${YELLOW}⚠${NC} Используется дефолтный docker-compose.yml"
    echo -e "${YELLOW}⚠${NC} Рекомендуется вручную изменить биндинг портов на 127.0.0.1:PORT:PORT"
fi

echo ""
read -p "Запустить observability-стек сейчас? (y/n): " START_NOW

if [ "$START_NOW" == "y" ]; then
    echo -e "${GREEN}✓${NC} Запуск контейнеров..."
    docker compose -f "$COMPOSE_FILE" --profile observability down
    docker compose -f "$COMPOSE_FILE" --profile observability up -d --build
    
    echo ""
    echo -e "${GREEN}✓${NC} Контейнеры запущены. Статус:"
    docker compose -f "$COMPOSE_FILE" ps
fi

# ============================================================
# Шаг 6: Настройка Nginx (только для Варианта Б)
# ============================================================

if [ "$VARIANT" == "2" ]; then
    echo ""
    echo -e "${YELLOW}Настройка Nginx и SSL-сертификатов${NC}"
    
    read -p "Введите ваш домен для Grafana (например, grafana.example.com): " GRAFANA_DOMAIN
    read -p "Введите ваш email для Let's Encrypt: " CERTBOT_EMAIL
    
    # Создание htpasswd
    echo ""
    echo "Создание пользователя для Basic Auth..."
    apt install -y apache2-utils
    mkdir -p "$PROJECT_DIR/deploy/nginx"
    
    read -p "Введите имя пользователя для Basic Auth: " HTPASSWD_USER
    htpasswd -c "$PROJECT_DIR/deploy/nginx/.htpasswd" "$HTPASSWD_USER"
    
    # Замена your-domain.com в nginx.conf
    sed -i "s/your-domain.com/$GRAFANA_DOMAIN/g" "$PROJECT_DIR/deploy/nginx/nginx.conf"
    
    echo ""
    echo -e "${YELLOW}⚠${NC} Для получения SSL-сертификатов выполните следующие команды:"
    echo ""
    echo "cd $PROJECT_DIR"
    echo "# Создайте временный Nginx для ACME challenge"
    echo "docker run -d --name nginx-temp -p 80:80 -v \$(pwd)/deploy/nginx/ssl:/etc/letsencrypt -v certbot-webroot:/var/www/certbot nginx:1.27-alpine"
    echo ""
    echo "# Получите сертификаты"
    echo "docker run --rm -v \$(pwd)/deploy/nginx/ssl:/etc/letsencrypt -v certbot-webroot:/var/www/certbot certbot/certbot:v3.0.1 certonly --webroot --webroot-path=/var/www/certbot --email $CERTBOT_EMAIL --agree-tos -d $GRAFANA_DOMAIN"
    echo ""
    echo "# Остановите временный Nginx и запустите основной стек"
    echo "docker stop nginx-temp && docker rm nginx-temp"
    echo "docker compose -f $COMPOSE_FILE --profile observability up -d"
fi

# ============================================================
# Шаг 7: Настройка автоматических бэкапов
# ============================================================

echo ""
read -p "Настроить автоматические бэкапы volumes? (y/n): " SETUP_BACKUP

if [ "$SETUP_BACKUP" == "y" ]; then
    echo -e "${GREEN}✓${NC} Создание скрипта бэкапа..."
    
    mkdir -p /root/backups/observability
    
    cat > /root/backup-observability.sh << 'BACKUP_SCRIPT'
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/root/backups/observability"
DATE=$(date +%Y%m%d_%H%M%S)
PROJECT_DIR="/root/who_is_the_spy"

mkdir -p "$BACKUP_DIR"

cd "$PROJECT_DIR"
docker compose --profile observability stop prometheus loki grafana

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

docker compose --profile observability start prometheus loki grafana

find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete

echo "✅ Backup completed: $DATE"
BACKUP_SCRIPT

    chmod +x /root/backup-observability.sh
    
    # Добавление в crontab
    (crontab -l 2>/dev/null | grep -v backup-observability.sh; echo "0 3 * * * /root/backup-observability.sh >> /var/log/observability-backup.log 2>&1") | crontab -
    
    echo -e "${GREEN}✓${NC} Скрипт бэкапа создан: /root/backup-observability.sh"
    echo -e "${GREEN}✓${NC} Cron job добавлен: ежедневно в 3:00 AM"
fi

# ============================================================
# Финальная проверка
# ============================================================

echo ""
echo "=========================================="
echo -e "${GREEN}✅ Настройка безопасности завершена!${NC}"
echo "=========================================="
echo ""
echo "📋 Чеклист для проверки:"
echo ""
echo "1. Проверьте доступность с сервера:"
echo "   curl http://localhost:3000/api/health"
echo ""
echo "2. Проверьте недоступность извне (с другого компьютера):"
echo "   curl --max-time 5 http://<PUBLIC_IP>:3000"
echo "   (должен отвалиться по таймауту)"
echo ""
echo "3. Проверьте статус UFW:"
echo "   sudo ufw status numbered"
echo ""
echo "4. Проверьте контейнеры:"
echo "   docker compose -f $COMPOSE_FILE ps"
echo ""
echo "5. Сохраните пароли в безопасном месте:"
echo "   GRAFANA: $GRAFANA_ADMIN_PASSWORD"
echo "   REDIS: $REDIS_PASSWORD"
echo ""

if [ "$VARIANT" == "1" ]; then
    echo "6. Настройте SSH-туннель с локальной машины:"
    echo "   ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 root@<PUBLIC_IP>"
    echo ""
fi

echo "📖 Полная документация: $PROJECT_DIR/docs/SECURITY.md"
echo ""
