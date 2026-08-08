import type { CSSProperties } from "react"

import { cn } from "@/lib/utils"

type BackgroundGlowProps = {
  className?: string
}

/**
 * Left-edge emerald abstract semicircles / soft waves.
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
      {/* Soft blurred orbs — same tokens as the landing hero left edge */}
      <div className="absolute -left-24 top-[12%] size-[22rem] rounded-full bg-[#059669]/10 blur-[120px] sm:size-[28rem]" />
      <div className="absolute -left-16 top-[42%] size-[18rem] rounded-full bg-[#1b3e2b]/20 blur-[120px] sm:size-[24rem]" />
      <div className="absolute -left-20 bottom-[8%] size-[16rem] rounded-full bg-[#059669]/10 blur-[100px] sm:size-[22rem]" />

      {/* Abstract semicircle / wave silhouettes */}
      <svg
        className="absolute inset-y-0 left-0 h-full w-full text-[#059669]"
        viewBox="0 0 320 900"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden
        preserveAspectRatio="xMinYMid slice"
      >
        {/* Large outer semicircle wash */}
        <path
          d="M-40 80 C80 40 180 120 200 260 C220 400 120 480 -20 520 C40 360 20 200 -40 80Z"
          fill="currentColor"
          opacity="0.07"
        />
        {/* Mid wave arc */}
        <path
          d="M-30 280 C70 250 150 310 165 420 C180 530 90 600 -25 640 C30 500 15 360 -30 280Z"
          fill="#1b3e2b"
          opacity="0.14"
        />
        {/* Soft stacked semicircles */}
        <path
          d="M-10 520 C55 500 110 545 118 620 C126 695 70 745 -15 770 C20 680 10 580 -10 520Z"
          fill="currentColor"
          opacity="0.06"
        />
        {/* Thin wave strokes for depth */}
        <path
          d="M0 160 C90 130 160 190 170 280"
          stroke="currentColor"
          strokeWidth="1.25"
          opacity="0.12"
        />
        <path
          d="M0 360 C85 340 145 390 155 480"
          stroke="#1b3e2b"
          strokeWidth="1.25"
          opacity="0.18"
        />
        <path
          d="M0 580 C75 560 125 610 132 690"
          stroke="currentColor"
          strokeWidth="1"
          opacity="0.1"
        />
        {/* Edge-clipped circle fragments (read as half-disks) */}
        <circle cx="-20" cy="210" r="110" fill="currentColor" opacity="0.05" />
        <circle cx="-10" cy="470" r="90" fill="#1b3e2b" opacity="0.12" />
        <circle cx="-30" cy="720" r="100" fill="currentColor" opacity="0.045" />
      </svg>
    </div>
  )
}

/**
 * Reusable emerald botanical side glow used across Landing, Editor, Auth, etc.
 * Mount once (e.g. inside AppAtmosphere) for a site-wide frame.
 */
function BackgroundGlow({ className }: BackgroundGlowProps) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        className,
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
