"use client"

import { Component, type ErrorInfo, type ReactNode } from "react"

import { recoverCanvasAfterRenderError } from "@/lib/editor/canvas-error-recovery"
import { useEditorStore } from "@/lib/store/editor-store"

const MAX_AUTO_RECOVERIES = 5

type CanvasErrorBoundaryProps = {
  children: ReactNode
  /** When this changes (e.g. page switch), recovery counter resets. */
  resetKey?: string | number
}

type CanvasErrorBoundaryState = {
  hasError: boolean
  recoverKey: number
  attempts: number
  propsResetKey: string | number | undefined
}

/**
 * Canvas-specific boundary: never kill the stage with a "Retry" banner.
 * On render failure → reset the offending layer + softbox to defaults,
 * remount children, and request Fabric `renderAll` / `requestRenderAll`.
 */
class CanvasErrorBoundary extends Component<
  CanvasErrorBoundaryProps,
  CanvasErrorBoundaryState
> {
  state: CanvasErrorBoundaryState = {
    hasError: false,
    recoverKey: 0,
    attempts: 0,
    propsResetKey: this.props.resetKey,
  }

  private recoverTimer: ReturnType<typeof setTimeout> | null = null

  static getDerivedStateFromError(): Partial<CanvasErrorBoundaryState> {
    return { hasError: true }
  }

  static getDerivedStateFromProps(
    props: CanvasErrorBoundaryProps,
    state: CanvasErrorBoundaryState
  ): Partial<CanvasErrorBoundaryState> | null {
    if (props.resetKey !== state.propsResetKey) {
      return {
        hasError: false,
        attempts: 0,
        propsResetKey: props.resetKey,
        recoverKey: state.recoverKey + 1,
      }
    }
    return null
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (process.env.NODE_ENV !== "production") {
      console.error("[canvas-error-boundary]", error, info.componentStack)
    }

    if (this.state.attempts >= MAX_AUTO_RECOVERIES) {
      // Avoid an infinite remount loop; page switch (resetKey) clears attempts.
      return
    }

    const selectedLayerId = useEditorStore.getState().selectedLayerId
    recoverCanvasAfterRenderError(selectedLayerId)

    if (this.recoverTimer) clearTimeout(this.recoverTimer)

    // Defer remount so Zustand defaults commit before children re-render.
    this.recoverTimer = setTimeout(() => {
      this.recoverTimer = null
      this.setState((prev) => ({
        hasError: false,
        recoverKey: prev.recoverKey + 1,
        attempts: prev.attempts + 1,
      }))
    }, 0)
  }

  componentWillUnmount() {
    if (this.recoverTimer) clearTimeout(this.recoverTimer)
  }

  render() {
    // Brief null while recovering — never the old "Ошибка элемента холста" plate.
    if (this.state.hasError) {
      return null
    }

    return (
      <div
        key={`canvas-recover-${this.state.recoverKey}`}
        className="contents"
      >
        {this.props.children}
      </div>
    )
  }
}

export { CanvasErrorBoundary }
export type { CanvasErrorBoundaryProps }
