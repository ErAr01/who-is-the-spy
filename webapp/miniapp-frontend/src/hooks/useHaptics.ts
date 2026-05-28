import { useCallback } from "react";

import type { TelegramHapticImpactStyle } from "../types/telegram";

export function useHaptics() {
  const impact = useCallback((style: TelegramHapticImpactStyle = "light") => {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(style);
  }, []);

  const notify = useCallback((type: "success" | "warning" | "error") => {
    window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred(type);
  }, []);

  return { impact, notify };
}
