
const STATUS_CONFIG = {
  pending: {
    label: 'Pending',
    className: 'badge-pending'
  },
  approved: {
    label: 'Approved',
    className: 'badge-approved'
  },
  active: {
    label: 'Active',
    className: 'badge-active'
  },
  rejected: {
    label: 'Rejected',
    className: 'badge-rejected'
  },
  revoked: {
    label: 'Revoked',
    className: 'badge-revoked'
  },
  expired: {
    label: 'Expired',
    className: 'badge-expired'
  },
  consumed: {
    label: 'Consumed',
    className: 'badge-consumed'
  }
};

export default function Badge({ status, label, size = 'sm', variant }) {
  const config = STATUS_CONFIG[status?.toLowerCase()] || {
    label: label || status || 'Unknown',
    className: 'badge-default'
  };

  const displayLabel = label || config.label;
  const badgeClass = variant ? `badge-${variant}` : config.className;

  return (
    <span className={`status-badge ${badgeClass} size-${size}`}>
      <span className="badge-dot" />
      {displayLabel}
    </span>
  );
}
