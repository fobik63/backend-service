"use client"

import { Star } from "lucide-react"
import { useRef, type CSSProperties } from "react"
import { motion, useInView } from "framer-motion"

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

/** Pad a short row so one marquee half stays wider than typical viewports. */
function padMarqueeTrack(items: Testimonial[], minCards = 8): Testimonial[] {
  if (items.length === 0) return []
  const track = [...items]
  while (track.length < minCards) {
    track.push(...items)
  }
  return track
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
  /** Two equal halves → translate3d(±50%) loops without a visible seam. */
  const track = padMarqueeTrack(items)

  return (
    <div className="marquee-row marquee-fade-edges relative overflow-hidden py-1">
      <div
        className="marquee-track"
        data-direction={direction}
        style={
          {
            "--marquee-duration": `${durationSec}s`,
          } as CSSProperties
        }
      >
        <div className="marquee-track-half">
          {track.map((item, index) => (
            <TestimonialCard key={`${item.id}-a-${index}`} testimonial={item} />
          ))}
        </div>
        <div className="marquee-track-half" aria-hidden="true">
          {track.map((item, index) => (
            <TestimonialCard key={`${item.id}-b-${index}`} testimonial={item} />
          ))}
        </div>
      </div>
    </div>
  )
}

function TestimonialsSection() {
  const sectionRef = useRef<HTMLElement>(null)
  const inView = useInView(sectionRef, { once: true, amount: 0.15 })

  const mid = Math.ceil(TESTIMONIALS.length / 2)
  const topRow = TESTIMONIALS.slice(0, mid)
  const bottomRow = TESTIMONIALS.slice(mid)

  return (
    <section
      id="testimonials"
      ref={sectionRef}
      className="relative isolate flex flex-col gap-12 scroll-mt-24 py-16 md:py-24"
    >
      <div className="mx-auto w-full max-w-6xl px-5">
        <div className="section-glass rounded-3xl px-5 py-10 sm:px-8 sm:py-12">
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

      <div
        className="flex flex-col gap-4"
        aria-label="Лента отзывов"
      >
        <MarqueeRow items={topRow} direction="left" durationSec={35} />
        <MarqueeRow items={bottomRow} direction="right" durationSec={40} />
      </div>
    </section>
  )
}

export { TestimonialsSection }
