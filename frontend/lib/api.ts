import type {
  ApiErrorBody,
  CandidateDetail,
  CandidateSummary,
  CandidateUpdateResult,
  EditableSection,
  HealthReport,
  JsonObject,
  ReadinessReport,
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init?.headers },
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

export const api = {
  health: () => request<HealthReport>("/api/health"),
  candidates: () => request<CandidateSummary[]>("/api/candidates"),
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
};
