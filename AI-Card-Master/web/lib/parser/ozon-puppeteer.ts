/**
 * Headless Chromium + stealth plugin fallback for Ozon anti-bot pages.
 * Kept in a separate module so Next.js can treat Chromium as a server-only dep.
 */
export async function launchOzonBrowserPage(productUrl: string): Promise<{
  nuxtState: unknown | null
  html: string
  title: string
  description: string
}> {
  const puppeteer = (await import("puppeteer-extra")).default
  const StealthPlugin = (await import("puppeteer-extra-plugin-stealth")).default
  const { nextDesktopUserAgent } = await import("@/lib/parser/user-agents")
  puppeteer.use(StealthPlugin())

  const browser = await puppeteer.launch({
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-blink-features=AutomationControlled",
      "--lang=ru-RU,ru",
    ],
  })

  try {
    const page = await browser.newPage()
    await page.setViewport({ width: 1365, height: 900 })
    await page.setExtraHTTPHeaders({
      "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    await page.setUserAgent(nextDesktopUserAgent())

    await page.goto(productUrl, {
      waitUntil: "domcontentloaded",
      timeout: 45_000,
    })

    await page
      .waitForFunction(
        () =>
          typeof (window as unknown as { __NUXT__?: unknown }).__NUXT__ !==
            "undefined" || document.title.length > 0,
        { timeout: 12_000 },
      )
      .catch(() => undefined)

    await new Promise((resolve) => setTimeout(resolve, 1_200))

    const html = await page.content()
    const evaluated = await page.evaluate(() => {
      const w = window as unknown as { __NUXT__?: unknown }
      const title = document.title || ""
      const description =
        document
          .querySelector('meta[property="og:description"]')
          ?.getAttribute("content") ||
        document
          .querySelector('meta[name="description"]')
          ?.getAttribute("content") ||
        ""
      return {
        nuxt: w.__NUXT__ ?? null,
        title,
        description,
      }
    })

    return {
      nuxtState: evaluated.nuxt ?? null,
      html,
      title: evaluated.title,
      description: evaluated.description,
    }
  } finally {
    await browser.close().catch(() => undefined)
  }
}
