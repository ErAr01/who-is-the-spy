interface Props {
  open: boolean;
  title: string;
  description: string;
  confirmText: string;
  cancelText?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText,
  cancelText = "Отмена",
  onConfirm,
  onCancel
}: Props) {
  if (!open) {
    return null;
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="dialog">
        <h3>{title}</h3>
        <p>{description}</p>
        <div className="dialog-actions">
          <button type="button" className="button button-secondary" onClick={onCancel}>
            {cancelText}
          </button>
          <button type="button" className="button button-danger" onClick={onConfirm}>
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
