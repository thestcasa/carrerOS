import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("overview exposes one plain-language next action from backend readiness", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your next safe action" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Resolve readiness blockers" })).toHaveAttribute(
    "href",
    `/candidates/${fixtureIds.candidateId}/readiness`,
  );
  await expect(page.getByRole("link", { name: "Start or check the safe dry run" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Review the final controlled approval" })).toHaveCount(0);
});

test("active candidate follows navigation and readiness blockers link to editing", async ({ page }) => {
  await page.goto(`/candidates/${fixtureIds.candidateId}/readiness`);
  await expect(page.getByRole("heading", { name: "Readiness by capability" })).toBeVisible();
  const editLink = page.getByRole("link", { name: /Edit domain/ });
  await expect(editLink).toHaveAttribute("href", `/candidates/${fixtureIds.candidateId}/profile?section=legal_status`);

  await page.getByRole("link", { name: "Jobs" }).click();
  await expect(page).toHaveURL(new RegExp(`/jobs\\?candidate_id=${fixtureIds.candidateId}$`));
  await expect(page.getByText(`Active: ${fixtureIds.candidateId}`)).toHaveCount(1);
});

test("job analysis exposes evidence without a submission action", async ({ page }) => {
  await page.goto(`/jobs/${fixtureIds.jobId}?candidate_id=${fixtureIds.candidateId}`);
  await expect(page.getByRole("heading", { name: "Requirements", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Production Python" })).toBeVisible();
  await expect(page.getByRole("button", { name: /submit/i })).toHaveCount(0);
  await expect(page.getByText(/does not record an application or submission/i)).toBeVisible();
});

test("confirmed application identifies every exact submitted artifact", async ({ page }) => {
  await page.goto(`/applications/${fixtureIds.applicationId}?candidate_id=${fixtureIds.candidateId}`);
  await expect(page.getByRole("heading", { name: "Exact backend-confirmed submission" })).toBeVisible();
  for (const label of [
    "Exact submitted CV",
    "Exact submitted cover letter",
    "Exact submitted answers",
    "Final submission receipt",
  ]) {
    const card = page.getByRole("article", { name: label });
    await expect(card.getByRole("heading", { name: label })).toBeVisible();
    await expect(card.getByRole("button", { name: /Download exact PDF|Preview escaped text/ })).toBeEnabled();
  }
  await expect(page.getByText("SYNTHETIC-CONFIRMATION-001", { exact: true }).first()).toBeVisible();
});
