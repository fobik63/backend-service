import { describe, expect, it } from "vitest"

import {
  MIN_PURCHASE_COINS,
  packageBadge,
  quoteCoinPurchase,
  unitPriceRubForCoins,
} from "@/lib/billing/coin-pricing"

describe("quoteCoinPurchase", () => {
  it("rejects amounts below the 50-coin minimum", () => {
    expect(() => quoteCoinPurchase(MIN_PURCHASE_COINS - 1)).toThrow(/50/)
  })

  it("rejects amounts above the 5000-coin maximum", () => {
    expect(() => quoteCoinPurchase(5001)).toThrow(/5000/)
  })

  it("matches backend preset pack totals", () => {
    expect(quoteCoinPurchase(50).amountRub).toBe(400)
    expect(quoteCoinPurchase(250).amountRub).toBe(1700)
    expect(quoteCoinPurchase(1000).amountRub).toBe(5500)
    expect(quoteCoinPurchase(5000).amountRub).toBe(19500)
  })

  it("applies volume tiers to custom amounts", () => {
    expect(quoteCoinPurchase(80).unitPriceRub).toBe(unitPriceRubForCoins(50))
    expect(quoteCoinPurchase(80).amountRub).toBe(640)
    expect(quoteCoinPurchase(1200).unitPriceRub).toBe(unitPriceRubForCoins(1000))
    expect(quoteCoinPurchase(1200).isHighValue).toBe(true)
  })

  it("labels high-value packs", () => {
    expect(packageBadge(250)).toBeNull()
    expect(packageBadge(1000)).toBe("Популярный")
    expect(packageBadge(5000)).toBe("Максимальная выгода")
  })
})
