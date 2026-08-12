import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

const routes = [
  "/",
  "/candidates",
  `/jobs?candidate_id=${fixtureIds.candidateId}`,
  `/jobs/${fixtureIds.jobId}?candidate_id=${fixtureIds.candidateId}`,
  `/applications?candidate_id=${fixtureIds.candidateId}`,
  `/applications/${fixtureIds.applicationId}?candidate_id=${fixtureIds.candidateId}`,
  `/applications/${fixtureIds.applicationId}/materials?candidate_id=${fixtureIds.candidateId}`,
  `/actions?candidate_id=${fixtureIds.candidateId}`,
  `/candidates/${fixtureIds.candidateId}/profile`,
  `/candidates/${fixtureIds.candidateId}/readiness`,
  `/settings?candidate_id=${fixtureIds.candidateId}`,
  `/analytics?candidate_id=${fixtureIds.candidateId}`,
  `/security?candidate_id=${fixtureIds.candidateId}`,
];

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

for (const route of routes) {
  test(`${route} renders every visible section and named control`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.getByText("We could not load this view.")).toHaveCount(0);
    await expect(page.getByText("Invalid profile selection")).toHaveCount(0);
    await expect(page.getByText("This page couldnt load")).toHaveCount(0);

    for (const control of await page.locator("button:visible").all()) {
      const name = await control.evaluate((element) =>
        element.getAttribute("aria-label")?.trim() || element.textContent?.trim(),
      );
      expect(name, `unnamed control on ${route}`).toBeTruthy();
      const box = await control.boundingBox();
      expect(box, `unrendered control ${name} on ${route}`).not.toBeNull();
      expect(box!.width).toBeGreaterThan(0);
      expect(box!.height).toBeGreaterThan(0);
    }

    for (const region of await page.locator("section:visible, article:visible").all()) {
      const box = await region.boundingBox();
      expect(box, `collapsed section on ${route}`).not.toBeNull();
      expect(box!.width).toBeGreaterThan(0);
      expect(box!.height).toBeGreaterThan(0);
    }

    const overflow = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    }));
    expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
  });
}

test("theme toggle changes rendered tokens and persists after navigation", async ({ page }) => {
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Switch to dark mode" }).first();
  const light = await page.evaluate(() => ({
    background: getComputedStyle(document.body).backgroundColor,
    color: getComputedStyle(document.body).color,
  }));
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const dark = await page.evaluate(() => ({
    background: getComputedStyle(document.body).backgroundColor,
    color: getComputedStyle(document.body).color,
    stored: localStorage.getItem("careeros-theme"),
  }));
  expect(dark.background).not.toBe(light.background);
  expect(dark.color).not.toBe(light.color);
  expect(dark.stored).toBe("dark");

  await page.goto(`/jobs?candidate_id=${fixtureIds.candidateId}`);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("button", { name: "Switch to light mode" }).first()).toBeVisible();
});
