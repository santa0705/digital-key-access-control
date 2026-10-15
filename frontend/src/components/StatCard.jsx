
export default function StatCard({
  label,
  value,
  subtext,
  icon: Icon,
  tone = 'default',
  onClick,
  active = false
}) {
  return (
    <div
      className={`stat-card tone-${tone} ${onClick ? 'clickable' : ''} ${active ? 'is-active' : ''}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="stat-card-header">
        <span className="stat-card-label">{label}</span>
        {Icon && (
          <div className="stat-card-icon">
            <Icon size={16} />
          </div>
        )}
      </div>
      <div className="stat-card-value">{value}</div>
      {subtext && <div className="stat-card-subtext">{subtext}</div>}
    </div>
  );
}
