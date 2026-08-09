"use client"

import { cva, type VariantProps } from "class-variance-authority"
import { motion, type HTMLMotionProps } from "framer-motion"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

const glassButtonVariants = cva(
  [
    "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg",
    "bg-primary text-primary-foreground",
    "font-medium whitespace-nowrap",
    "border border-transparent",
    "transition-[background-color,border-color,opacity] duration-200",
    "outline-none select-none",
    "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-loft",
    "disabled:pointer-events-none disabled:opacity-50",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ].join(" "),
  {
    variants: {
      size: {
        default: "h-10 px-5 text-sm",
        sm: "h-8 gap-1.5 px-3.5 text-xs [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-12 gap-2.5 px-7 text-base [&_svg:not([class*='size-'])]:size-5",
        icon: "size-10",
      },
    },
    defaultVariants: {
      size: "default",
    },
  }
)

type GlassButtonProps = Omit<HTMLMotionProps<"button">, "children"> &
  VariantProps<typeof glassButtonVariants> & {
    children?: ReactNode
    icon?: LucideIcon
    iconPosition?: "start" | "end"
  }

function GlassButton({
  className,
  size,
  children,
  icon: Icon,
  iconPosition = "start",
  disabled,
  type = "button",
  ...props
}: GlassButtonProps) {
  return (
    <motion.button
      type={type}
      disabled={disabled}
      whileHover={disabled ? undefined : { opacity: 0.92 }}
      whileTap={disabled ? undefined : { scale: 0.98 }}
      transition={{ type: "spring", stiffness: 420, damping: 28 }}
      className={cn(glassButtonVariants({ size }), className)}
      {...props}
    >
      {Icon && iconPosition === "start" ? <Icon aria-hidden /> : null}
      {children}
      {Icon && iconPosition === "end" ? <Icon aria-hidden /> : null}
    </motion.button>
  )
}

export { GlassButton, glassButtonVariants }
export type { GlassButtonProps }
