# Mini App Frontend (MVP)

Отдельный frontend-модуль Telegram Mini App для `/api/v1/miniapp/*`.

## Стек

- React + Vite + TypeScript
- In-memory session storage (без `localStorage`)
- Polling (`since_version` + `no_change`) с connection-state и backoff

## Запуск

```bash
cd webapp/miniapp-frontend
npm install
npm run dev
```

## Проверка сборки

```bash
npm run build
npm run test
```

## Переменные окружения

- `VITE_MINIAPP_API_BASE` — базовый URL backend API.
  - Пример для локальной разработки: `http://localhost:8080`
  - По умолчанию `""`, тогда клиент обращается к текущему origin.

## UX-объем MVP

- `AuthGate` через Telegram WebApp `initData` + `POST /auth`
- state-driven shell: `Lobby` / `Playing` / `Voting` / `Finished`
- единый player+admin UI с permission-aware контролами
- role secrecy: роль загружается отдельно (`GET /me/role`) и хранится только в памяти
- error/empty состояния по ключевым backend-кодам
- P2 baseline: архитектурные заготовки под haptics/microinteractions
