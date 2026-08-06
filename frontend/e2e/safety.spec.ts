import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("CAPTCHA remains an explicit same-session human action", async ({ page }) => {
  await page.goto(`/actions?candidate_id=${fixtureIds.candidateId}`);
  await expect(page.getByRole("heading", { name: "Human actions" })).toBeVisible();
  await expect(page.getByText(/CAPTCHA requires human completion/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Open recoverable browser session" })).toBeVisible();
  await expect(page.getByText(/never bypasses them/i)).toBeVisible();
  await expect(page.getByText(/bypass captcha/i)).toHaveCount(0);
});

test("backend blockers keep autonomous mode disabled", async ({ page }) => {
  await page.goto(`/settings?candidate_id=${fixtureIds.candidateId}`);
  await expect(page.getByRole("button", { name: "autonomous" })).toBeDisabled();
  await expect(page.getByText("no tested ats adapter")).toBeVisible();
  await expect(page.getByText("dry run acceptance not passed")).toBeVisible();
});
