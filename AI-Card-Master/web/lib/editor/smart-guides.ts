/**
 * Smart Guides / Snapping — pure geometry for Fabric drag alignment.
 * Snaps moving objects to canvas and peer edges/centers (esp. product).
 */

export const SMART_GUIDE_THRESHOLD_PX = 8

export type AxisAlignedBounds = {
  left: number
  top: number
  right: number
  bottom: number
  centerX: number
  centerY: number
}

export type SmartGuideLine = {
  orientation: "horizontal" | "vertical"
  /** Canvas coordinate: x for vertical, y for horizontal. */
  position: number
}

export type SnapMoveResult = {
  dx: number
  dy: number
  guides: SmartGuideLine[]
}

export function boundsFromRect(rect: {
  left: number
  top: number
  width: number
  height: number
}): AxisAlignedBounds {
  const left = rect.left
  const top = rect.top
  const right = rect.left + rect.width
  const bottom = rect.top + rect.height
  return {
    left,
    top,
    right,
    bottom,
    centerX: (left + right) / 2,
    centerY: (top + bottom) / 2,
  }
}

export function canvasBounds(width: number, height: number): AxisAlignedBounds {
  return boundsFromRect({ left: 0, top: 0, width, height })
}

type AxisCandidate = {
  movingValue: number
  targetValue: number
  /** Lower is better: 0 = like-to-like (L-L / C-C / R-R), 1 = cross. */
  priority: number
}

function bestSnapDelta(
  candidates: AxisCandidate[],
  threshold: number
): { delta: number; snappedAt: number | null } {
  let best: {
    abs: number
    priority: number
    delta: number
    snappedAt: number
  } | null = null
  for (const c of candidates) {
    const delta = c.targetValue - c.movingValue
    const abs = Math.abs(delta)
    if (abs > threshold) continue
    if (
      !best ||
      abs < best.abs ||
      (abs === best.abs && c.priority < best.priority)
    ) {
      best = { abs, priority: c.priority, delta, snappedAt: c.targetValue }
    }
  }
  return best
    ? { delta: best.delta, snappedAt: best.snappedAt }
    : { delta: 0, snappedAt: null }
}

function verticalCandidates(
  moving: AxisAlignedBounds,
  target: AxisAlignedBounds
): AxisCandidate[] {
  const pairs: Array<[number, number, number]> = [
    [moving.left, target.left, 0],
    [moving.centerX, target.centerX, 0],
    [moving.right, target.right, 0],
    [moving.left, target.centerX, 1],
    [moving.left, target.right, 1],
    [moving.centerX, target.left, 1],
    [moving.centerX, target.right, 1],
    [moving.right, target.left, 1],
    [moving.right, target.centerX, 1],
  ]
  return pairs.map(([movingValue, targetValue, priority]) => ({
    movingValue,
    targetValue,
    priority,
  }))
}

function horizontalCandidates(
  moving: AxisAlignedBounds,
  target: AxisAlignedBounds
): AxisCandidate[] {
  const pairs: Array<[number, number, number]> = [
    [moving.top, target.top, 0],
    [moving.centerY, target.centerY, 0],
    [moving.bottom, target.bottom, 0],
    [moving.top, target.centerY, 1],
    [moving.top, target.bottom, 1],
    [moving.centerY, target.top, 1],
    [moving.centerY, target.bottom, 1],
    [moving.bottom, target.top, 1],
    [moving.bottom, target.centerY, 1],
  ]
  return pairs.map(([movingValue, targetValue, priority]) => ({
    movingValue,
    targetValue,
    priority,
  }))
}

/**
 * Compute snap deltas + guide lines for a moving AABB against targets.
 * Prefer product / peer targets first when distances tie (stable order).
 */
export function snapMoveToTargets(
  moving: AxisAlignedBounds,
  targets: AxisAlignedBounds[],
  threshold: number = SMART_GUIDE_THRESHOLD_PX
): SnapMoveResult {
  const vCandidates: AxisCandidate[] = []
  const hCandidates: AxisCandidate[] = []
  for (const target of targets) {
    vCandidates.push(...verticalCandidates(moving, target))
    hCandidates.push(...horizontalCandidates(moving, target))
  }

  const v = bestSnapDelta(vCandidates, threshold)
  const h = bestSnapDelta(hCandidates, threshold)

  const snapped: AxisAlignedBounds = {
    left: moving.left + v.delta,
    top: moving.top + h.delta,
    right: moving.right + v.delta,
    bottom: moving.bottom + h.delta,
    centerX: moving.centerX + v.delta,
    centerY: moving.centerY + h.delta,
  }

  const guides: SmartGuideLine[] = []
  const eps = 0.75

  if (v.snappedAt != null) {
    const edges = [snapped.left, snapped.centerX, snapped.right]
    if (edges.some((e) => Math.abs(e - v.snappedAt!) < eps)) {
      guides.push({ orientation: "vertical", position: v.snappedAt })
    }
  }
  if (h.snappedAt != null) {
    const edges = [snapped.top, snapped.centerY, snapped.bottom]
    if (edges.some((e) => Math.abs(e - h.snappedAt!) < eps)) {
      guides.push({ orientation: "horizontal", position: h.snappedAt })
    }
  }

  // Also show matching peer edges that align after snap (multi-guide feel)
  for (const target of targets) {
    for (const t of [target.left, target.centerX, target.right]) {
      for (const m of [snapped.left, snapped.centerX, snapped.right]) {
        if (Math.abs(m - t) < eps) {
          if (
            !guides.some(
              (g) => g.orientation === "vertical" && Math.abs(g.position - t) < eps
            )
          ) {
            guides.push({ orientation: "vertical", position: t })
          }
        }
      }
    }
    for (const t of [target.top, target.centerY, target.bottom]) {
      for (const m of [snapped.top, snapped.centerY, snapped.bottom]) {
        if (Math.abs(m - t) < eps) {
          if (
            !guides.some(
              (g) =>
                g.orientation === "horizontal" && Math.abs(g.position - t) < eps
            )
          ) {
            guides.push({ orientation: "horizontal", position: t })
          }
        }
      }
    }
  }

  return { dx: v.delta, dy: h.delta, guides }
}
