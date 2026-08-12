function safeErrorMessage(message: string) {
  const normalized = message.toLowerCase();
  if (normalized.includes("401") || normalized.includes("unauthorized") || normalized.includes("session")) {
    return "Your session is no longer available. Sign in again, then retry.";
  }
  if (normalized.includes("403") || normalized.includes("forbidden")) {
    return "This action is not available for the selected profile.";
  }
  if (normalized.includes("expired")) return "This request expired safely. Refresh the page before continuing.";
  return "Career OS could not reach this information. Your data and application state were not changed.";
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-state" role="alert">
      <strong>We could not load this view.</strong>
      <p>{safeErrorMessage(message)}</p>
      <details className="technical-details">
        <summary>Technical details</summary>
        <code>{message}</code>
      </details>
      {retry ? <button onClick={retry}>Try again</button> : null}
    </div>
  );
}
