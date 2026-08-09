"use client"

import { useEffect, useState } from "react"

/**
 * Returns `value` only after it has been stable for `delayMs`.
 * Use to keep high-frequency UI (sliders) off the hot path for heavy work.
 */
export function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(id)
  }, [value, delayMs])

  return debounced
}
