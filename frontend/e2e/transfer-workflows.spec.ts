import { expect, test } from "@playwright/test";
import { fixtureIds, installApiFixtures } from "./fixtures/api-fixtures";

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("CV upload is a candidate-scoped unapproved draft before profile review", async ({ page }) => {
  const commands: Array<{ method: string; path: string; idempotency: string | undefined }> = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.includes("/cv-imports")) {
      commands.push({
        method: request.method(),
        path: url.pathname,
        idempotency: request.headers()["idempotency-key"],
      });
    }
  });

  await page.goto(`/candidates/${fixtureIds.candidateId}/profile`);
  await page.getByLabel("CV file").setInputFiles({
    name: "fictional-candidate.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Fictional Candidate\\nML Engineer at Fictional Research Lab"),
  });
  await page.getByRole("button", { name: "Review CV details" }).click();

  await expect(page.getByText(/We found 0 education and 1 experience/)).toBeVisible();
  await expect(page.getByText("Imported facts are drafts and remain unapproved.")).toBeVisible();
  await page.getByRole("button", { name: "Add to my profile" }).click();
  await expect(page.getByText("Version fixture-v2")).toBeVisible();

  expect(commands).toHaveLength(2);
  expect(commands.map((command) => command.method)).toEqual(["POST", "POST"]);
  expect(commands.every((command) => command.path.includes(fixtureIds.candidateId))).toBe(true);
  expect(commands.every((command) => Boolean(command.idempotency))).toBe(true);
});

test("application artifacts download as the exact scoped file type", async ({ page }) => {
  await page.goto(
    `/applications/${fixtureIds.applicationId}?candidate_id=${fixtureIds.candidateId}`,
  );
  const files = page.getByRole("heading", { name: "Submitted package and receipt" })
    .locator("..");
  const downloadPromise = page.waitForEvent("download");
  await files.getByRole("button", { name: "Download PDF" }).first().click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toBe("submitted_cv-v1.pdf");
  expect(await download.failure()).toBeNull();
  expect(await download.path()).not.toBeNull();
});
