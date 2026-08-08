"use client"

import { Play, Sparkles } from "lucide-react"
import Image from "next/image"
import { useRouter } from "next/navigation"
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react"
import { motion } from "framer-motion"

import { GlassButton } from "@/components/ui/glass-button"
import { cn } from "@/lib/utils"

const fadeUp = {
  hidden: { opacity: 0, y: 28 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      delay: 0.12 + i * 0.1,
      duration: 0.55,
      ease: [0.22, 1, 0.36, 1] as const,
    },
  }),
}

function BeforeAfterSlider() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState(52)
  const dragging = useRef(false)
  const interacted = useRef(false)

  const updateFromClientX = useCallback((clientX: number) => {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const next = ((clientX - rect.left) / rect.width) * 100
    setPosition(Math.min(96, Math.max(4, next)))
  }, [])

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    interacted.current = true
    dragging.current = true
    e.currentTarget.setPointerCapture(e.pointerId)
    updateFromClientX(e.clientX)
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    updateFromClientX(e.clientX)
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = false
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }

  useEffect(() => {
    const id = window.setTimeout(() => {
      if (!interacted.current) setPosition(48)
    }, 900)
    const id2 = window.setTimeout(() => {
      if (!interacted.current) setPosition(58)
    }, 1600)
    return () => {
      window.clearTimeout(id)
      window.clearTimeout(id2)
    }
  }, [])

  return (
    <div
      ref={containerRef}
      className={cn(
        "relative aspect-[4/5] w-full max-w-md overflow-hidden rounded-2xl",
        "border border-white/10 bg-loft-surface",
        "shadow-[0_24px_80px_rgba(0,0,0,0.45)]",
        "select-none touch-none cursor-ew-resize"
      )}
      role="img"
      aria-label="Сравнение: сырое фото товара и готовая карточка Ozon"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {/* After — готовая карточка */}
      <div className="absolute inset-0">
        <Image
          src="/landing/after-card.png"
          alt="Готовая карточка Ozon с инфографикой"
          fill
          priority
          sizes="(max-width: 768px) 100vw, 28rem"
          className="object-cover object-center"
        />
        <span className="absolute right-3 top-3 rounded-md bg-emerald/90 px-2 py-1 font-heading text-[11px] font-semibold tracking-wide text-loft">
          После
        </span>
      </div>

      {/* Before — сырое фото, клип по ползунку */}
      <div
        className="absolute inset-0 overflow-hidden"
        style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }}
      >
        <Image
          src="/landing/before-product.png"
          alt="Сырое фото товара до обработки"
          fill
          priority
          sizes="(max-width: 768px) 100vw, 28rem"
          className="object-cover object-center"
        />
        <div
          className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,rgba(15,17,21,0.35)_100%)]"
          aria-hidden
        />
        <span className="absolute left-3 top-3 rounded-md bg-loft/80 px-2 py-1 font-heading text-[11px] font-semibold tracking-wide text-foreground backdrop-blur-sm">
          До
        </span>
      </div>

      {/* Divider + handle */}
      <div
        className="absolute inset-y-0 z-10 w-px bg-white/80"
        style={{ left: `${position}%` }}
        aria-hidden
      >
        <div className="absolute left-1/2 top-1/2 flex size-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-loft/85 shadow-[0_0_24px_rgba(16,185,129,0.35)] backdrop-blur-md">
          <span className="flex gap-0.5 text-emerald">
            <span className="block h-3.5 w-0.5 rounded-full bg-current opacity-70" />
            <span className="block h-3.5 w-0.5 rounded-full bg-current" />
            <span className="block h-3.5 w-0.5 rounded-full bg-current opacity-70" />
          </span>
        </div>
      </div>

      <label className="sr-only" htmlFor="hero-compare-slider">
        Ползунок сравнения до и после
      </label>
      <input
        id="hero-compare-slider"
        type="range"
        min={4}
        max={96}
        value={position}
        onChange={(e) => setPosition(Number(e.target.value))}
        className="absolute inset-x-0 bottom-3 z-20 mx-auto h-2 w-[min(80%,16rem)] cursor-pointer appearance-none rounded-full bg-white/15 accent-emerald"
        onPointerDown={() => {
          interacted.current = true
        }}
      />
    </div>
  )
}

function HeroSection() {
  const router = useRouter()

  return (
    <section className="relative isolate min-h-[100svh] overflow-hidden pt-28 pb-16 sm:pt-32">
      {/* Atmosphere */}
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden>
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_60%_at_50%_-10%,rgba(16,185,129,0.14),transparent_55%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_50%_40%_at_90%_40%,rgba(46,74,56,0.35),transparent_60%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_40%_30%_at_10%_70%,rgba(194,166,140,0.08),transparent_55%)]" />
        <div
          className="absolute inset-0 opacity-[0.035]"
          style={{
            backgroundImage:
              "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
          }}
        />
      </div>

      <div className="mx-auto grid max-w-6xl items-center gap-12 px-5 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
        <div className="flex flex-col items-start">
          <motion.p
            custom={0}
            variants={fadeUp}
            initial="hidden"
            animate="show"
            className="mb-4 font-heading text-sm font-medium tracking-[0.18em] text-emerald uppercase"
          >
            CARD AI
          </motion.p>

          <motion.h1
            custom={1}
            variants={fadeUp}
            initial="hidden"
            animate="show"
            className="max-w-xl font-heading text-3xl font-semibold leading-[1.12] tracking-tight text-foreground sm:text-4xl lg:text-[2.75rem]"
          >
            Создавай продающие карточки для Ozon и WB за 10 секунд с помощью AI
          </motion.h1>

          <motion.p
            custom={2}
            variants={fadeUp}
            initial="hidden"
            animate="show"
            className="mt-5 max-w-lg text-base leading-relaxed text-text-muted sm:text-lg"
          >
            Автоматическая вырезка фона, студийный софтбокс и идеальная
            типографика без дизайнеров
          </motion.p>

          <motion.div
            custom={3}
            variants={fadeUp}
            initial="hidden"
            animate="show"
            className="mt-8 flex flex-wrap items-center gap-3"
          >
            <GlassButton
              size="lg"
              icon={Sparkles}
              onClick={() => router.push("/register")}
            >
              Сгенерировать бесплатно
            </GlassButton>
            <GlassButton
              size="lg"
              icon={Play}
              className="border border-white/12 !bg-none bg-white/[0.04] text-foreground shadow-none [background-image:none]"
              onClick={() => {
                document
                  .getElementById("demo-360")
                  ?.scrollIntoView({ behavior: "smooth" })
              }}
            >
              Посмотреть демо 360°
            </GlassButton>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, scale: 0.94, y: 36 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{
            delay: 0.28,
            duration: 0.7,
            ease: [0.22, 1, 0.36, 1],
          }}
          className="relative mx-auto flex w-full justify-center lg:justify-end"
        >
          <div
            className="pointer-events-none absolute -inset-8 -z-10 rounded-full bg-emerald/10 blur-3xl"
            aria-hidden
          />
          <BeforeAfterSlider />
        </motion.div>
      </div>
    </section>
  )
}

export { HeroSection }
