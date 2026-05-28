import { useCallback, useEffect, useState } from "react";

import type { ApiError, MiniAppUser } from "../api/types";
import { miniAppClient } from "../api/miniappClient";

type AuthStatus = "idle" | "loading" | "ready" | "error";

export interface MiniAppSession {
  token: string;
  expiresAt: number;
  user: MiniAppUser;
}

interface UseMiniAppAuthResult {
  session: MiniAppSession | null;
  status: AuthStatus;
  error: ApiError | null;
  authorize: () => Promise<void>;
  logout: () => void;
}

export function useMiniAppAuth(initData: string, chatId: number | null): UseMiniAppAuthResult {
  const [session, setSession] = useState<MiniAppSession | null>(null);
  const [status, setStatus] = useState<AuthStatus>("idle");
  const [error, setError] = useState<ApiError | null>(null);

  const authorize = useCallback(async () => {
    if (!chatId || !initData) {
      setStatus("error");
      setError({ code: "init_data_expired", message: "Не хватает данных Telegram для авторизации." });
      return;
    }

    setStatus("loading");
    setError(null);

    try {
      const response = await miniAppClient.auth(initData, chatId);
      setSession({ token: response.session_token, expiresAt: response.expires_at, user: response.user });
      setStatus("ready");
    } catch (authError) {
      setSession(null);
      setStatus("error");
      setError(authError as ApiError);
    }
  }, [chatId, initData]);

  const logout = useCallback(() => {
    setSession(null);
    setStatus("idle");
  }, []);

  useEffect(() => {
    if (!session) {
      void authorize();
    }
  }, [authorize, session]);

  return { session, status, error, authorize, logout };
}
