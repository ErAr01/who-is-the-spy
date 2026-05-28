import { describe, expect, it } from "vitest";

import { resolveConnectionState } from "../hooks/useConnectionState";

describe("resolveConnectionState", () => {
  it("returns loading on first fetch", () => {
    expect(
      resolveConnectionState({
        hasSnapshot: false,
        isFetching: true,
        isReconnecting: false,
        lastSuccessAt: null,
        now: 100
      })
    ).toBe("loading");
  });

  it("returns reconnecting when retrying after failure", () => {
    expect(
      resolveConnectionState({
        hasSnapshot: true,
        isFetching: false,
        isReconnecting: true,
        lastSuccessAt: Date.now(),
        now: Date.now()
      })
    ).toBe("reconnecting");
  });

  it("returns stale when freshness timeout passed", () => {
    expect(
      resolveConnectionState({
        hasSnapshot: true,
        isFetching: false,
        isReconnecting: false,
        lastSuccessAt: 0,
        staleAfterMs: 1000,
        now: 2001
      })
    ).toBe("stale");
  });
});
