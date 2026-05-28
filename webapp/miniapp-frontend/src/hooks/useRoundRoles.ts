import { useCallback, useEffect, useMemo, useState } from "react";

import { miniAppClient } from "../api/miniappClient";
import type { ApiError, GameState, MiniAppRoundRolesResponse } from "../api/types";

interface RoundRolesState {
  loading: boolean;
  roundRoles: MiniAppRoundRolesResponse | null;
  error: ApiError | null;
  revealRoundRoles: () => Promise<void>;
  clearRoundRoles: () => void;
}

export function useRoundRoles(sessionToken: string, chatId: number, gameState?: GameState): RoundRolesState {
  const [loading, setLoading] = useState(false);
  const [roundRoles, setRoundRoles] = useState<MiniAppRoundRolesResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const allowed = gameState === "finished";

  const clearRoundRoles = useCallback(() => {
    setRoundRoles(null);
    setError(null);
  }, []);

  const revealRoundRoles = useCallback(async () => {
    if (!allowed) {
      clearRoundRoles();
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const payload = await miniAppClient.getRoundRoles(sessionToken, chatId);
      setRoundRoles(payload);
    } catch (requestError) {
      setRoundRoles(null);
      setError(requestError as ApiError);
    } finally {
      setLoading(false);
    }
  }, [allowed, chatId, clearRoundRoles, sessionToken]);

  useEffect(() => {
    if (!allowed) {
      clearRoundRoles();
    }
  }, [allowed, clearRoundRoles]);

  return useMemo(
    () => ({ loading, roundRoles, error, revealRoundRoles, clearRoundRoles }),
    [clearRoundRoles, error, loading, revealRoundRoles, roundRoles]
  );
}
