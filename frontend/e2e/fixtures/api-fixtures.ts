import type { Page, Route } from "@playwright/test";

const candidateId = "example_candidate";
const applicationId = "00000000-0000-0000-0000-000000000111";
const jobId = "00000000-0000-0000-0000-000000000222";

const summary = {
  application_id: applicationId,
  candidate_id: candidateId,
  job_id: jobId,
  company: "Fictional Robotics Ltd",
  role: "Machine Learning Engineer",
  score: 88,
  state: "confirmed",
  last_event: "SUBMISSION_CONFIRMED",
  updated_at: "2026-08-05T10:00:00Z",
  next_action: "Monitor correspondence",
};

const application = {
  ...summary,
  source_url: "https://synthetic.invalid/jobs/fixture-1",
  ats_platform: "greenhouse",
  documents: [],
  answers: [],
  events: [],
  review: null,
  correspondence: [],
  archive_available: true,
  confirmation_reference: "SYNTHETIC-CONFIRMATION-001",
  submitted_at: "2026-08-05T10:00:00Z",
  material_policy: null,
};

const artifact = (kind: string, suffix: string, contentType: string) => ({
  artifact_id: `00000000-0000-0000-0000-000000000${suffix}`,
  application_id: applicationId,
  candidate_id: candidateId,
  kind,
  version: 1,
  sha256: suffix.repeat(64).slice(0, 64),
  content_type: contentType,
  immutable: true,
  download_path: `/api/applications/${applicationId}/artifacts/${suffix}`,
  metadata: { backend_confirmed: true },
  created_at: "2026-08-05T10:00:00Z",
});

const artifacts = [
  artifact("submitted_cv", "401", "application/pdf"),
  artifact("submitted_cover_letter", "402", "application/pdf"),
  artifact("submitted_answers", "403", "application/json"),
  { ...artifact("submission_receipt", "404", "application/json"), version: 2 },
];

const readiness = {
  candidate_id: candidateId,
  status: "blocked",
  issues: [],
  capabilities: [
    {
      capability: "submission",
      label: "Controlled submission",
      status: "blocked",
      blockers: ["legal_status_not_approved"],
    },
  ],
  domains: [
    {
      domain: "legal_status",
      label: "Legal status",
      field_path: "legal_status",
      status: "blocked",
      issues: [
        {
          code: "approval_required",
          message: "Legal answers require explicit approval.",
          field_path: "legal_status",
        },
      ],
    },
  ],
};

const job = {
  job_id: jobId,
  candidate_id: candidateId,
  external_job_id: "fixture-1",
  requisition_id: "REQ-1",
  company: "Fictional Robotics Ltd",
  company_domain: "fictional-robotics.invalid",
  company_stage: "growth",
  team: "ML Platform",
  title: "Machine Learning Engineer",
  normalized_title: "machine learning engineer",
  location: "Paris",
  normalized_location: "paris",
  remote_policy: "hybrid",
  employment_type: "full_time",
  seniority: "mid",
  source: "fixture",
  source_url: "https://synthetic.invalid/jobs/fixture-1",
  ats_platform: "greenhouse",
  posted_at: "2026-08-01T00:00:00Z",
  deadline: null,
  expected_start_date: null,
  verified_open_at: "2026-08-05T09:00:00Z",
  salary_display: "EUR 60,000–70,000",
  salary_min: "60000",
  salary_max: "70000",
  salary_currency: "EUR",
  salary_period: "year",
  salary_source: "job description",
  visa_requirements: "Not stated",
  work_authorization_requirements: "EU work authorization",
  required_experience_years_min: 2,
  required_experience_years_max: 4,
  required_languages: [{ language: "English", minimum_level: "C1" }],
  role_category: "target",
  score: 88,
  state: "shortlisted",
  hard_blockers: [],
  possible_duplicate: false,
  stale: false,
  description_raw: "Build deterministic ML systems.",
  description_normalized: "Build deterministic ML systems.",
  source_verified: true,
  source_trust_level: "official_ats",
  classification_confidence: 0.96,
  proposed_action: "prepare",
  required_skills: ["Python"],
  preferred_skills: ["SQL"],
  requirements: [
    {
      requirement: "Production Python",
      kind: "mandatory",
      status: "supported",
      evidence: ["fictional_experience_1"],
    },
  ],
  score_dimensions: [
    { name: "role_fit", points: 40, explanation: "Configured target role." },
  ],
  bonuses: [],
  penalties: [],
  salary_evidence: "Salary shown on source.",
  salary_confidence: 1,
  selected_experience: ["fictional_experience_1"],
  selected_projects: [],
  security_findings: [],
};

const settings = {
  candidate_id: candidateId,
  automation_mode: "approval_required",
  discovery_enabled: true,
  emergency_stopped: false,
  allowed_ats_adapters: ["greenhouse"],
  tested_ats_adapters: [],
  dry_run_acceptance_passed: false,
  explicit_autonomy_confirmation: false,
  maximum_applications_per_day: 3,
  maximum_applications_per_week: 10,
  maximum_applications_per_company_30_days: 1,
  browser_session_retention_days: 30,
  autonomy_blockers: ["no_tested_ats_adapter", "dry_run_acceptance_not_passed"],
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export async function installApiFixtures(page: Page): Promise<void> {
  await page.route("http://localhost:8000/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/auth/local-session") {
      return json(route, {
        session_token: "fixture-session",
        csrf_token: "fixture-csrf",
        candidate_ids: [candidateId],
      });
    }
    if (path === `/api/candidates/${candidateId}/readiness`) return json(route, readiness);
    if (path === `/api/candidates/${candidateId}`) {
      return json(route, { candidate_id: candidateId, profile_version: "fixture-v1", config: {}, readiness });
    }
    if (path === "/api/jobs/sources") return json(route, []);
    if (path === "/api/jobs") return json(route, [job]);
    if (path === `/api/jobs/${jobId}`) return json(route, job);
    if (path === "/api/applications") return json(route, [summary]);
    if (path === `/api/applications/${applicationId}/artifacts`) return json(route, artifacts);
    if (path.startsWith(`/api/applications/${applicationId}/artifacts/`)) {
      const id = path.split("/").at(-1);
      const selected = artifacts.find((item) => item.artifact_id === id);
      if (!selected) return json(route, { error: { message: "Not found" } }, 404);
      const body = selected.content_type === "application/pdf" ? "%PDF-1.4 fixture" : JSON.stringify({ artifact_id: id });
      return route.fulfill({ status: 200, contentType: selected.content_type, body });
    }
    if (path === `/api/applications/${applicationId}`) return json(route, application);
    if (path === "/api/human-actions") {
      return json(route, [
        {
          action_id: "00000000-0000-0000-0000-000000000301",
          candidate_id: candidateId,
          application_id: applicationId,
          company: "Fictional Robotics Ltd",
          role: "Machine Learning Engineer",
          kind: "captcha",
          status: "pending",
          reason: "CAPTCHA requires human completion in this isolated session.",
          created_at: "2026-08-05T10:00:00Z",
          expires_at: "2026-08-05T10:15:00Z",
          screenshot_available: true,
          browser_session_id: "00000000-0000-0000-0000-000000000302",
          session_opened: false,
        },
      ]);
    }
    if (path === "/api/settings") return json(route, settings);
    if (path === `/api/candidates/${candidateId}/deletion`) {
      return json(route, { error: { code: "deletion_not_found", message: "No deletion." } }, 404);
    }
    return json(route, { error: { code: "fixture_missing", message: `No fixture for ${path}` } }, 404);
  });
}

export const fixtureIds = { applicationId, candidateId, jobId };
