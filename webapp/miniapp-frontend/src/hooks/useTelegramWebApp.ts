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

export interface TelegramContext {
  webApp: TelegramWebApp | null;
  initData: string;
  chatId: number | null;
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
      chatId: parseChatIdFromSearch() ?? webApp?.initDataUnsafe?.chat?.id ?? null
    };
  }, []);
}
