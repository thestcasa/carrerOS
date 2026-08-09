import Link from "next/link";
import type {
  ApplicationSummary,
  HumanActionView,
  JobSummary,
  ReadinessReport,
} from "@/lib/types";
import { StatusPill } from "./StatusPill";

interface PipelineStage {
  title: string;
  description: string;
  href: string;
  action: string;
}

const terminalStates = new Set([
  "submitted",
  "confirmed",
  "rejected",
  "interview",
  "offer",
  "withdrawn",
]);

function activeStage(
  readiness: ReadinessReport,
  jobs: JobSummary[],
  applications: ApplicationSummary[],
  actions: HumanActionView[],
): number {
  if (readiness.status !== "ready") return 0;
  if (!jobs.length || !applications.length) return 1;
  const application = applications[0];
  if (application.state === "review_pending" || application.state === "materials_ready") return 2;
  if (application.state === "application_started" || application.state === "form_filling") return 3;
  if (
    application.state === "human_action_required" ||
    actions.some((action) => action.status === "pending")
  )
    return 4;
  if (application.state === "ready_to_submit" || application.state === "submitting") return 5;
  return terminalStates.has(application.state) ? 6 : 2;
}

export function GuidedPipeline({
  candidateId,
  readiness,
  jobs,
  applications,
  actions,
}: {
  candidateId: string;
  readiness: ReadinessReport;
  jobs: JobSummary[];
  applications: ApplicationSummary[];
  actions: HumanActionView[];
}) {
  const encodedCandidate = encodeURIComponent(candidateId);
  const application = applications[0];
  const current = activeStage(readiness, jobs, applications, actions);
  const applicationHref = application
    ? `/applications/${application.application_id}?candidate_id=${encodedCandidate}`
    : `/applications?candidate_id=${encodedCandidate}`;
  const stages: PipelineStage[] = [
    {
      title: "1. Candidate readiness",
      description: "Validate the facts, approvals, legal answers, and application boundaries.",
      href: `/candidates/${encodedCandidate}/readiness`,
      action: readiness.status === "ready" ? "Review readiness" : "Resolve readiness blockers",
    },
    {
      title: "2. Select a job",
      description: "Review one scored opening and choose whether it deserves tailored materials.",
      href: `/jobs?candidate_id=${encodedCandidate}`,
      action: jobs.length ? "Review selected jobs" : "Find and select a job",
    },
    {
      title: "3. Review materials",
      description: "Check the exact CV, cover letter, answers, and their source-fact support.",
      href: applicationHref,
      action: "Review the application materials",
    },
    {
      title: "4. Run a safe dry run",
      description: "Fill the isolated synthetic form, capture evidence, and never click submit.",
      href: applicationHref,
      action: "Start or check the safe dry run",
    },
    {
      title: "5. Complete human actions",
      description: "Handle CAPTCHA, OTP, or an ambiguous question yourself in the preserved session.",
      href: `/actions?candidate_id=${encodedCandidate}`,
      action: "Open the human-action queue",
    },
    {
      title: "6. Give controlled approval",
      description: "Review consequences and explicitly approve only the prepared fictional or controlled action.",
      href: applicationHref,
      action: "Review the final controlled approval",
    },
  ];

  return (
    <section className="panel guided-pipeline" aria-labelledby="guided-pipeline-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Normal first-version workflow</p>
          <h2 id="guided-pipeline-heading">Your next safe action</h2>
        </div>
        <p>One stage is active at a time. Backend state decides when the next stage opens.</p>
      </div>
      <ol className="pipeline-stages">
        {stages.map((stage, index) => {
          const complete = current > index;
          const active = current === index;
          return (
            <li className={active ? "pipeline-stage current" : "pipeline-stage"} key={stage.title}>
              <StatusPill status={complete ? "READY" : active ? "READY_WITH_WARNINGS" : "NOT_CONFIGURED"} />
              <h3>{stage.title}</h3>
              <p>{stage.description}</p>
              {active ? (
                <Link className="button primary" href={stage.href}>
                  {stage.action}
                </Link>
              ) : (
                <span className="muted">{complete ? "Complete" : "Waiting for the previous stage"}</span>
              )}
            </li>
          );
        })}
      </ol>
      {current === 6 ? (
        <p className="form-message success">This workflow has reached a recorded outcome.</p>
      ) : null}
    </section>
  );
}
