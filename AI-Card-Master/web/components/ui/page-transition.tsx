"use client"

import { motion } from "framer-motion"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

const PAGE_TRANSITION = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  transition: {
    duration: 0.38,
    ease: [0.22, 1, 0.36, 1] as const,
  },
}

type PageTransitionProps = {
  children: ReactNode
  className?: string
}

/** Fade-in + slide-up wrapper for App Router `template.tsx` remounts. */
function PageTransition({ children, className }: PageTransitionProps) {
  return (
    <motion.div
      className={cn("h-full w-full", className)}
      initial={PAGE_TRANSITION.initial}
      animate={PAGE_TRANSITION.animate}
      transition={PAGE_TRANSITION.transition}
    >
      {children}
    </motion.div>
  )
}

export { PageTransition, PAGE_TRANSITION }
export type { PageTransitionProps }
