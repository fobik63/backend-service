import type { CSSProperties } from "react"

import { cn } from "@/lib/utils"

type BackgroundGlowProps = {
  className?: string
}

/**
 * Soft ambient orbs along the viewport edges.
 * Mirrored on the right via scaleX(-1) so both sides frame the content.
 */
function GlowSide({
  className,
  style,
}: {
  className?: string
  style?: CSSProperties
}) {
  return (
    <div
      className={cn("absolute inset-y-0 w-[min(48vw,32rem)]", className)}
      style={style}
    >
      <div className="absolute -left-24 top-[10%] size-[22rem] rounded-full bg-zinc-400/[0.07] blur-[120px] sm:size-[28rem]" />
      <div className="absolute -left-16 top-[40%] size-[18rem] rounded-full bg-zinc-500/[0.08] blur-[120px] sm:size-[24rem]" />
      <div className="absolute -left-20 bottom-[6%] size-[16rem] rounded-full bg-stone-400/[0.06] blur-[100px] sm:size-[22rem]" />
    </div>
  )
}

/**
 * Site-wide subtle ambient glow for Landing, Editor, Auth, etc.
 * Mount once inside AppAtmosphere.
 */
function BackgroundGlow({ className }: BackgroundGlowProps) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className
      )}
      aria-hidden
    >
      <div className="absolute inset-0 botanical-glow" />

      <GlowSide className="left-0" />
      <GlowSide
        className="right-0 origin-center"
        style={{ transform: "scaleX(-1)" }}
      />
    </div>
  )
}

export { BackgroundGlow }
