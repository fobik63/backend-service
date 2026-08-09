"use client"

import { Component, type ErrorInfo, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type ErrorBoundaryProps = {
  children: ReactNode
  title?: string
  description?: string
  className?: string
  onReset?: () => void
}

type ErrorBoundaryState = {
  error: Error | null
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (process.env.NODE_ENV !== "production") {
      console.error("[error-boundary]", error, info.componentStack)
    }
  }

  private handleReset = () => {
    this.props.onReset?.()
    this.setState({ error: null })
  }

  render() {
    if (!this.state.error) {
      return this.props.children
    }

    return (
      <div
        className={cn(
          "flex min-h-40 flex-col items-center justify-center gap-3 rounded-xl border border-white/10 bg-loft-surface/60 px-4 py-6 text-center",
          this.props.className
        )}
        role="alert"
      >
        <p className="font-heading text-sm font-semibold tracking-tight">
          {this.props.title ?? "Секция временно недоступна"}
        </p>
        <p className="max-w-sm text-xs text-muted-foreground">
          {this.props.description ??
            this.state.error.message ??
            "Произошла ошибка отрисовки. Попробуйте снова."}
        </p>
        <Button type="button" size="sm" variant="outline" onClick={this.handleReset}>
          Повторить
        </Button>
      </div>
    )
  }
}

export { ErrorBoundary }
export type { ErrorBoundaryProps }
