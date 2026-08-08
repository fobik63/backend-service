import Link from "next/link"

import { cn } from "@/lib/utils"

function CardLogoIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden
    >
      <rect
        x="3.5"
        y="5"
        width="17"
        height="22"
        rx="2.5"
        stroke="currentColor"
        strokeWidth="1.6"
        className="text-copper/80"
      />
      <rect
        x="7.5"
        y="1"
        width="17"
        height="22"
        rx="2.5"
        fill="rgba(22,24,30,0.9)"
        stroke="currentColor"
        strokeWidth="1.6"
        className="text-emerald"
      />
      <path
        d="M11 8.5h10M11 12.5h7M11 16.5h8.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        className="text-copper/70"
      />
      <circle cx="21.5" cy="5.5" r="2" className="fill-emerald" />
    </svg>
  )
}

type BrandLogoProps = {
  href?: string
  className?: string
}

function BrandLogo({ href = "/projects", className }: BrandLogoProps) {
  return (
    <Link
      href={href}
      className={cn("group flex shrink-0 items-center gap-2.5", className)}
    >
      <CardLogoIcon className="size-7 transition-transform duration-300 group-hover:scale-105" />
      <span className="font-heading text-lg font-semibold tracking-tight text-sidebar-foreground">
        CARD AI
        <span
          aria-hidden
          className="ml-0.5 inline-block size-1.5 translate-y-[-0.35em] rounded-full bg-emerald shadow-[0_0_10px_rgba(16,185,129,0.7)]"
        />
      </span>
    </Link>
  )
}

export { BrandLogo, CardLogoIcon }
