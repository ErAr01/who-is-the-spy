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
  isPrivateChat: boolean;
}

export function useTelegramWebApp(): TelegramContext {
  return useMemo(() => {
    const webApp = window.Telegram?.WebApp ?? null;
    if (webApp) {
      webApp.ready();
      webApp.expand();
    }

    const chatId =
      parseChatIdFromSearch() ??
      webApp?.initDataUnsafe?.chat?.id ??
      parseChatIdFromStartParam(webApp?.initDataUnsafe?.start_param) ??
      webApp?.initDataUnsafe?.user?.id ??
      null;
    const userId = webApp?.initDataUnsafe?.user?.id ?? null;
    const chatType = webApp?.initDataUnsafe?.chat?.type;

    return {
      webApp,
      initData: webApp?.initData ?? "",
      chatId,
      mode: new URLSearchParams(window.location.search).get("mode"),
      isPrivateChat: chatType === "private" || (chatId !== null && userId !== null && chatId === userId)
    };
  }, []);
}
