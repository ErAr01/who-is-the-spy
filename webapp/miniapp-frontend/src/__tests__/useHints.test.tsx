import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { miniAppClient } from "../api/miniappClient";
import type { GameState } from "../api/types";
import { useHints } from "../hooks/useHints";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useHints", () => {
  it("accumulates revealed hints and tracks the remaining counter", async () => {
    const spy = vi
      .spyOn(miniAppClient, "getHint")
      .mockResolvedValueOnce({ has_hint: true, hint: "fact-0", hints_total: 2, hints_used: 1, hints_remaining: 1 })
      .mockResolvedValueOnce({ has_hint: true, hint: "fact-1", hints_total: 2, hints_used: 2, hints_remaining: 0 });

    const { result } = renderHook(() => useHints("token", 1, "playing"));

    await act(async () => {
      await result.current.revealHint();
    });
    expect(result.current.revealed).toEqual(["fact-0"]);
    expect(result.current.remaining).toBe(1);

    await act(async () => {
      await result.current.revealHint();
    });
    expect(result.current.revealed).toEqual(["fact-0", "fact-1"]);
    expect(result.current.remaining).toBe(0);
    expect(result.current.total).toBe(2);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("handles exhaustion without appending an empty hint", async () => {
    vi.spyOn(miniAppClient, "getHint").mockResolvedValue({
      has_hint: false,
      hint: null,
      hints_total: 2,
      hints_used: 2,
      hints_remaining: 0
    });

    const { result } = renderHook(() => useHints("token", 1, "voting"));

    await act(async () => {
      await result.current.revealHint();
    });

    expect(result.current.revealed).toEqual([]);
    expect(result.current.remaining).toBe(0);
  });

  it("resets revealed hints when a new round starts after finished", async () => {
    vi.spyOn(miniAppClient, "getHint").mockResolvedValue({
      has_hint: true,
      hint: "fact-0",
      hints_total: 3,
      hints_used: 1,
      hints_remaining: 2
    });

    let state: GameState = "playing";
    const { result, rerender } = renderHook(() => useHints("token", 1, state));

    await act(async () => {
      await result.current.revealHint();
    });
    expect(result.current.revealed).toEqual(["fact-0"]);

    // finished -> playing simulates a brand new round; hints from the previous round must clear.
    state = "finished";
    rerender();
    state = "playing";
    rerender();

    await waitFor(() => expect(result.current.revealed).toEqual([]));
    expect(result.current.remaining).toBeNull();
  });

  it("deduplicates concurrent reveal calls (double click consumes one hint)", async () => {
    const spy = vi.spyOn(miniAppClient, "getHint").mockResolvedValue({
      has_hint: true,
      hint: "fact-0",
      hints_total: 3,
      hints_used: 1,
      hints_remaining: 2
    });

    const { result } = renderHook(() => useHints("token", 1, "playing"));

    await act(async () => {
      // Два синхронных вызова в один тик — второй должен быть проигнорирован.
      await Promise.all([result.current.revealHint(), result.current.revealHint()]);
    });

    expect(spy).toHaveBeenCalledTimes(1);
    expect(result.current.revealed).toEqual(["fact-0"]);
  });

  it("surfaces a 409 error from a stale round", async () => {
    vi.spyOn(miniAppClient, "getHint").mockRejectedValue({
      code: "hint_forbidden_state",
      message: "round ended",
      status: 409
    });

    const { result } = renderHook(() => useHints("token", 1, "playing"));

    await act(async () => {
      await result.current.revealHint();
    });

    expect(result.current.error?.code).toBe("hint_forbidden_state");
    expect(result.current.revealed).toEqual([]);
  });
});
