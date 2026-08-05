import type {
  ApiErrorBody,
  AnalyticsOverview,
  ApplicationDetail,
  ApplicationSummary,
  ArtifactView,
  AuthorizationView,
  CandidateDetail,
  CandidateSummary,
  CandidateUpdateResult,
  CVImportDraft,
  DiscoveryRequest,
  DiscoveryResult,
  DiscoverySourceView,
  DiscoverySourceCreate,
  DiscoverySourceUpdate,
  EditableSection,
  HealthReport,
  HumanActionView,
  InterviewPreparationPackage,
  JsonObject,
  JobDetail,
  JobSummary,
  ReadinessReport,
  SecurityEventView,
  SettingsView,
  SettingsUpdate,
  SubmissionResultView,
} from "./types";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface LocalSession {
  session_token: string;
  csrf_token: string;
  candidate_ids: string[];
}

let memorySession: LocalSession | null = null;

function clearLocalSession(): void {
  memorySession = null;
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem("careeros-local-session");
  }
}

async function localSession(): Promise<LocalSession> {
  if (memorySession) return memorySession;
  if (typeof window !== "undefined") {
    const stored = window.sessionStorage.getItem("careeros-local-session");
    if (stored) {
      try {
        memorySession = JSON.parse(stored) as LocalSession;
        return memorySession;
      } catch {
        window.sessionStorage.removeItem("careeros-local-session");
      }
    }
  }
  const response = await fetch(`${API_BASE}/api/auth/local-session`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) throw new ApiError("Local session could not be established.", "authentication_failed", response.status);
  memorySession = (await response.json()) as LocalSession;
  if (typeof window !== "undefined") window.sessionStorage.setItem("careeros-local-session", JSON.stringify(memorySession));
  return memorySession;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const session = await localSession();
  const method = init?.method ?? "GET";
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.session_token}`,
      ...(method === "GET" ? {} : { "X-CSRF-Token": session.csrf_token }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      body.error?.message ?? `Request failed with status ${response.status}.`,
      body.error?.code ?? "request_failed",
      response.status,
    );
  }
  return (await response.json()) as T;
}

function commandHeaders(idempotencyKey: string): HeadersInit {
  return { "Idempotency-Key": idempotencyKey };
}

export const api = {
  health: () => request<HealthReport>("/api/health"),
  candidates: () => request<CandidateSummary[]>("/api/candidates"),
  createCandidate: async (candidateId: string, displayName: string) => {
    const candidate = await request<CandidateDetail>("/api/candidates", {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId, display_name: displayName }),
    });
    clearLocalSession();
    return candidate;
  },
  exportCandidate: (candidateId: string) =>
    request<JsonObject>(`/api/candidates/${encodeURIComponent(candidateId)}/export`),
  createCvImport: (candidateId: string, filename: string, contentBase64: string) =>
    request<CVImportDraft>(
      `/api/candidates/${encodeURIComponent(candidateId)}/cv-imports`,
      {
        method: "POST",
        body: JSON.stringify({ filename, content_base64: contentBase64 }),
      },
    ),
  applyCvImport: (candidateId: string, importId: string) =>
    request<CandidateDetail>(
      `/api/candidates/${encodeURIComponent(candidateId)}/cv-imports/${encodeURIComponent(importId)}/apply`,
      { method: "POST" },
    ),
  candidate: (candidateId: string) =>
    request<CandidateDetail>(`/api/candidates/${encodeURIComponent(candidateId)}`),
  readiness: (candidateId: string) =>
    request<ReadinessReport>(
      `/api/candidates/${encodeURIComponent(candidateId)}/readiness`,
    ),
  updateSection: (candidateId: string, section: EditableSection, data: JsonObject) =>
    request<CandidateUpdateResult>(
      `/api/candidates/${encodeURIComponent(candidateId)}`,
      { method: "PATCH", body: JSON.stringify({ section, data }) },
    ),
  jobs: (candidateId: string) =>
    request<JobSummary[]>(`/api/jobs?candidate_id=${encodeURIComponent(candidateId)}`),
  job: (candidateId: string, jobId: string) =>
    request<JobDetail>(
      `/api/jobs/${encodeURIComponent(jobId)}?candidate_id=${encodeURIComponent(candidateId)}`,
    ),
  discoverJobs: (input: DiscoveryRequest, idempotencyKey: string) =>
    request<DiscoveryResult>("/api/jobs/discover", {
      method: "POST",
      headers: commandHeaders(idempotencyKey),
      body: JSON.stringify(input),
    }),
  verifyJob: (candidateId: string, jobId: string, idempotencyKey: string) =>
    request<JobDetail>(
      `/api/jobs/${encodeURIComponent(jobId)}/verify?candidate_id=${encodeURIComponent(candidateId)}`,
      { method: "POST", headers: commandHeaders(idempotencyKey) },
    ),
  shortlistJob: (candidateId: string, jobId: string, idempotencyKey: string) =>
    request<JobDetail>(
      `/api/jobs/${encodeURIComponent(jobId)}/shortlist?candidate_id=${encodeURIComponent(candidateId)}`,
      { method: "POST", headers: commandHeaders(idempotencyKey) },
    ),
  skipJob: (candidateId: string, jobId: string, idempotencyKey: string) =>
    request<JobDetail>(
      `/api/jobs/${encodeURIComponent(jobId)}/skip?candidate_id=${encodeURIComponent(candidateId)}`,
      { method: "POST", headers: commandHeaders(idempotencyKey) },
    ),
  generateMaterials: (candidateId: string, jobId: string, idempotencyKey: string) =>
    request<ApplicationDetail>(
      `/api/jobs/${encodeURIComponent(jobId)}/generate-materials?candidate_id=${encodeURIComponent(candidateId)}`,
      { method: "POST", headers: commandHeaders(idempotencyKey) },
    ),
  applications: (candidateId: string) =>
    request<ApplicationSummary[]>(`/api/applications?candidate_id=${encodeURIComponent(candidateId)}`),
  application: (candidateId: string, applicationId: string) =>
    request<ApplicationDetail>(`/api/applications/${encodeURIComponent(applicationId)}?candidate_id=${encodeURIComponent(candidateId)}`),
  applicationCommand: (candidateId: string, applicationId: string, command: "approve-materials" | "start", idempotencyKey: string) =>
    request<ApplicationDetail>(`/api/applications/${encodeURIComponent(applicationId)}/${command}?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", headers: commandHeaders(idempotencyKey) }),
  dryRun: (candidateId: string, applicationId: string, challenge: "captcha" | "otp" | null, idempotencyKey: string) =>
    request<ApplicationDetail>(`/api/applications/${encodeURIComponent(applicationId)}/dry-run?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", headers: commandHeaders(idempotencyKey), body: JSON.stringify({ challenge }) }),
  authorize: (candidateId: string, applicationId: string, idempotencyKey: string) =>
    request<AuthorizationView>(`/api/applications/${encodeURIComponent(applicationId)}/authorize?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", headers: commandHeaders(idempotencyKey) }),
  submitSynthetic: (candidateId: string, applicationId: string, authorizationId: string, idempotencyKey: string) =>
    request<SubmissionResultView>(`/api/applications/${encodeURIComponent(applicationId)}/submit?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", headers: commandHeaders(idempotencyKey), body: JSON.stringify({ authorization_id: authorizationId, synthetic_fixture_acknowledged: true }) }),
  artifacts: (candidateId: string, applicationId: string) =>
    request<ArtifactView[]>(`/api/applications/${encodeURIComponent(applicationId)}/artifacts?candidate_id=${encodeURIComponent(candidateId)}`),
  downloadArtifact: async (
    candidateId: string,
    applicationId: string,
    artifactId: string,
  ) => {
    const session = await localSession();
    const response = await fetch(
      `${API_BASE}/api/applications/${encodeURIComponent(applicationId)}/artifacts/${encodeURIComponent(artifactId)}?candidate_id=${encodeURIComponent(candidateId)}`,
      {
        cache: "no-store",
        headers: { Authorization: `Bearer ${session.session_token}` },
      },
    );
    if (!response.ok) {
      throw new ApiError(
        "Artifact download failed safely.",
        "artifact_download_failed",
        response.status,
      );
    }
    return response.blob();
  },
  prepareInterview: (candidateId: string, applicationId: string, idempotencyKey: string) =>
    request<InterviewPreparationPackage>(
      `/api/applications/${encodeURIComponent(applicationId)}/prepare-interview?candidate_id=${encodeURIComponent(candidateId)}`,
      { method: "POST", headers: commandHeaders(idempotencyKey) },
    ),
  humanActions: (candidateId: string) =>
    request<HumanActionView[]>(`/api/human-actions?candidate_id=${encodeURIComponent(candidateId)}`),
  openHumanSession: (candidateId: string, actionId: string, idempotencyKey: string) =>
    request<HumanActionView>(`/api/human-actions/${encodeURIComponent(actionId)}/open-session?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", headers: commandHeaders(idempotencyKey) }),
  completeHumanAction: (candidateId: string, actionId: string, idempotencyKey: string) =>
    request<HumanActionView>(`/api/human-actions/${encodeURIComponent(actionId)}/complete?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", headers: commandHeaders(idempotencyKey) }),
  securityEvents: (candidateId: string) =>
    request<SecurityEventView[]>(`/api/security-events?candidate_id=${encodeURIComponent(candidateId)}`),
  resolveSecurityEvent: (candidateId: string, eventId: string) =>
    request<SecurityEventView>(`/api/security-events/${encodeURIComponent(eventId)}/resolve?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST" }),
  settings: (candidateId: string) =>
    request<SettingsView>(`/api/settings?candidate_id=${encodeURIComponent(candidateId)}`),
  discoverySources: (candidateId: string) =>
    request<DiscoverySourceView[]>(`/api/jobs/sources?candidate_id=${encodeURIComponent(candidateId)}`),
  createDiscoverySource: (candidateId: string, input: DiscoverySourceCreate, idempotencyKey: string) =>
    request<DiscoverySourceView>(`/api/jobs/sources?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST", headers: commandHeaders(idempotencyKey), body: JSON.stringify(input) }),
  updateDiscoverySource: (candidateId: string, sourceId: string, input: DiscoverySourceUpdate, idempotencyKey: string) =>
    request<DiscoverySourceView>(`/api/jobs/sources/${encodeURIComponent(sourceId)}?candidate_id=${encodeURIComponent(candidateId)}`, { method: "PATCH", headers: commandHeaders(idempotencyKey), body: JSON.stringify(input) }),
  updateSettings: (input: SettingsUpdate) =>
    request<SettingsView>("/api/settings", { method: "PATCH", body: JSON.stringify(input) }),
  emergencyStop: (candidateId: string) =>
    request<SettingsView>(`/api/automation/emergency-stop?candidate_id=${encodeURIComponent(candidateId)}`, { method: "POST" }),
  analytics: (candidateId: string) =>
    request<AnalyticsOverview>(`/api/analytics/overview?candidate_id=${encodeURIComponent(candidateId)}`),
};
