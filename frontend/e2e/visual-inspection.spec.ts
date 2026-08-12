import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

const mobileRoutes = [
  ["home", "/"],
  ["jobs", `/jobs?candidate_id=${fixtureIds.candidateId}`],
  ["job", `/jobs/${fixtureIds.jobId}?candidate_id=${fixtureIds.candidateId}`],
  ["applications", `/applications?candidate_id=${fixtureIds.candidateId}`],
  ["application", `/applications/${fixtureIds.applicationId}?candidate_id=${fixtureIds.candidateId}`],
  ["actions", `/actions?candidate_id=${fixtureIds.candidateId}`],
  ["profile", `/candidates/${fixtureIds.candidateId}/profile`],
] as const;

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("capture representative mobile light and dark compositions", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [name, route] of mobileRoutes) {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.locator(".loading-state")).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath(`mobile-light-${name}.png`),
      fullPage: true,
    });
  }

  await page.goto("/");
  await page.getByRole("button", { name: "Switch to dark mode" }).first().click();
  for (const [name, route] of mobileRoutes) {
    await page.goto(route);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator(".loading-state")).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath(`mobile-dark-${name}.png`),
      fullPage: true,
    });
  }
});

test("capture representative desktop control-center compositions", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const [name, route] of mobileRoutes.slice(0, 5)) {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.locator(".loading-state")).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath(`desktop-${name}.png`),
      fullPage: true,
    });
  }
});
