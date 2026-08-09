import { expect, test } from "@playwright/test"

test.describe("AI Card Master smoke", () => {
  test("landing loads and exposes primary CTAs", async ({ page }) => {
    await page.goto("/landing")
    await expect(page.locator("body")).toBeVisible()
    const editorCta = page
      .getByRole("button", { name: /сгенерировать|editor|бесплатно/i })
      .first()
    await expect(editorCta).toBeVisible()
  })

  test("editor sandbox mounts canvas chrome", async ({ page }) => {
    await page.goto("/editor/demo")
    await expect(page.getByRole("button", { name: /сохранить|save/i })).toBeVisible({
      timeout: 20_000,
    })
  })
})
