#!/bin/bash
# Скрипт ротации паролей для продакшен-инфраструктуры
# Использование: sudo bash scripts/rotate-passwords.sh [grafana|redis|all]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_DIR="/root/who_is_the_spy"
ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}❌ Файл .env не найден: $ENV_FILE${NC}"
    exit 1
fi

TARGET="${1:-all}"

function rotate_grafana() {
    echo ""
    echo -e "${YELLOW}🔄 Ротация пароля Grafana...${NC}"
    
    NEW_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
    
    echo "Новый пароль Grafana: $NEW_PASSWORD"
    echo -e "${YELLOW}⚠  Сохраните этот пароль в безопасном месте!${NC}"
    
    read -p "Продолжить ротацию? (y/n): " CONFIRM
    if [ "$CONFIRM" != "y" ]; then
        echo "Отменено"
        return
    fi
    
    # Обновление .env
    sed -i.backup "s/^GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$NEW_PASSWORD/" "$ENV_FILE"
    
    # Пересоздание контейнера Grafana
    cd "$PROJECT_DIR"
    docker compose --profile observability up -d --force-recreate grafana
    
    # Проверка
    sleep 5
    if curl -u admin:"$NEW_PASSWORD" -s http://localhost:3000/api/health | grep -q "ok"; then
        echo -e "${GREEN}✓${NC} Пароль Grafana успешно изменен"
    else
        echo -e "${RED}✗${NC} Ошибка при проверке нового пароля"
        echo "Восстановление из .env.backup..."
        mv "$ENV_FILE.backup" "$ENV_FILE"
        docker compose --profile observability up -d --force-recreate grafana
    fi
    
    # Обновление htpasswd (если используется Nginx)
    if [ -f "$PROJECT_DIR/deploy/nginx/.htpasswd" ]; then
        echo ""
        echo -e "${YELLOW}Обновление htpasswd для Nginx...${NC}"
        htpasswd -b "$PROJECT_DIR/deploy/nginx/.htpasswd" admin "$NEW_PASSWORD"
        docker compose restart nginx 2>/dev/null || true
        echo -e "${GREEN}✓${NC} htpasswd обновлен"
    fi
}

function rotate_redis() {
    echo ""
    echo -e "${YELLOW}🔄 Ротация пароля Redis...${NC}"
    echo -e "${RED}⚠  ВНИМАНИЕ: Все активные игровые сессии будут потеряны!${NC}"
    
    NEW_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
    
    echo "Новый пароль Redis: $NEW_PASSWORD"
    echo -e "${YELLOW}⚠  Сохраните этот пароль в безопасном месте!${NC}"
    
    read -p "Продолжить ротацию? (y/n): " CONFIRM
    if [ "$CONFIRM" != "y" ]; then
        echo "Отменено"
        return
    fi
    
    # Обновление .env
    sed -i.backup "s/^REDIS_PASSWORD=.*/REDIS_PASSWORD=$NEW_PASSWORD/" "$ENV_FILE"
    sed -i "s|^REDIS_URL=.*|REDIS_URL=redis://:$NEW_PASSWORD@redis:6379/0|" "$ENV_FILE"
    
    # Остановка бота, пересоздание Redis, запуск бота
    cd "$PROJECT_DIR"
    docker compose stop bot
    docker compose up -d --force-recreate redis
    sleep 3
    docker compose start bot
    
    # Проверка
    if docker exec who-is-the-spy-redis redis-cli -a "$NEW_PASSWORD" PING 2>/dev/null | grep -q "PONG"; then
        echo -e "${GREEN}✓${NC} Пароль Redis успешно изменен"
    else
        echo -e "${RED}✗${NC} Ошибка при проверке нового пароля"
        echo "Восстановление из .env.backup..."
        mv "$ENV_FILE.backup" "$ENV_FILE"
        docker compose up -d --force-recreate redis
        docker compose start bot
    fi
}

# Главная логика
case "$TARGET" in
    grafana)
        rotate_grafana
        ;;
    redis)
        rotate_redis
        ;;
    all)
        rotate_grafana
        rotate_redis
        ;;
    *)
        echo "Использование: $0 [grafana|redis|all]"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}✅ Ротация паролей завершена${NC}"
echo ""
echo "📋 Следующие шаги:"
echo "1. Убедитесь, что пароли сохранены в безопасном месте"
echo "2. Обновите документацию (если используете Password Manager)"
echo "3. Уведомите команду о новых паролях (если применимо)"
echo "4. Удалите .env.backup после проверки: rm $ENV_FILE.backup"
echo ""
