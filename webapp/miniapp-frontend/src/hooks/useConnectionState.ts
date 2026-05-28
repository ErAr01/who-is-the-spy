import { useMemo } from "react";

import type { ConnectionState } from "../api/types";

interface Params {
  hasSnapshot: boolean;
  isFetching: boolean;
  isReconnecting: boolean;
  lastSuccessAt: number | null;
  staleAfterMs?: number;
  now?: number;
}

export function resolveConnectionState(params: Params): ConnectionState {
  const { hasSnapshot, isFetching, isReconnecting, lastSuccessAt, staleAfterMs = 10_000, now = Date.now() } = params;

  if (!hasSnapshot && isFetching) {
    return "loading";
  }
  if (isReconnecting) {
    return "reconnecting";
  }
  if (lastSuccessAt !== null && now - lastSuccessAt > staleAfterMs) {
    return "stale";
  }
  return "fresh";
}

export function useConnectionState(params: Params): ConnectionState {
  return useMemo(() => resolveConnectionState(params), [params]);
}
