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

  if (typeof window !== "undefined" && "requestIdleCallback" in window) {
    idleId = window.requestIdleCallback(run, { timeout: timeoutMs })
  } else if (typeof window !== "undefined") {
    // Yield at least one frame so compositor animations are not starved.
    rafId = window.requestAnimationFrame(() => {
      timeoutId = window.setTimeout(run, 0)
    })
  } else {
    task()
  }

  return () => {
    cancelled = true
    if (
      idleId &&
      typeof window !== "undefined" &&
      "cancelIdleCallback" in window
    ) {
      window.cancelIdleCallback(idleId)
    }
    if (rafId) window.cancelAnimationFrame(rafId)
    if (timeoutId) window.clearTimeout(timeoutId)
  }
}
