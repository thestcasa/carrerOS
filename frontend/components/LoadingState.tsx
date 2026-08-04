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
      <p>{message}</p>
      {retry ? <button onClick={retry}>Try again</button> : null}
    </div>
  );
}
