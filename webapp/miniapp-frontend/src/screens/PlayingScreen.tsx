import type { ApiError, MiniAppRoleResponse, MiniAppSnapshot } from "../api/types";
import { AdminActions } from "../components/AdminActions";
import { RoleCard } from "../components/RoleCard";

interface Props {
  snapshot: MiniAppSnapshot;
  role: MiniAppRoleResponse | null;
  roleLoading: boolean;
  pendingAction: string | null;
  hints: {
    revealed: string[];
    loading: boolean;
    error: ApiError | null;
    remaining: number | null;
    total: number;
    used: number;
    onRevealHint: () => void;
  };
  onRevealRole: () => void;
  onOpenVoting: () => void;
  onCancel: () => void;
}

export function PlayingScreen({
  snapshot,
  role,
  roleLoading,
  pendingAction,
  hints,
  onRevealRole,
  onOpenVoting,
  onCancel
}: Props) {
  return (
    <>
      <section className="card turn-order-reminder">
        <p className="hint">
          Вы можете определить порядок хода самостоятельно, но если среди вас есть игрок по имени Даша, то она
          ходит первой.
        </p>
      </section>
      <RoleCard
        role={role}
        loading={roleLoading}
        onReveal={onRevealRole}
        hiddenReason="Роль доступна только после старта раунда."
        hints={hints}
      />
      <AdminActions
        title="Управление раундом"
        actions={[
          {
            key: "open-voting",
            label: "Открыть голосование",
            primary: true,
            disabled: !snapshot.is_admin || pendingAction !== null,
            disabledReason: !snapshot.is_admin ? "Только админ может открыть голосование" : undefined,
            onClick: onOpenVoting
          },
          {
            key: "cancel",
            label: "Отменить игру",
            disabled: !snapshot.is_admin || pendingAction !== null,
            disabledReason: !snapshot.is_admin ? "Доступно только админу" : undefined,
            onClick: onCancel
          }
        ]}
      />
    </>
  );
}
