import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("CAPTCHA remains an explicit same-session human action", async ({ page }) => {
  await page.goto(`/actions?candidate_id=${fixtureIds.candidateId}`);
  await expect(page.getByRole("heading", { name: "Needs your attention" })).toBeVisible();
  await expect(page.getByText(/CAPTCHA requires human completion/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Record local takeover handshake" })).toBeVisible();
  await page.getByText("Technical details").click();
  await expect(page.getByText("http://127.0.0.1:8090")).toBeVisible();
  await expect(page.getByText("unavailable", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/never bypassed/i)).toBeVisible();
  await expect(page.getByText(/bypass captcha/i)).toHaveCount(0);
});

test("backend blockers keep autonomous mode disabled", async ({ page }) => {
  await page.goto(`/settings?candidate_id=${fixtureIds.candidateId}`);
  await expect(page.getByRole("button", { name: "autonomous" })).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Tested ATS adapter" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Candidate-scoped dry run" })).toBeVisible();
});
