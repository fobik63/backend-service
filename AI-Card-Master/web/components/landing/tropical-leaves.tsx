import { cn } from "@/lib/utils"

type TropicalLeavesProps = {
  className?: string
  /** Extra opacity multiplier on top of base 0.03 */
  opacity?: number
}

/**
 * Barely-visible tropical leaf silhouettes for Loft + Botanical atmosphere.
 * Default opacity ~0.03 so they read as texture, not illustration.
 */
function TropicalLeaves({ className, opacity = 0.03 }: TropicalLeavesProps) {
  return (
    <svg
      className={cn("pointer-events-none absolute inset-0 h-full w-full", className)}
      viewBox="0 0 1200 800"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      style={{ opacity }}
      preserveAspectRatio="xMidYMid slice"
    >
      {/* Left monstera-like cluster */}
      <g fill="currentColor" className="text-emerald">
        <path d="M80 120c40 20 70 70 55 130-18 72-78 110-130 95 25-35 35-80 20-120 28-20 45-55 55-105z" />
        <path d="M40 280c55 15 95 65 85 125-12 68-72 105-125 90 30-40 38-85 18-125 22-18 35-50 22-90z" />
        <path d="M120 420c48 28 78 85 58 145-22 68-88 98-140 78 32-38 42-90 20-135 28-12 48-48 62-88z" />
        <path d="M-10 540c50 10 88 55 80 110-10 60-60 95-110 82 25-35 32-75 12-110 18-15 28-42 18-82z" />
      </g>

      {/* Right palm / bird-of-paradise silhouettes */}
      <g fill="currentColor" className="text-[#1b3e2b]">
        <path d="M1120 80c-55 35-85 100-60 165 28 70 95 105 155 85-20-45-15-95 15-135-35-20-70-55-110-115z" />
        <path d="M1180 260c-60 20-105 75-90 140 18 72 85 110 145 90-25-42-30-95-5-140-25-15-45-50-50-90z" />
        <path d="M1080 400c-50 40-70 110-35 170 38 65 110 85 165 50-35-35-45-95-20-145-40-5-75-35-110-75z" />
        <path d="M1220 560c-55 15-95 70-80 130 15 65 75 100 135 80-28-38-32-85-8-125-22-12-40-45-47-85z" />
      </g>

      {/* Soft mid-field fronds */}
      <g fill="currentColor" className="text-sage">
        <path d="M200 700c80-40 160-30 200 20-55 35-130 45-200 25 15-20 20-35 0-45z" />
        <path d="M980 720c-70-35-150-25-190 25 50 30 120 40 190 20-10-15-15-30 0-45z" />
      </g>
    </svg>
  )
}

export { TropicalLeaves }
