# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telegram bot for the game "Who Is The Spy" (group-chat game loop: lobby → round → voting), plus a Telegram Mini App (React frontend + FastAPI backend) and a separate card-labeling CLI service. Docs and README are in Russian.

## Commands

### Backend (Python 3.12, aiogram 3, FastAPI)

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # includes torch/transformers for local CLIP

# Run bot locally (requires Redis at REDIS_URL and .env with BOT_TOKEN)
python -m src.main

# Tests (pytest, no config file — run from repo root so `src` imports resolve)
python -m pytest tests/
python -m pytest tests/test_miniapp_service.py            # single file
python -m pytest tests/test_miniapp_service.py -k name    # single test

# Docker (redis + bot)
docker compose up --build
docker compose --profile observability up -d --build      # + Prometheus/Loki/Promtail/Grafana
```

There is no linter/formatter configuration in this repo.

### Mini App frontend (React + Vite + TypeScript)

```bash
cd webapp/miniapp-frontend
npm install
npm run dev        # local dev server
npm run build      # tsc type-check + vite build (required before deploy — Caddy serves dist/)
npm run test       # vitest
```

### Labeling CLI

```bash
python -m src.labeling.cli <command>   # ingest, ingest-batch, pair, list, stats, re-embed,
                                       # image-embed-ingest[-batch], image-embed-list, plot-embeddings, ...
```

## Architecture

Two subsystems sharing `src/config.py` (`Settings` via pydantic-settings, all env vars + defaults, loaded from `.env`):

### 1. Game Bot Runtime (`python -m src.main` — single process)

- `src/main.py` runs aiogram **long polling** and, when `MINIAPP_ENABLED=true`, also starts a uvicorn server for the Mini App API **in the same process**. The Prometheus metrics HTTP server (port 8001) is a third listener when `METRICS_ENABLED=true`.
- `src/bot.py` builds `AppContext` (Bot, Dispatcher, two Redis clients, `GameRepo`). Game state lives in **Redis** (`game:{chat_id}`), FSM storage also Redis.
- `src/handlers/` — Telegram entry points: `group.py` (`/newgame`, `/startgame`, `/vote`, `/endvote`, `/cancel`), `private.py` (`/start`, `/testpair`), `callbacks.py` (join/category/vote buttons), `admin_actions.py`.
- `src/game/` — domain logic shared by Telegram handlers AND the Mini App: `engine.py` (round prep, role delivery, vote counting), `content.py` (`ContentProvider` — picks a civilian/spy image pair from SQLite using tag embeddings + pair history + 24h per-chat anti-repeat TTL), `repo.py` (Redis persistence), `models.py` (`Game`, `Player`, `GameState`, `GameMode` — only `IMAGE_DB` mode is actually used at runtime).
- `src/miniapp/` — FastAPI app mounted at `/api/v1/miniapp`: `auth.py` validates Telegram WebApp `initData` and issues short-lived sessions (`session.py`, signed with `MINIAPP_SESSION_SECRET`), `service.py` wraps game actions, `api.py` defines routes. Clients long-poll `GET /game` with `since_version` + `no_change` protocol.
- `src/analytics/` — `analytics_event` JSON events to stdout (taxonomy in README); `src/observability/` mirrors them into Prometheus metrics. Both are wired as emitters/middleware in `main.py` — new game events should go through this layer, not direct logging.

### 2. Labeling Service (`src/labeling/`, offline CLI)

Prepares card content: ingests images into SQLite (`LABELING_DB_PATH`, prod DB is `data/images/cards_prod.db`) as BLOBs, tags them via OpenAI vision (`llm/openai_tagger.py`), embeds the appearance text, and stores `cards`/`card_tags`/`pair_history` tables (`storage.py`). A separate image-embedding DB (`IMAGE_EMBEDDING_DB_PATH`, local CLIP by default) powers an optional runtime matcher gated by `ENABLE_IMAGE_EMBEDDING_MATCHER` — default game flow is tag-based. The game's `ContentProvider` reads these same SQLite DBs; there are no migrations (schema evolves manually).

### Frontend (`webapp/miniapp-frontend/`)

React SPA talking only to `/api/v1/miniapp/*` (`src/api/miniappClient.ts`, `VITE_MINIAPP_API_BASE` env). State-driven shell: Lobby / Playing / Voting / Finished, single player+admin UI with permission-aware controls. Role data is fetched separately (`GET /me/role`) and kept in memory only — no `localStorage`. In production it is served by Caddy from `dist/` (not by FastAPI), so frontend changes require `npm run build` on the server; backend changes require `docker compose up -d --build bot redis` (see `docs/technical_documentation_ru/07_server_deployment_and_update.md`).

## Conventions and gotchas

- Run pytest and `python -m ...` from the repo root — all imports are absolute from `src.`.
- `get_settings()` is `lru_cache`d; `Settings` validators silently coerce invalid env values to safe defaults (follow that pattern for new settings).
- When adding a bot command: handler in `src/handlers/`, keyboard in `src/utils/keyboards.py`, callback in `callbacks.py`; routers are included in `src/main.py`. Mirror game-state mutations in `src/miniapp/service.py` if the Mini App should support them.
- New content-selection logic must keep the `ContentProvider` contract: `get_random_image_pair(...)` and `get_image_bytes(card_id)`.
- Full documentation index: `docs/TECHNICAL_DOCUMENTATION_RU.md` (sections in `docs/technical_documentation_ru/`). Ops: `PRODUCTION_RUNBOOK.md`, security: `SECURITY_QUICK_REFERENCE.md` and `docker-compose.secure.yml`.
