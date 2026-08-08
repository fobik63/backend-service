"use client"

import { useEffect, useState, type ComponentProps } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type ImageWithSkeletonProps = Omit<
  ComponentProps<"img">,
  "onLoad" | "onError"
> & {
  /** Extra class for the pulsing skeleton behind the image. */
  skeletonClassName?: string
  /** Fires after a successful load (skeleton dismissed). */
  onLoad?: () => void
  /** Called when the image fails to load (network / 404). */
  onLoadError?: () => void
}

/**
 * Renders a skeleton until the image fires `load`.
 * On error, keeps a muted skeleton and optionally notifies the parent.
 */
function ImageWithSkeleton({
  className,
  skeletonClassName,
  alt,
  src,
  onLoad,
  onLoadError,
  ...props
}: ImageWithSkeletonProps) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")

  useEffect(() => {
    setStatus("loading")
  }, [src])

  return (
    <div className={cn("relative overflow-hidden", className)}>
      {status !== "ready" ? (
        <Skeleton
          className={cn(
            "absolute inset-0 size-full rounded-[inherit]",
            skeletonClassName
          )}
          aria-hidden
        />
      ) : null}
      {status === "error" ? (
        <div
          className="absolute inset-0 flex items-center justify-center bg-white/[0.04] text-center text-[11px] text-muted-foreground"
          role="img"
          aria-label={alt || "Не удалось загрузить изображение"}
        >
          Не удалось загрузить
        </div>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- dynamic blob/CDN URLs
        <img
          {...props}
          src={src}
          alt={alt}
          className={cn(
            "size-full object-cover transition-opacity duration-300",
            status === "ready" ? "opacity-100" : "opacity-0"
          )}
          onLoad={() => {
            setStatus("ready")
            onLoad?.()
          }}
          onError={() => {
            setStatus("error")
            onLoadError?.()
          }}
        />
      )}
    </div>
  )
}

export { ImageWithSkeleton }
export type { ImageWithSkeletonProps }
