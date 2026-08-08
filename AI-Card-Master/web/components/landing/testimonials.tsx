"use client"

import { Star } from "lucide-react"
import { useRef, type CSSProperties } from "react"
import { motion, useInView, useReducedMotion } from "framer-motion"

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
      className="w-[min(100vw-2.5rem,320px)] shrink-0 sm:w-[340px]"
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
  const reduceMotion = useReducedMotion()
  /** Two identical halves → translate ±50% loops without a seam */
  const loop = reduceMotion ? items : [...items, ...items]

  return (
    <div className="marquee-row marquee-fade-edges relative overflow-hidden py-1">
      <div
        className={cn(
          "flex w-max gap-4 will-change-transform",
          !reduceMotion &&
            (direction === "left"
              ? "animate-marquee-left"
              : "animate-marquee-right")
        )}
        style={
          {
            "--marquee-duration": `${durationSec}s`,
          } as CSSProperties
        }
      >
        {loop.map((item, index) => (
          <TestimonialCard key={`${item.id}-${index}`} testimonial={item} />
        ))}
      </div>
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
      className="relative isolate scroll-mt-24 py-20 sm:py-28"
    >
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden>
        <div className="absolute -right-32 top-1/4 size-72 rounded-full bg-[#1b3e2b]/20 blur-[120px]" />
        <div className="absolute -left-28 bottom-1/3 size-64 rounded-full bg-[#059669]/10 blur-[120px]" />
      </div>

      <div className="mx-auto max-w-6xl px-5">
        <div className="section-glass mb-10 rounded-3xl px-5 py-10 sm:mb-12 sm:px-8 sm:py-12">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 24 }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          >
            <SectionHeader
              align="center"
              title="Отзывы продавцов"
              subtitle="Селлеры Ozon и Wildberries уже собирают карточки в CARD AI — без студии и долгой ретуши"
            />
          </motion.div>
        </div>
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
