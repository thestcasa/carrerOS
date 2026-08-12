import type { ApplicationEventView, ApplicationState } from "@/lib/types";
import { applicationStatus, eventLabel } from "@/lib/product-semantics";
import { ProductIcon } from "./ProductIcon";

export function ApplicationTimeline({ events, currentState }: { events: ApplicationEventView[]; currentState: ApplicationState }) {
  const ordered = [...events].sort((left, right) => left.occurred_at.localeCompare(right.occurred_at));
  const visible = ordered.filter((event, index) => index === ordered.length - 1 || event.to_state !== ordered[index + 1]?.to_state);
  if (!visible.length) {
    const current = applicationStatus(currentState);
    return <ol className="application-timeline"><li className={`timeline-step active semantic-${current.tone}`}><span className="timeline-marker"><ProductIcon name="clock" /></span><div><strong>{current.label}</strong><p>{current.description}</p></div></li></ol>;
  }
  return <ol className="application-timeline">{visible.map((event, index) => {
    const isLast = index === visible.length - 1;
    const status = applicationStatus(event.to_state);
    const failed = status.tone === "danger";
    const waiting = status.tone === "attention";
    return <li className={`timeline-step ${isLast ? "active" : "completed"} semantic-${status.tone}`} key={event.event_id}>
      <span className="timeline-marker"><ProductIcon name={failed || waiting ? "warning" : isLast ? "clock" : "check"} /></span>
      <div>
        <strong>{eventLabel(event)}</strong>
        {isLast ? <p>{status.description}</p> : null}
        <time dateTime={event.occurred_at}>{new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.occurred_at))}</time>
      </div>
    </li>;
  })}</ol>;
}
