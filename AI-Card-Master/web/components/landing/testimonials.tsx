"use client"

import { Star } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import {
  motion,
  useAnimationFrame,
  useInView,
  useMotionValue,
  useReducedMotion,
} from "framer-motion"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { GlassCard } from "@/components/ui/glass-card"
import { SectionHeader } from "@/components/ui/section-header"
import {
  TESTIMONIALS,
  type Testimonial,
  type TestimonialMarketplace,
} from "@/lib/constants/testimonials"
import { cn } from "@/lib/utils"

function MarketplaceLogo({
  marketplace,
  className,
}: {
  marketplace: TestimonialMarketplace
  className?: string
}) {
  if (marketplace === "ozon") {
    return (
      <span
        className={cn(
          "inline-flex h-5 items-center rounded px-1.5 font-heading text-[10px] font-bold tracking-tight text-white",
          "bg-[#005bff]",
          className
        )}
        title="Ozon"
        aria-label="Ozon"
      >
        ozon
      </span>
    )
  }

  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded px-1.5 font-heading text-[10px] font-bold tracking-tight text-white",
        "bg-[#cb11ab]",
        className
      )}
      title="Wildberries"
      aria-label="Wildberries"
    >
      WB
    </span>
  )
}

function Stars({ rating }: { rating: number }) {
  const clamped = Math.min(5, Math.max(0, Math.round(rating)))

  return (
    <div className="flex items-center gap-0.5" aria-label={`Оценка ${clamped} из 5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <Star
          key={i}
          className={cn(
            "size-3.5",
            i < clamped ? "fill-amber text-amber" : "fill-transparent text-white/20"
          )}
          strokeWidth={1.5}
          aria-hidden
        />
      ))}
    </div>
  )
}

function TestimonialCard({ testimonial }: { testimonial: Testimonial }) {
  return (
    <GlassCard
      className="w-[min(100vw-2.5rem,320px)] shrink-0 copper-border sm:w-[340px]"
      padding="md"
      hoverLift={false}
    >
      <div className="flex items-start gap-3">
        <Avatar size="lg" className="border border-white/10">
          {testimonial.avatarUrl ? (
            <AvatarImage src={testimonial.avatarUrl} alt={testimonial.name} />
          ) : null}
          <AvatarFallback className="bg-sage/40 font-heading text-xs font-semibold text-emerald">
            {testimonial.avatarInitials}
          </AvatarFallback>
        </Avatar>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate font-heading text-sm font-semibold text-foreground">
                {testimonial.name}
              </p>
              <p className="mt-0.5 truncate text-xs text-text-muted">
                {testimonial.niche}
              </p>
            </div>
            <MarketplaceLogo marketplace={testimonial.marketplace} />
          </div>
          <div className="mt-2">
            <Stars rating={testimonial.rating} />
          </div>
        </div>
      </div>

      <p className="mt-4 text-sm leading-relaxed text-text-muted">
        «{testimonial.text}»
      </p>
    </GlassCard>
  )
}

function MarqueeRow({
  items,
  direction,
  durationSec,
}: {
  items: Testimonial[]
  direction: "left" | "right"
  durationSec: number
}) {
  const loop = [...items, ...items]
  const trackRef = useRef<HTMLDivElement>(null)
  const x = useMotionValue(0)
  const [paused, setPaused] = useState(false)
  const reduceMotion = useReducedMotion()
  const halfWidthRef = useRef(0)

  useEffect(() => {
    const measure = () => {
      const el = trackRef.current
      if (!el) return
      halfWidthRef.current = el.scrollWidth / 2
      if (direction === "right" && x.get() === 0) {
        x.set(-halfWidthRef.current)
      }
    }
    measure()
    window.addEventListener("resize", measure)
    return () => window.removeEventListener("resize", measure)
  }, [direction, items, x])

  useAnimationFrame((_, delta) => {
    if (paused || reduceMotion) return
    const half = halfWidthRef.current
    if (half <= 0) return

    const pxPerMs = half / (durationSec * 1000)
    const current = x.get()

    if (direction === "left") {
      let next = current - pxPerMs * delta
      if (next <= -half) next += half
      x.set(next)
    } else {
      let next = current + pxPerMs * delta
      if (next >= 0) next -= half
      x.set(next)
    }
  })

  return (
    <div
      className="relative overflow-hidden"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={() => setPaused(false)}
    >
      <div
        className="pointer-events-none absolute inset-y-0 left-0 z-10 w-16 bg-gradient-to-r from-[#0f1115] via-[#0f1115]/85 to-transparent sm:w-28"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute inset-y-0 right-0 z-10 w-16 bg-gradient-to-l from-[#0f1115] via-[#0f1115]/85 to-transparent sm:w-28"
        aria-hidden
      />

      <motion.div
        ref={trackRef}
        className="flex w-max gap-4 py-1 will-change-transform"
        style={{ x }}
      >
        {loop.map((item, index) => (
          <TestimonialCard key={`${item.id}-${index}`} testimonial={item} />
        ))}
      </motion.div>
    </div>
  )
}

function TestimonialsSection() {
  const sectionRef = useRef<HTMLElement>(null)
  const inView = useInView(sectionRef, { once: true, amount: 0.15 })

  const topRow = TESTIMONIALS
  const bottomRow = [...TESTIMONIALS].reverse()

  return (
    <section
      id="testimonials"
      ref={sectionRef}
      className="relative isolate scroll-mt-24 bg-gradient-to-b from-[#0f1115] via-[#141b17] to-[#0f1115] py-20 sm:py-28"
    >
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden>
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_50%_35%_at_50%_100%,rgba(16,185,129,0.07),transparent_55%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_35%_30%_at_90%_20%,rgba(27,62,43,0.3),transparent_50%)]" />
        <div className="absolute inset-0 opacity-[0.035] noise-texture" />
      </div>

      <div className="mx-auto max-w-6xl px-5">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 24 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        >
          <SectionHeader
            align="center"
            title="Отзывы продавцов"
            subtitle="Селлеры Ozon и Wildberries уже собирают карточки в CARD AI — без студии и долгой ретуши"
            className="mb-12 sm:mb-14"
          />
        </motion.div>
      </div>

      <motion.div
        className="flex flex-col gap-4"
        initial={{ opacity: 0 }}
        animate={inView ? { opacity: 1 } : { opacity: 0 }}
        transition={{ delay: 0.15, duration: 0.55 }}
        aria-label="Лента отзывов"
      >
        <MarqueeRow items={topRow} direction="left" durationSec={42} />
        <MarqueeRow items={bottomRow} direction="right" durationSec={48} />
      </motion.div>
    </section>
  )
}

export { TestimonialsSection }
