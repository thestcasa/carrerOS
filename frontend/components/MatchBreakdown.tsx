import type { ScoreContribution } from "@/lib/types";
export function MatchBreakdown({ items }: { items: ScoreContribution[] }) {
  const maximum = Math.max(1, ...items.map((item) => Math.max(0, item.points)));
  if (!items.length) return <p className="muted">No score breakdown is available.</p>;
  return <div className="match-breakdown">{items.map((item) => {
    const width = Math.max(4, Math.round((Math.max(0, item.points) / maximum) * 100));
    return <div className="breakdown-row" key={item.name}>
      <div><span>{item.name.replaceAll("_", " ")}</span><strong>{item.points > 0 ? "+" : ""}{item.points} pts</strong></div>
      <div className="breakdown-track" aria-hidden="true"><span style={{ width: `${width}%` }} /></div>
      <small>{item.explanation}</small>
    </div>;
  })}</div>;
}
