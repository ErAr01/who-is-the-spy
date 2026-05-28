import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { miniAppClient } from "../api/miniappClient";
import type { ApiError, GameState, MiniAppRoleResponse } from "../api/types";

interface RoleState {
  loading: boolean;
  role: MiniAppRoleResponse | null;
  error: ApiError | null;
  revealRole: () => Promise<void>;
  clearRole: () => void;
}

const ROLE_STATES: GameState[] = ["playing", "voting", "finished"];

export function useRole(sessionToken: string, chatId: number, gameState?: GameState): RoleState {
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState<MiniAppRoleResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const previousStateRef = useRef<GameState | undefined>(gameState);

  const allowed = gameState ? ROLE_STATES.includes(gameState) : false;

  const clearRole = useCallback(() => {
    setRole(null);
    setError(null);
  }, []);

  const revealRole = useCallback(async () => {
    if (!allowed) {
      clearRole();
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const payload = await miniAppClient.getRole(sessionToken, chatId);
      setRole(payload);
    } catch (requestError) {
      setRole(null);
      setError(requestError as ApiError);
    } finally {
      setLoading(false);
    }
  }, [allowed, chatId, clearRole, sessionToken]);

  useEffect(() => {
    if (!allowed) {
      clearRole();
    }
  }, [allowed, clearRole]);

  useEffect(() => {
    const previousState = previousStateRef.current;
    previousStateRef.current = gameState;

    // If game enters a new playing round from finished state, keep role hidden until user reveals again.
    if (gameState === "playing" && previousState === "finished") {
      clearRole();
    }
  }, [clearRole, gameState]);

  return useMemo(() => ({ loading, role, error, revealRole, clearRole }), [clearRole, error, loading, revealRole, role]);
}
