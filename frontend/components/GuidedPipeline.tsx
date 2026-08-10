import Link from "next/link";
import type {
  ApplicationSummary,
  HumanActionView,
  JobSummary,
  ReadinessReport,
} from "@/lib/types";
import { deriveGuidedWorkflowFocus } from "@/lib/guided-workflow";
import { StatusPill } from "./StatusPill";

interface PipelineStage {
  title: string;
  description: string;
  href: string;
  action: string;
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
  const focus = deriveGuidedWorkflowFocus(candidateId, readiness, jobs, applications, actions);
  const applicationHref = focus.application
    ? `/applications/${focus.application.application_id}?candidate_id=${encodedCandidate}`
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
          const complete = focus.stage > index;
          const active = focus.stage === index;
          return (
            <li className={active ? "pipeline-stage current" : "pipeline-stage"} key={stage.title}>
              <StatusPill status={complete ? "READY" : active && focus.blocked ? "BLOCKED" : active ? "READY_WITH_WARNINGS" : "NOT_CONFIGURED"} />
              <h3>{stage.title}</h3>
              <p>{stage.description}</p>
              {active ? (
                <Link className="button primary" href={focus.href ?? stage.href}>
                  {focus.action ?? stage.action}
                </Link>
              ) : (
                <span className="muted">{complete ? "Complete" : "Waiting for the previous stage"}</span>
              )}
            </li>
          );
        })}
      </ol>
      {focus.stage === 6 ? (
        <p className="form-message success">
          This workflow has reached a backend-recorded outcome. {focus.outcome}
          {focus.href && focus.action ? <> <Link href={focus.href}>{focus.action}</Link>.</> : null}
        </p>
      ) : focus.outcome ? (
        <p className="form-message">{focus.outcome}</p>
      ) : null}
    </section>
  );
}
