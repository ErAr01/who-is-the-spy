import { useMemo } from "react";

import type { TelegramWebApp } from "../types/telegram";

function parseChatIdFromSearch(): number | null {
  const value = new URLSearchParams(window.location.search).get("chat_id");
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseChatIdFromStartParam(value: unknown): number | null {
  if (typeof value !== "string") {
    return null;
  }
  const match = value.match(/^chat_(-?\d+)$/);
  if (!match) {
    return null;
  }
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? parsed : null;
}

export interface TelegramContext {
  webApp: TelegramWebApp | null;
  initData: string;
  chatId: number | null;
  mode: string | null;
}

export function useTelegramWebApp(): TelegramContext {
  return useMemo(() => {
    const webApp = window.Telegram?.WebApp ?? null;
    if (webApp) {
      webApp.ready();
      webApp.expand();
    }

    return {
      webApp,
      initData: webApp?.initData ?? "",
      chatId:
        parseChatIdFromSearch() ??
        webApp?.initDataUnsafe?.chat?.id ??
        parseChatIdFromStartParam(webApp?.initDataUnsafe?.start_param) ??
        webApp?.initDataUnsafe?.user?.id ??
        null,
      mode: new URLSearchParams(window.location.search).get("mode")
    };
  }, []);
}
