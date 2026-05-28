import { useMemo, useState } from "react";

import { miniAppClient } from "../api/miniappClient";
import type { ApiError } from "../api/types";

interface UseGameActionsResult {
  pendingAction: string | null;
  actionError: ApiError | null;
  clearActionError: () => void;
  join: () => Promise<void>;
  toggleCategory: (category: string) => Promise<void>;
  start: () => Promise<void>;
  openVoting: () => Promise<void>;
  closeVoting: () => Promise<void>;
  vote: (targetId: number) => Promise<void>;
  cancel: () => Promise<void>;
}

export function useGameActions(
  sessionToken: string,
  chatId: number,
  onActionSuccess: () => void
): UseGameActionsResult {
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);

  async function runAction(actionName: string, action: () => Promise<unknown>): Promise<void> {
    setPendingAction(actionName);
    setActionError(null);
    try {
      await action();
      onActionSuccess();
    } catch (error) {
      setActionError(error as ApiError);
    } finally {
      setPendingAction(null);
    }
  }

  return useMemo(
    () => ({
      pendingAction,
      actionError,
      clearActionError: () => setActionError(null),
      join: () => runAction("join", () => miniAppClient.join(sessionToken, chatId)),
      toggleCategory: (category: string) =>
        runAction("toggle_category", () => miniAppClient.toggleCategory(sessionToken, chatId, category)),
      start: () => runAction("start", () => miniAppClient.start(sessionToken, chatId)),
      openVoting: () => runAction("open_voting", () => miniAppClient.openVoting(sessionToken, chatId)),
      closeVoting: () => runAction("close_voting", () => miniAppClient.closeVoting(sessionToken, chatId)),
      vote: (targetId: number) => runAction("vote", () => miniAppClient.vote(sessionToken, chatId, targetId)),
      cancel: () => runAction("cancel", () => miniAppClient.cancel(sessionToken, chatId))
    }),
    [actionError, chatId, onActionSuccess, pendingAction, sessionToken]
  );
}
