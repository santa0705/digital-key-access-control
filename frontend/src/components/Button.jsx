
export default function Button({
  children,
  variant = 'secondary',
  size = 'md',
  icon: Icon,
  disabled = false,
  loading = false,
  type = 'button',
  onClick,
  className = '',
  title,
  ...rest
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      onClick={onClick}
      className={`btn btn-${variant} btn-${size} ${className}`}
      title={title}
      {...rest}
    >
      {loading ? (
        <span className="btn-spinner" aria-hidden="true" />
      ) : Icon ? (
        <Icon className="btn-icon" size={size === 'sm' ? 14 : 16} />
      ) : null}
      <span className="btn-text">{children}</span>
    </button>
  );
}
