/**
 * Schedule non-urgent Fabric / canvas work off the animation critical path.
 * Prefer requestIdleCallback so CSS/WebGL 3D animations keep the main thread.
 */
export function scheduleWhenIdle(
  task: () => void,
  options?: { timeoutMs?: number }
): () => void {
  const timeoutMs = options?.timeoutMs ?? 120
  let cancelled = false
  let idleId = 0
  let timeoutId = 0
  let rafId = 0

  const run = () => {
    if (cancelled) return
    task()
  }

  if (typeof window === "undefined") {
    task()
    return () => {
      cancelled = true
    }
  }

  const win = window as Window & {
    requestIdleCallback?: (
      callback: IdleRequestCallback,
      opts?: IdleRequestOptions
    ) => number
    cancelIdleCallback?: (handle: number) => void
  }

  if (typeof win.requestIdleCallback === "function") {
    idleId = win.requestIdleCallback(run, { timeout: timeoutMs })
  } else {
    // Yield at least one frame so compositor animations are not starved.
    rafId = win.requestAnimationFrame(() => {
      timeoutId = win.setTimeout(run, 0)
    })
  }

  return () => {
    cancelled = true
    if (idleId && typeof win.cancelIdleCallback === "function") {
      win.cancelIdleCallback(idleId)
    }
    if (rafId) win.cancelAnimationFrame(rafId)
    if (timeoutId) win.clearTimeout(timeoutId)
  }
}
