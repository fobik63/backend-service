/**
 * Inter-request throttle for marketplace scrapes (anti-ban jitter).
 *
 * Configure via env (milliseconds):
 * - PARSER_REQUEST_DELAY_MS_MIN (default 400)
 * - PARSER_REQUEST_DELAY_MS_MAX (default 1200)
 */

function readDelayMs(name: string, fallback: number): number {
  const raw = process.env[name]
  if (raw == null || raw.trim() === "") return fallback
  const parsed = Number(raw)
  if (!Number.isFinite(parsed) || parsed < 0) return fallback
  return parsed
}

export type ParserThrottleOptions = {
  /** Override min delay (ms). */
  minMs?: number
  /** Override max delay (ms). */
  maxMs?: number
  /** Disable sleeps (unit tests). */
  disabled?: boolean
}

export class ParserRequestThrottle {
  private readonly minMs: number
  private readonly maxMs: number
  private readonly disabled: boolean
  private lastRequestAt = 0

  constructor(options?: ParserThrottleOptions) {
    const envMin = readDelayMs("PARSER_REQUEST_DELAY_MS_MIN", 400)
    const envMax = readDelayMs("PARSER_REQUEST_DELAY_MS_MAX", 1200)
    const minMs = options?.minMs ?? envMin
    const maxMs = options?.maxMs ?? envMax
    this.minMs = Math.max(0, Math.min(minMs, maxMs))
    this.maxMs = Math.max(this.minMs, maxMs)
    this.disabled = Boolean(options?.disabled) || this.maxMs <= 0
  }

  /** Sleep a jittered gap since the previous request (if any). */
  async waitBeforeRequest(): Promise<void> {
    if (this.disabled) return

    const now = Date.now()
    const sinceLast = now - this.lastRequestAt
    const targetGap =
      this.minMs + Math.random() * (this.maxMs - this.minMs)

    if (this.lastRequestAt > 0 && sinceLast < targetGap) {
      await sleep(targetGap - sinceLast)
    } else if (this.lastRequestAt === 0 && this.minMs > 0) {
      // Small opening jitter so the first hit is not perfectly timed.
      await sleep(Math.random() * Math.min(250, this.minMs))
    }

    this.lastRequestAt = Date.now()
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
