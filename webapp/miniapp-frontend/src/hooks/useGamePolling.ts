import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { miniAppClient } from "../api/miniappClient";
import type { ApiError, ConnectionState, MiniAppSnapshot } from "../api/types";
import { useConnectionState } from "./useConnectionState";

interface PollingResult {
  snapshot: MiniAppSnapshot | null;
  connection: ConnectionState;
  error: ApiError | null;
  refreshNow: () => void;
}

const FRESH_INTERVAL_MS = 2500;
const MAX_BACKOFF_MS = 15000;

export function useGamePolling(sessionToken: string, chatId: number): PollingResult {
  const [snapshot, setSnapshot] = useState<MiniAppSnapshot | null>(null);
  const [version, setVersion] = useState<number | undefined>(undefined);
  const [isFetching, setIsFetching] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const backoffRef = useRef(1000);

  const refreshNow = useCallback(() => {
    setTick((value) => value + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const poll = async () => {
      setIsFetching(true);
      try {
        const response = await miniAppClient.getGame(sessionToken, chatId, version);
        if (cancelled) {
          return;
        }

        setError(null);
        setLastSuccessAt(Date.now());
        setIsReconnecting(false);
        backoffRef.current = 1000;

        if (!response.no_change && response.snapshot) {
          setSnapshot(response.snapshot);
          setVersion(response.snapshot.version);
        } else {
          setVersion(response.version);
        }

        timer = window.setTimeout(poll, FRESH_INTERVAL_MS);
      } catch (pollError) {
        if (cancelled) {
          return;
        }

        setError(pollError as ApiError);
        setIsReconnecting(true);
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS);
        timer = window.setTimeout(poll, backoffRef.current);
      } finally {
        if (!cancelled) {
          setIsFetching(false);
        }
      }
    };

    void poll();

    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [chatId, sessionToken, tick, version]);

  const connection = useConnectionState({
    hasSnapshot: snapshot !== null,
    isFetching,
    isReconnecting,
    lastSuccessAt
  });

  return useMemo(
    () => ({
      snapshot,
      connection,
      error,
      refreshNow
    }),
    [connection, error, refreshNow, snapshot]
  );
}
