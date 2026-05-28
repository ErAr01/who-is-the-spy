# Развертывание и обновление на сервере

Этот документ фиксирует рабочий порядок обновления проекта на сервере, где:
- backend работает через `docker compose` (`bot` + `redis`);
- Mini App фронтенд раздается отдельным `Caddy` из `webapp/miniapp-frontend/dist`.

## Быстрый сценарий обновления

```bash
# 1) Подключиться к серверу
ssh root@...

# 2) Перейти в проект и подтянуть код
cd /opt/who_is_the_spy
git fetch --all
git checkout feature/telegram-mini-app-migration
git pull --ff-only

# 3) Обновить .env (новый параметр, если его нет)
# LOBBY_IDLE_RESET_SECONDS=3600

# 4) Пересобрать фронтенд (Caddy отдает файлы из dist)
cd /opt/who_is_the_spy/webapp/miniapp-frontend
npm install
npm run build

# 5) Перезапустить backend-контейнеры с пересборкой
cd /opt/who_is_the_spy
docker compose up -d --build bot redis

# 6) Проверка, что все поднялось
docker compose ps
docker compose logs --tail=100 bot
curl -I https://---.sslip.io
curl -I https://---.sslip.io/api/v1/miniapp/game
```

## Коротко по сути

- `git pull` подтягивает изменения кода.
- `npm run build` обязателен, потому что измененный Mini App фронтенд должен попасть в `dist`.
- `docker compose up -d --build bot redis` пересобирает и перезапускает backend с новым кодом.
- `miniapp-caddy` обычно перезапускать не нужно, если `Caddyfile` не менялся.

## Когда нужен перезапуск Caddy

Перезапускай или reload `miniapp-caddy` только если:
- изменился `Caddyfile`;
- изменился домен/URL (`sslip.io`);
- поменялся маршрут `reverse_proxy`.

Если менялись только backend-код и frontend `dist`, достаточно шагов из "Быстрый сценарий обновления".
