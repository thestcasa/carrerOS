import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
  await page.setViewportSize({ width: 390, height: 844 });
});

test("safe mobile navigation, job tabs, search, sorting, and filters all respond", async ({ page }) => {
  await page.goto(`/jobs?candidate_id=${fixtureIds.candidateId}`);
  const navigation = page.getByRole("navigation", { name: "Mobile navigation" });
  await expect(navigation.getByRole("link", { name: "Jobs" })).toHaveAttribute("aria-current", "page");

  await page.getByRole("button", { name: "All jobs" }).click();
  await expect(page.getByRole("button", { name: "All jobs" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Shortlisted" }).click();
  await expect(page.getByRole("button", { name: "Shortlisted" })).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("Search jobs").fill("no fictional result");
  await expect(page.getByRole("heading", { name: "No jobs match these filters" })).toBeVisible();
  await page.getByLabel("Search jobs").fill("");
  await page.getByLabel("Sort jobs").selectOption("newest");

  const filterButton = page.getByRole("button", { name: "Open job filters" });
  await filterButton.click();
  const sheet = page.getByRole("dialog", { name: "Filters" });
  await expect(sheet).toBeVisible();
  await sheet.getByLabel(/Minimum match score/).fill("95");
  await expect(sheet.getByRole("button", { name: "Show 0 jobs" })).toBeVisible();
  await sheet.getByRole("button", { name: "Clear filters" }).click();
  await expect(sheet.getByRole("button", { name: "Show 1 job" })).toBeVisible();
  await sheet.getByRole("button", { name: "Show 1 job" }).click();
  await expect(sheet).toHaveCount(0);
  await expect(filterButton).toBeFocused();

  for (const destination of ["Home", "Applications", "Profile"]) {
    await navigation.getByRole("link", { name: destination }).click();
    await expect(page.getByRole("navigation", { name: "Mobile navigation" })
      .getByRole("link", { name: destination })).toHaveAttribute("aria-current", "page");
  }
});

test("safe decision controls open, close, switch views, and disclose technical details", async ({ page }) => {
  await page.goto(
    `/jobs/${fixtureIds.jobId}?candidate_id=${fixtureIds.candidateId}`,
  );
  const matchButton = page.getByRole("button", { name: "View match analysis" });
  await matchButton.click();
  const analysis = page.getByRole("dialog", { name: "Match analysis" });
  await expect(analysis).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(analysis).toHaveCount(0);
  await expect(matchButton).toBeFocused();
  await page.getByText("Advanced job analysis").click();
  await expect(page.getByRole("heading", { name: "Normalized job metadata" })).toBeVisible();

  await page.setViewportSize({ width: 1200, height: 900 });
  await page.goto(`/applications?candidate_id=${fixtureIds.candidateId}`);
  await page.getByRole("button", { name: "Board" }).click();
  await expect(page.getByLabel("Application board")).toBeVisible();
  await page.getByRole("button", { name: "List" }).click();
  await expect(page.getByLabel("Application list")).toBeVisible();

  await page.goto(
    `/applications/${fixtureIds.applicationId}?candidate_id=${fixtureIds.candidateId}`,
  );
  await page.getByText("Technical details and audit trail").click();
  await expect(page.getByRole("heading", { name: "Raw state events" })).toBeVisible();

  await page.goto(`/candidates/${fixtureIds.candidateId}/profile`);
  await page.getByRole("link", { name: "Skills & technologies" }).click();
  await expect(page).toHaveURL(/section=skills/);
  await expect(page.getByRole("heading", { name: "Skills", exact: true })).toBeVisible();
});
