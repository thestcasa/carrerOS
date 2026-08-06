import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

for (const route of [
  `/candidates/${fixtureIds.candidateId}/readiness`,
  `/jobs?candidate_id=${fixtureIds.candidateId}`,
  `/jobs/${fixtureIds.jobId}?candidate_id=${fixtureIds.candidateId}`,
  `/applications/${fixtureIds.applicationId}?candidate_id=${fixtureIds.candidateId}`,
  `/actions?candidate_id=${fixtureIds.candidateId}`,
  `/settings?candidate_id=${fixtureIds.candidateId}`,
]) {
  test(`${route} has no serious or critical axe violations`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    const critical = results.violations.filter(
      (violation) => violation.impact === "critical" || violation.impact === "serious",
    );
    expect(critical).toEqual([]);
  });
}
