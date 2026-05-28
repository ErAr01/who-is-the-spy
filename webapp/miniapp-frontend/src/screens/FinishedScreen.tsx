import type { MiniAppRoleResponse, MiniAppSnapshot } from "../api/types";
import { AdminActions } from "../components/AdminActions";
import { PlayersList } from "../components/PlayersList";
import { RoleCard } from "../components/RoleCard";

interface Props {
  snapshot: MiniAppSnapshot;
  role: MiniAppRoleResponse | null;
  roleLoading: boolean;
  pendingAction: string | null;
  onRevealRole: () => void;
  onCancel: () => void;
}

export function FinishedScreen({ snapshot, role, roleLoading, pendingAction, onRevealRole, onCancel }: Props) {
  return (
    <>
      <RoleCard role={role} loading={roleLoading} onReveal={onRevealRole} />
      <PlayersList players={snapshot.players} adminId={snapshot.admin_id} />
      <section className="card">
        <h2>Итоги</h2>
        <p className="muted">Раунд завершен. Можно обсудить результат и запустить новую игру из чата.</p>
      </section>
      <AdminActions
        title="Действия админа"
        actions={[
          {
            key: "cancel-game",
            label: "Сбросить игру",
            disabled: !snapshot.is_admin || pendingAction !== null,
            disabledReason: !snapshot.is_admin ? "Только админ может сбросить игру" : undefined,
            onClick: onCancel
          }
        ]}
      />
    </>
  );
}
