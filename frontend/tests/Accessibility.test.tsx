import axe from "axe-core";
import { render, type RenderResult } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JobDetail } from "@/components/JobDetail";
import { JobsInbox } from "@/components/JobsInbox";
import { MaterialPreview } from "@/components/MaterialPreview";
import { ReadinessBoard } from "@/components/ReadinessBoard";
import { SubmittedPackageViewer } from "@/components/SubmittedPackageViewer";
import type {
  ApplicationDetail,
  ArtifactView,
  JobDetail as JobDetailData,
  ReadinessReport,
} from "@/lib/types";

async function expectNoBlockingViolations(view: RenderResult) {
  const result = await axe.run(view.container, {
    // jsdom has no canvas implementation; the browser E2E suite owns contrast checks.
    rules: { "color-contrast": { enabled: false } },
  });
  const blocking = result.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(
    blocking.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      targets: violation.nodes.flatMap((node) => node.target),
    })),
  ).toEqual([]);
}

const readiness: ReadinessReport = {
  candidate_id: "example_candidate",
  status: "not_ready",
  issues: [],
  domains: [
    {
      domain: "legal",
      label: "Legal and work authorization",
      status: "BLOCKED",
      field_path: "legal_status",
      issues: [
        {
          code: "legal_status_not_approved",
          message: "Legal status requires explicit approval.",
          domain: "legal",
          field_path: "legal_status.approved_for_automated_use",
          severity: "blocking",
        },
      ],
    },
  ],
  capabilities: [
    {
      capability: "controlled_submission",
      label: "Controlled submission",
      status: "BLOCKED",
      blockers: ["legal"],
    },
  ],
};

const submittedArtifacts: ArtifactView[] = [
  ["submitted_cv", "application/pdf"],
  ["submitted_cover_letter", "application/pdf"],
  ["submitted_answers", "application/json"],
  ["submission_receipt", "application/json"],
].map(([kind, contentType], index) => ({
  artifact_id: `artifact-${index}`,
  application_id: "application-1",
  candidate_id: "example_candidate",
  kind,
  version: kind === "submission_receipt" ? 2 : 1,
  sha256: String(index + 1).repeat(64),
  content_type: contentType,
  immutable: true,
  download_path: `/fixture/${index}`,
  metadata: { backend_confirmed: true },
  created_at: "2026-08-06T10:00:00Z",
}));

const job: JobDetailData = {
  job_id: "job-1",
  candidate_id: "example_candidate",
  external_job_id: "gh-1",
  requisition_id: "REQ-1",
  company: "Fictional Labs",
  company_domain: "fictional.invalid",
  company_stage: "seed",
  team: "Applied AI",
  title: "ML Engineer",
  normalized_title: "machine learning engineer",
  location: "Remote",
  normalized_location: "remote",
  remote_policy: "remote",
  employment_type: "full_time",
  seniority: "early_career",
  source: "official",
  source_url: "https://jobs.example.invalid/1",
  ats_platform: "greenhouse",
  posted_at: "2026-08-01T10:00:00Z",
  deadline: null,
  expected_start_date: null,
  verified_open_at: "2026-08-06T10:00:00Z",
  salary_display: null,
  salary_min: "42000",
  salary_max: "50000",
  salary_currency: "EUR",
  salary_period: "gross_annual",
  salary_source: "job_post",
  visa_requirements: null,
  work_authorization_requirements: "Authorized to work in Spain",
  required_experience_years_min: 1,
  required_experience_years_max: 3,
  required_languages: [{ language: "English", minimum_level: "B2" }],
  role_category: "target",
  score: 87,
  state: "shortlisted",
  hard_blockers: [],
  possible_duplicate: false,
  stale: false,
  description_raw: "Build fictional models.",
  description_normalized: "Build fictional models.",
  source_verified: true,
  source_trust_level: "official",
  classification_confidence: 0.9,
  proposed_action: "prepare",
  required_skills: ["Python"],
  preferred_skills: [],
  requirements: [],
  score_dimensions: [],
  bonuses: [],
  penalties: [],
  salary_evidence: "Explicit job range.",
  salary_confidence: 1,
  selected_experience: [],
  selected_projects: [],
  security_findings: [],
};

const application: ApplicationDetail = {
  application_id: "application-1",
  candidate_id: "example_candidate",
  job_id: "job-1",
  company: "Fictional Labs",
  role: "ML Engineer",
  score: 87,
  state: "review_pending",
  last_event: "INDEPENDENT_REVIEW_COMPLETED",
  updated_at: "2026-08-06T10:00:00Z",
  next_action: "Review materials",
  source_url: "https://jobs.example.invalid/1",
  ats_platform: "greenhouse",
  documents: [
    {
      document_id: "document-1",
      kind: "cv",
      version: 1,
      content: "Fictional approved CV content",
      sha256: "a".repeat(64),
      immutable: false,
      validated: true,
      evidence_ids: ["experience_example_1"],
      created_at: "2026-08-06T10:00:00Z",
      provenance: [
        {
          text: "Built typed APIs",
          evidence_ids: ["experience_example_1"],
          source_paths: ["experience.items[0]"],
        },
      ],
      revision_actor: null,
      base_document_id: null,
      render_metadata: {
        template_id: "technical_two_page",
        template_version: "1.0",
        page_count: 1,
        extraction_matches: true,
      },
    },
  ],
  answers: [],
  events: [],
  review: { decision: "pass", semantic_passed: true, report: {} },
  correspondence: [],
  archive_available: false,
  confirmation_reference: null,
  submitted_at: null,
  material_policy: null,
};

describe("accessibility-critical component checks", () => {
  it("has no serious or critical violations in candidate readiness", async () => {
    await expectNoBlockingViolations(
      render(<ReadinessBoard candidateId="example_candidate" report={readiness} />),
    );
  });

  it("has no serious or critical violations in jobs list and detail", async () => {
    await expectNoBlockingViolations(
      render(<JobsInbox candidateId="example_candidate" jobs={[job]} />),
    );
    await expectNoBlockingViolations(render(<JobDetail job={job} onAction={vi.fn()} />));
  });

  it("has no serious or critical violations in material review", async () => {
    await expectNoBlockingViolations(
      render(<MaterialPreview application={application} onSaveRevision={vi.fn()} />),
    );
  });

  it("has no serious or critical violations in the exact submitted package", async () => {
    await expectNoBlockingViolations(
      render(
        <SubmittedPackageViewer
          applicationId="application-1"
          artifacts={submittedArtifacts}
          candidateId="example_candidate"
          confirmationReference="SYNTHETIC-CONFIRMATION-001"
        />,
      ),
    );
  });
});
