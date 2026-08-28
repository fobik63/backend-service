const STORAGE_KEY = "acm.pending-coin-purchase"
const TTL_MS = 1000 * 60 * 60 * 2

export type PendingCoinPurchase = {
  amountCoins: number
  amountRub: number
  createdAt: number
}

function isPending(value: unknown): value is PendingCoinPurchase {
  if (!value || typeof value !== "object") return false
  const row = value as PendingCoinPurchase
  return (
    Number.isInteger(row.amountCoins) &&
    row.amountCoins > 0 &&
    typeof row.amountRub === "number" &&
    typeof row.createdAt === "number"
  )
}

export function savePendingCoinPurchase(
  purchase: Omit<PendingCoinPurchase, "createdAt">
): void {
  if (typeof window === "undefined") return
  const payload: PendingCoinPurchase = {
    ...purchase,
    createdAt: Date.now(),
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
}

export function peekPendingCoinPurchase(): PendingCoinPurchase | null {
  if (typeof window === "undefined") return null
  const raw = window.localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!isPending(parsed)) return null
    if (Date.now() - parsed.createdAt > TTL_MS) {
      window.localStorage.removeItem(STORAGE_KEY)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

/** Read and clear the pending checkout so it is applied once. */
export function takePendingCoinPurchase(): PendingCoinPurchase | null {
  const pending = peekPendingCoinPurchase()
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(STORAGE_KEY)
  }
  return pending
}
