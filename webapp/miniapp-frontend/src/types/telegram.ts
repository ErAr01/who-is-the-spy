export type TelegramHapticImpactStyle = "light" | "medium" | "heavy" | "rigid" | "soft";

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe?: {
    chat?: { id?: number };
    start_param?: string;
  };
  ready(): void;
  expand(): void;
  HapticFeedback?: {
    impactOccurred(style: TelegramHapticImpactStyle): void;
    notificationOccurred(type: "error" | "success" | "warning"): void;
  };
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}
