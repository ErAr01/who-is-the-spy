import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { miniAppClient } from "../api/miniappClient";
import type { ApiError, GameState } from "../api/types";

interface HintsState {
  /** Подсказки, открытые в этом раунде (только в памяти, как и роль). */
  revealed: string[];
  loading: boolean;
  error: ApiError | null;
  /** Сколько подсказок ещё можно открыть. null — пока неизвестно. */
  remaining: number | null;
  total: number;
  used: number;
  revealHint: () => Promise<void>;
  reset: () => void;
}

const HINT_STATES: GameState[] = ["playing", "voting"];

export function useHints(sessionToken: string, chatId: number, gameState?: GameState): HintsState {
  const [revealed, setRevealed] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [total, setTotal] = useState(0);
  const [used, setUsed] = useState(0);
  const previousStateRef = useRef<GameState | undefined>(gameState);
  // setLoading асинхронен — два клика в один тик прошли бы оба и съели две подсказки.
  const inFlightRef = useRef(false);

  const allowed = gameState ? HINT_STATES.includes(gameState) : false;

  const reset = useCallback(() => {
    setRevealed([]);
    setError(null);
    setRemaining(null);
    setTotal(0);
    setUsed(0);
  }, []);

  const revealHint = useCallback(async () => {
    if (!allowed) {
      reset();
      return;
    }
    if (inFlightRef.current) {
      return;
    }
    inFlightRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const payload = await miniAppClient.getHint(sessionToken, chatId);
      setTotal(payload.hints_total);
      setUsed(payload.hints_used);
      setRemaining(payload.hints_remaining);
      if (payload.has_hint && payload.hint) {
        setRevealed((prev) => [...prev, payload.hint as string]);
      }
    } catch (requestError) {
      setError(requestError as ApiError);
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }, [allowed, chatId, reset, sessionToken]);

  // Сбрасываем при выходе из активного раунда (роль тоже скрывается).
  useEffect(() => {
    if (!allowed) {
      reset();
    }
  }, [allowed, reset]);

  // Новый раунд после завершения — открытые подсказки больше не валидны.
  useEffect(() => {
    const previousState = previousStateRef.current;
    previousStateRef.current = gameState;
    if (gameState === "playing" && previousState === "finished") {
      reset();
    }
  }, [gameState, reset]);

  return useMemo(
    () => ({ revealed, loading, error, remaining, total, used, revealHint, reset }),
    [error, loading, remaining, reset, revealHint, revealed, total, used]
  );
}
