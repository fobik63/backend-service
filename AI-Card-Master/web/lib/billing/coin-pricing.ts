/** Client-side mirror of `backend/app/domain/coin_pricing.py` for live totals. */

export const MIN_PURCHASE_COINS = 50
export const MAX_PURCHASE_COINS = 5000
export const COIN_PACKAGES = [50, 250, 1000, 5000] as const

export type CoinPackageSize = (typeof COIN_PACKAGES)[number]

/** Highest matching threshold wins. RUB per coin. */
const UNIT_PRICE_TIERS: ReadonlyArray<readonly [number, number]> = [
  [5000, 3.9],
  [1000, 5.5],
  [250, 6.8],
  [50, 8],
]

export type CoinPurchaseQuote = {
  amountCoins: number
  unitPriceRub: number
  amountRub: number
  isPresetPackage: boolean
  isHighValue: boolean
}

export function unitPriceRubForCoins(amountCoins: number): number {
  if (amountCoins < MIN_PURCHASE_COINS) {
    throw new Error(`Minimum purchase is ${MIN_PURCHASE_COINS} AI-coins.`)
  }
  if (amountCoins > MAX_PURCHASE_COINS) {
    throw new Error(`Maximum purchase is ${MAX_PURCHASE_COINS} AI-coins.`)
  }
  for (const [threshold, price] of UNIT_PRICE_TIERS) {
    if (amountCoins >= threshold) return price
  }
  throw new Error(`No price tier for ${amountCoins} coins.`)
}

export function quoteCoinPurchase(amountCoins: number): CoinPurchaseQuote {
  const unitPriceRub = unitPriceRubForCoins(amountCoins)
  const amountRub = Math.round(unitPriceRub * amountCoins * 100) / 100
  return {
    amountCoins,
    unitPriceRub,
    amountRub,
    isPresetPackage: (COIN_PACKAGES as readonly number[]).includes(amountCoins),
    isHighValue: amountCoins >= 1000,
  }
}

export function formatRub(value: number): string {
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatCoins(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value)
}

export function packageBadge(amountCoins: number): string | null {
  if (amountCoins >= 5000) return "Максимальная выгода"
  if (amountCoins >= 1000) return "Популярный"
  return null
}
