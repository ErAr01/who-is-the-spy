import { useMemo, useState } from "react";

import { miniAppClient } from "../api/miniappClient";
import type { ApiError, MiniAppActionResponse } from "../api/types";

interface UseGameActionsResult {
  pendingAction: string | null;
  actionError: ApiError | null;
  actionNote: string | null;
  clearActionError: () => void;
  join: () => Promise<void>;
  leave: () => Promise<void>;
  toggleCategory: (category: string) => Promise<void>;
  start: () => Promise<void>;
  repeatRound: () => Promise<void>;
  chooseNewCategories: () => Promise<void>;
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
  const [actionNote, setActionNote] = useState<string | null>(null);

  async function runAction(actionName: string, action: () => Promise<MiniAppActionResponse>): Promise<void> {
    setPendingAction(actionName);
    setActionError(null);
    setActionNote(null);
    try {
      const response = await action();
      setActionNote(response.note_message ?? null);
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
      actionNote,
      clearActionError: () => setActionError(null),
      join: () => runAction("join", () => miniAppClient.join(sessionToken, chatId)),
      leave: () => runAction("leave", () => miniAppClient.leave(sessionToken, chatId)),
      toggleCategory: (category: string) =>
        runAction("toggle_category", () => miniAppClient.toggleCategory(sessionToken, chatId, category)),
      start: () => runAction("start", () => miniAppClient.start(sessionToken, chatId)),
      repeatRound: () => runAction("repeat_round", () => miniAppClient.repeatRound(sessionToken, chatId)),
      chooseNewCategories: () =>
        runAction("round_new_categories", () => miniAppClient.chooseNewCategories(sessionToken, chatId)),
      openVoting: () => runAction("open_voting", () => miniAppClient.openVoting(sessionToken, chatId)),
      closeVoting: () => runAction("close_voting", () => miniAppClient.closeVoting(sessionToken, chatId)),
      vote: (targetId: number) => runAction("vote", () => miniAppClient.vote(sessionToken, chatId, targetId)),
      cancel: () => runAction("cancel", () => miniAppClient.cancel(sessionToken, chatId))
    }),
    [actionError, actionNote, chatId, onActionSuccess, pendingAction, sessionToken]
  );
}
