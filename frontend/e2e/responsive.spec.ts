import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

const responsiveRoutes = [
  "/",
  `/jobs?candidate_id=${fixtureIds.candidateId}`,
  `/jobs/${fixtureIds.jobId}?candidate_id=${fixtureIds.candidateId}`,
  `/applications/${fixtureIds.applicationId}?candidate_id=${fixtureIds.candidateId}`,
  `/settings?candidate_id=${fixtureIds.candidateId}`,
];

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("primary navigation adapts between desktop and phone layouts", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.locator("h1")).toBeVisible();

  const mobile = testInfo.project.name === "mobile-chromium";
  const desktopNavigation = page.getByRole("navigation", { name: "Primary navigation" });
  const mobileNavigation = page.getByRole("navigation", { name: "Mobile navigation" });

  if (!mobile) {
    await expect(desktopNavigation).toBeVisible();
    await expect(mobileNavigation).toBeHidden();
    return;
  }

  await expect(desktopNavigation).toBeHidden();
  await expect(mobileNavigation).toBeVisible();
  await expect(mobileNavigation.getByRole("link")).toHaveCount(4);

  const viewportHeight = page.viewportSize()?.height;
  const navigationBox = await mobileNavigation.boundingBox();
  expect(viewportHeight).toBeDefined();
  expect(navigationBox).not.toBeNull();
  expect(Math.abs(navigationBox!.y + navigationBox!.height - viewportHeight!)).toBeLessThanOrEqual(1);

  for (const link of await mobileNavigation.getByRole("link").all()) {
    const box = await link.boundingBox();
    expect(box, `mobile navigation target ${await link.textContent()}`).not.toBeNull();
    expect(box!.height, `mobile navigation target ${await link.textContent()}`).toBeGreaterThanOrEqual(48);
  }
});

for (const route of responsiveRoutes) {
  test(`${route} does not overflow the page horizontally`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      body: document.body.scrollWidth,
      document: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    }));

    expect(dimensions.document, `document overflow on ${route}`).toBeLessThanOrEqual(
      dimensions.viewport,
    );
    expect(dimensions.body, `body overflow on ${route}`).toBeLessThanOrEqual(dimensions.viewport);
  });
}

test("phone workflow exposes 48px primary action targets", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "Phone-only target-size contract");

  await page.goto(`/jobs?candidate_id=${fixtureIds.candidateId}`);
  await expect(page.locator("h1")).toBeVisible();

  const primaryActions = page.getByRole("link", {
    name: /Prepare application for|Apply manually for/,
  });
  await expect(primaryActions).toHaveCount(2);
  for (const action of await primaryActions.all()) {
    const box = await action.boundingBox();
    expect(box, `workflow target ${await action.textContent()}`).not.toBeNull();
    expect(box!.height, `workflow target ${await action.textContent()}`).toBeGreaterThanOrEqual(48);
  }
});
