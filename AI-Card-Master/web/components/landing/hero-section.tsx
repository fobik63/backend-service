"use client"

import { Play, Sparkles, X } from "lucide-react"
import Image from "next/image"
import { useRouter } from "next/navigation"
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react"
import { AnimatePresence, motion } from "framer-motion"

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

  const onHandlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
    e.preventDefault()
    interacted.current = true
    dragging.current = true
    e.currentTarget.setPointerCapture(e.pointerId)
    updateFromClientX(e.clientX)
  }

  const onHandlePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    e.stopPropagation()
    updateFromClientX(e.clientX)
  }

  const onHandlePointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
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
        "border border-white/10 bg-loft-surface copper-border",
        "shadow-[0_24px_80px_rgba(0,0,0,0.45)]",
        "select-none"
      )}
      role="img"
      aria-label="Сравнение: сырое фото товара и готовая карточка Ozon"
    >
      {/* After — готовая карточка (pointer-events isolated) */}
      <div className="pointer-events-none absolute inset-0">
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
        className="pointer-events-none absolute inset-0 overflow-hidden"
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
        <span className="absolute left-3 top-3 rounded-md bg-loft/80 px-2 py-1 font-heading text-[11px] font-semibold tracking-wide text-foreground backdrop-blur-sm">
          До
        </span>
      </div>

      {/* Divider + handle — единственная зона drag */}
      <div
        className="absolute inset-y-0 z-20 w-12 -translate-x-1/2 touch-none cursor-ew-resize"
        style={{ left: `${position}%` }}
        onPointerDown={onHandlePointerDown}
        onPointerMove={onHandlePointerMove}
        onPointerUp={onHandlePointerUp}
        onPointerCancel={onHandlePointerUp}
        role="slider"
        aria-valuemin={4}
        aria-valuemax={96}
        aria-valuenow={Math.round(position)}
        aria-label="Разделитель до/после"
        tabIndex={0}
        onKeyDown={(e) => {
          interacted.current = true
          if (e.key === "ArrowLeft") setPosition((p) => Math.max(4, p - 2))
          if (e.key === "ArrowRight") setPosition((p) => Math.min(96, p + 2))
        }}
      >
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-white/80" />
        <div className="absolute left-1/2 top-1/2 flex size-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-loft/85 shadow-[0_0_24px_rgba(16,185,129,0.35)] backdrop-blur-md">
          <span className="flex gap-0.5 text-emerald">
            <span className="block h-3.5 w-0.5 rounded-full bg-current opacity-70" />
            <span className="block h-3.5 w-0.5 rounded-full bg-current" />
            <span className="block h-3.5 w-0.5 rounded-full bg-current opacity-70" />
          </span>
        </div>
      </div>

      {/* Bottom range — отдельный контроллер, stopPropagation */}
      <div
        className="absolute inset-x-0 bottom-0 z-30 flex justify-center px-4 pb-3 pt-8"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <label className="sr-only" htmlFor="hero-compare-slider">
          Ползунок сравнения до и после
        </label>
        <input
          id="hero-compare-slider"
          type="range"
          min={4}
          max={96}
          value={position}
          onChange={(e) => {
            interacted.current = true
            setPosition(Number(e.target.value))
          }}
          onPointerDown={(e) => {
            e.stopPropagation()
            interacted.current = true
          }}
          className="h-2 w-[min(80%,16rem)] cursor-pointer appearance-none rounded-full bg-white/15 accent-emerald"
        />
      </div>
    </div>
  )
}

function Demo360Viewer({ onClose }: { onClose: () => void }) {
  const [rotation, setRotation] = useState(0)
  const dragging = useRef(false)
  const lastX = useRef(0)
  const auto = useRef(true)

  useEffect(() => {
    const id = window.setInterval(() => {
      if (!auto.current) return
      setRotation((r) => (r + 0.9) % 360)
    }, 32)
    return () => window.clearInterval(id)
  }, [])

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    auto.current = false
    dragging.current = true
    lastX.current = e.clientX
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    const dx = e.clientX - lastX.current
    lastX.current = e.clientX
    setRotation((r) => (r + dx * 0.65) % 360)
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = false
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
    window.setTimeout(() => {
      auto.current = true
    }, 1400)
  }

  const face = ((rotation % 360) + 360) % 360
  const depth = Math.cos((face * Math.PI) / 180)

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Демо 360° обзора товара"
    >
      <button
        type="button"
        className="absolute inset-0 bg-loft/80 backdrop-blur-sm"
        aria-label="Закрыть"
        onClick={onClose}
      />
      <motion.div
        initial={{ opacity: 0, scale: 0.94, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
        className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl border border-white/10 bg-loft-surface copper-border shadow-[0_32px_100px_rgba(0,0,0,0.55)]"
      >
        <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
          <div>
            <p className="font-heading text-xs tracking-[0.16em] text-copper uppercase">
              Demo 360°
            </p>
            <p className="text-sm text-muted-foreground">
              Перетащите, чтобы вращать товар
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex size-9 items-center justify-center rounded-full border border-white/10 text-foreground/80 hover:bg-white/5"
            aria-label="Закрыть демо"
          >
            <X className="size-4" />
          </button>
        </div>

        <div
          className="relative aspect-[4/3] touch-none cursor-ew-resize select-none bg-[radial-gradient(ellipse_at_center,rgba(16,185,129,0.12),transparent_65%)]"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <div className="absolute inset-x-10 bottom-10 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent" />
          <div
            className="absolute left-1/2 top-[48%] h-40 w-40 -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border border-white/15 bg-loft shadow-[0_20px_50px_rgba(0,0,0,0.45)]"
            style={{
              transform: `translate(-50%, -50%) rotateY(${face}deg) scaleX(${0.78 + Math.abs(depth) * 0.22})`,
              boxShadow: `0 ${14 + (1 - Math.abs(depth)) * 10}px 40px rgba(0,0,0,0.5)`,
            }}
          >
            <Image
              src="/landing/after-card.png"
              alt="Товар 360"
              fill
              className="object-cover"
              sizes="16rem"
            />
          </div>
          <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full border border-white/10 bg-loft/70 px-3 py-1 font-heading text-[11px] text-emerald backdrop-blur-md">
            <Play className="size-3" />
            {Math.round(face)}°
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-white/8 px-4 py-3">
          <GlassButton
            size="sm"
            onClick={() => {
              onClose()
              window.location.href = "/editor"
            }}
          >
            Открыть в редакторе
          </GlassButton>
        </div>
      </motion.div>
    </div>
  )
}

function HeroSection() {
  const router = useRouter()
  const [demoOpen, setDemoOpen] = useState(false)

  useEffect(() => {
    if (!demoOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDemoOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [demoOpen])

  return (
    <section className="relative isolate min-h-[100svh] overflow-hidden pt-28 pb-16 sm:pt-32">
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden>
        <div className="absolute inset-0 bg-gradient-to-b from-[#0f1115] via-[#141b17] to-[#0f1115]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_60%_at_50%_-10%,rgba(16,185,129,0.14),transparent_55%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_50%_40%_at_90%_40%,rgba(27,62,43,0.45),transparent_60%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_40%_30%_at_10%_70%,rgba(16,185,129,0.08),transparent_55%)]" />
        <div className="absolute inset-0 opacity-[0.04] noise-texture" />
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
              onClick={() => router.push("/editor")}
            >
              Сгенерировать бесплатно
            </GlassButton>
            <GlassButton
              size="lg"
              icon={Play}
              className="border border-white/12 !bg-none bg-white/[0.04] text-foreground shadow-none [background-image:none]"
              onClick={() => setDemoOpen(true)}
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

      <AnimatePresence>
        {demoOpen ? (
          <Demo360Viewer onClose={() => setDemoOpen(false)} />
        ) : null}
      </AnimatePresence>
    </section>
  )
}

export { HeroSection }
