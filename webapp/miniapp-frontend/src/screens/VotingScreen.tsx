import type { MiniAppSnapshot } from "../api/types";
import { AdminActions } from "../components/AdminActions";
import { VotePanel } from "../components/VotePanel";

interface Props {
  snapshot: MiniAppSnapshot;
  currentUserId: number;
  pendingAction: string | null;
  onVote: (targetId: number) => void;
  onCloseVoting: () => void;
}

export function VotingScreen({ snapshot, currentUserId, pendingAction, onVote, onCloseVoting }: Props) {
  return (
    <>
      <VotePanel
        players={snapshot.players}
        currentUserId={currentUserId}
        disabled={!snapshot.is_member || pendingAction !== null}
        disabledReason={!snapshot.is_member ? "Голосовать могут только участники" : undefined}
        onVote={onVote}
      />
      <AdminActions
        title="Управление голосованием"
        actions={[
          {
            key: "close-voting",
            label: "Закрыть голосование",
            primary: true,
            disabled: !snapshot.is_admin || pendingAction !== null,
            disabledReason: !snapshot.is_admin ? "Только админ может закрыть голосование" : undefined,
            onClick: onCloseVoting
          }
        ]}
      />
    </>
  );
}
