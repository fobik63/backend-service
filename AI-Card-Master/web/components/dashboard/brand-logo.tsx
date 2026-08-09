import Link from "next/link"
import type { MouseEventHandler } from "react"

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
        className="text-white/35"
      />
      <rect
        x="7.5"
        y="1"
        width="17"
        height="22"
        rx="2.5"
        fill="#121214"
        stroke="currentColor"
        strokeWidth="1.6"
        className="text-foreground"
      />
      <path
        d="M11 8.5h10M11 12.5h7M11 16.5h8.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        className="text-white/45"
      />
      <circle cx="21.5" cy="5.5" r="2" className="fill-foreground" />
    </svg>
  )
}

type BrandLogoProps = {
  href?: string
  className?: string
  onClick?: MouseEventHandler<HTMLAnchorElement>
}

function BrandLogo({ href = "/projects", className, onClick }: BrandLogoProps) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn("group flex shrink-0 items-center gap-2.5", className)}
      aria-label="CARD AI"
    >
      <CardLogoIcon className="size-7 transition-opacity duration-200 group-hover:opacity-80" />
      <span className="font-heading text-lg font-semibold tracking-tight text-sidebar-foreground">
        CARD AI
        <span
          aria-hidden
          className="ml-1 inline-block size-1.5 translate-y-[-0.35em] rounded-full bg-foreground"
        />
      </span>
    </Link>
  )
}

export { BrandLogo, CardLogoIcon }
