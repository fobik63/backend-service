"use client"

import {
  BadgePercent,
  Lamp,
  Rotate3d,
  Scissors,
  type LucideIcon,
} from "lucide-react"
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react"
import { motion, useInView } from "framer-motion"

import { GlassCard } from "@/components/ui/glass-card"
import { SectionHeader } from "@/components/ui/section-header"
import { cn } from "@/lib/utils"

type Feature = {
  id: string
  title: string
  description: string
  icon: LucideIcon
  demo: ReactNode
}

function SoftboxDemo() {
  const ref = useRef<HTMLDivElement>(null)
  const [angle, setAngle] = useState(-28)
  const [warmth, setWarmth] = useState(0.35)
  const dragging = useRef(false)

  const updateFromPointer = useCallback((clientX: number, clientY: number) => {
    const el = ref.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = (clientX - rect.left) / rect.width - 0.5
    const y = (clientY - rect.top) / rect.height - 0.5
    setAngle(Math.atan2(y, x) * (180 / Math.PI))
    setWarmth(Math.min(1, Math.max(0, 0.5 - y)))
  }, [])

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = true
    e.currentTarget.setPointerCapture(e.pointerId)
    updateFromPointer(e.clientX, e.clientY)
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    updateFromPointer(e.clientX, e.clientY)
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = false
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }

  const lightColor = `color-mix(in srgb, #f8fafc ${Math.round((1 - warmth) * 100)}%, #f59e0b ${Math.round(warmth * 100)}%)`
  const soft = 18 + warmth * 28

  return (
    <div
      ref={ref}
      className="relative aspect-[16/10] w-full cursor-crosshair touch-none overflow-hidden rounded-lg bg-loft select-none"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      role="img"
      aria-label="Демо виртуального софтбокса: перетащите курсор, чтобы менять угол и температуру света"
    >
      <div
        className="absolute inset-0 transition-[background] duration-150"
        style={{
          background: `
            radial-gradient(
              circle at ${50 + Math.cos((angle * Math.PI) / 180) * 38}% ${50 + Math.sin((angle * Math.PI) / 180) * 38}%,
              ${lightColor} 0%,
              transparent ${soft}%
            ),
            linear-gradient(160deg, #1a1d24 0%, #0f1115 100%)
          `,
        }}
      />
      <div
        className="absolute left-1/2 top-[58%] h-14 w-20 -translate-x-1/2 -translate-y-1/2 rounded-md border border-white/15 bg-gradient-to-b from-copper/40 to-sage/50"
        style={{
          boxShadow: `${Math.cos((angle * Math.PI) / 180) * 18}px ${8 + Math.sin((angle * Math.PI) / 180) * 10}px ${soft}px rgba(0,0,0,0.55)`,
        }}
      />
      <div
        className="absolute size-3 rounded-full border border-white/40 shadow-[0_0_16px_rgba(16,185,129,0.45)]"
        style={{
          left: `calc(50% + ${Math.cos((angle * Math.PI) / 180) * 38}% - 6px)`,
          top: `calc(50% + ${Math.sin((angle * Math.PI) / 180) * 38}% - 6px)`,
          background: lightColor,
        }}
      />
      <span className="absolute bottom-2 left-2 font-heading text-[10px] tracking-wide text-text-muted uppercase">
        Угол · температура · тень
      </span>
    </div>
  )
}

function CutoutDemo() {
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => {
      setPhase((p) => (p + 1) % 3)
    }, 1800)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div
      className="relative aspect-[16/10] w-full overflow-hidden rounded-lg bg-[linear-gradient(135deg,#1a1d24_25%,#12141a_25%,#12141a_50%,#1a1d24_50%,#1a1d24_75%,#12141a_75%)] bg-[length:16px_16px] select-none"
      role="img"
      aria-label="Демо AI-вырезки: чистый контур товара без ореолов"
    >
      <div
        className={cn(
          "absolute inset-0 transition-opacity duration-500",
          phase === 0 ? "opacity-100" : "opacity-0"
        )}
      >
        <div className="absolute left-1/2 top-1/2 h-16 w-24 -translate-x-1/2 -translate-y-1/2 rounded-lg bg-copper/50 blur-[1px] ring-4 ring-white/70" />
        <span className="absolute top-2 left-2 rounded bg-loft/80 px-1.5 py-0.5 font-heading text-[10px] text-amber">
          До: ореол
        </span>
      </div>
      <div
        className={cn(
          "absolute inset-0 flex items-center justify-center transition-opacity duration-500",
          phase === 1 ? "opacity-100" : "opacity-0"
        )}
      >
        <motion.div
          className="h-16 w-24 rounded-lg bg-gradient-to-br from-copper/70 to-sage"
          style={{
            clipPath: "inset(0 round 8px)",
          }}
          animate={{ scale: [0.96, 1.02, 1] }}
          transition={{ duration: 1.2, ease: "easeOut" }}
        />
        <div className="pointer-events-none absolute inset-0 border border-dashed border-emerald/50" />
        <span className="absolute top-2 left-2 rounded bg-loft/80 px-1.5 py-0.5 font-heading text-[10px] text-emerald">
          Скан краёв
        </span>
      </div>
      <div
        className={cn(
          "absolute inset-0 flex items-center justify-center transition-opacity duration-500",
          phase === 2 ? "opacity-100" : "opacity-0"
        )}
      >
        <div className="h-16 w-24 rounded-lg bg-gradient-to-br from-copper/80 to-sage shadow-[0_8px_24px_rgba(0,0,0,0.35)]" />
        <span className="absolute top-2 left-2 rounded bg-loft/80 px-1.5 py-0.5 font-heading text-[10px] text-emerald">
          После: чисто
        </span>
      </div>
    </div>
  )
}

function Rotate360Demo() {
  const [rotation, setRotation] = useState(0)
  const dragging = useRef(false)
  const lastX = useRef(0)
  const auto = useRef(true)

  useEffect(() => {
    const id = window.setInterval(() => {
      if (!auto.current) return
      setRotation((r) => (r + 1.2) % 360)
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
    setRotation((r) => (r + dx * 0.7) % 360)
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = false
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
    window.setTimeout(() => {
      auto.current = true
    }, 1200)
  }

  const face = ((rotation % 360) + 360) % 360
  const depth = Math.cos((face * Math.PI) / 180)

  return (
    <div
      className="relative aspect-[16/10] w-full cursor-ew-resize touch-none overflow-hidden rounded-lg bg-loft select-none"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      role="img"
      aria-label="Демо 360° обзора: перетащите для вращения товара"
    >
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(16,185,129,0.12),transparent_65%)]" />
      <div className="absolute inset-x-8 bottom-6 h-px bg-gradient-to-r from-transparent via-white/20 to-transparent" />
      <div
        className="absolute left-1/2 top-[48%] h-16 w-20 -translate-x-1/2 -translate-y-1/2 rounded-lg border border-white/20 bg-gradient-to-br from-emerald/30 via-sage to-loft-surface"
        style={{
          transform: `translate(-50%, -50%) rotateY(${face}deg) scaleX(${0.72 + Math.abs(depth) * 0.28})`,
          boxShadow: `0 ${10 + (1 - Math.abs(depth)) * 8}px 28px rgba(0,0,0,0.45)`,
        }}
      >
        <div className="absolute inset-x-2 top-2 h-1 rounded-full bg-white/25" />
        <div className="absolute inset-x-4 top-5 h-1 rounded-full bg-white/15" />
      </div>
      <div className="absolute right-2 bottom-2 flex items-center gap-1 font-heading text-[10px] text-text-muted uppercase tracking-wide">
        <Rotate3d className="size-3 text-emerald" />
        360°
      </div>
      <svg
        className="absolute bottom-3 left-1/2 size-10 -translate-x-1/2 text-emerald/40"
        viewBox="0 0 40 40"
        aria-hidden
      >
        <circle
          cx="20"
          cy="20"
          r="14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
          strokeDasharray="4 6"
          transform={`rotate(${face} 20 20)`}
        />
      </svg>
    </div>
  )
}

function InfographicDemo() {
  return (
    <div
      className="relative aspect-[16/10] w-full overflow-hidden rounded-lg bg-loft select-none"
      role="img"
      aria-label="Демо готовой инфографики: плашки и скидки"
    >
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_70%_40%,rgba(46,74,56,0.45),transparent_60%)]" />
      <div className="absolute left-1/2 top-[55%] h-14 w-16 -translate-x-1/2 -translate-y-1/2 rounded-md bg-gradient-to-b from-copper/50 to-sage/60" />

      <motion.div
        className="absolute top-3 left-3 rounded-md bg-[#1b3e2b] px-2 py-1 font-heading text-[10px] font-semibold text-emerald"
        initial={{ opacity: 0, x: -12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.2, duration: 0.45 }}
      >
        −35%
      </motion.div>
      <motion.div
        className="absolute top-3 right-3 rounded-md border border-copper/40 bg-loft-surface/90 px-2 py-1 font-heading text-[10px] text-copper"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.45, duration: 0.45 }}
      >
        Хит продаж
      </motion.div>
      <motion.div
        className="absolute bottom-3 left-3 max-w-[55%] rounded-md border border-white/10 bg-loft-surface/90 px-2 py-1.5"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.7, duration: 0.45 }}
      >
        <p className="font-heading text-[10px] font-semibold text-foreground">
          Быстрая доставка
        </p>
        <p className="text-[9px] text-text-muted">Гарантия 12 мес.</p>
      </motion.div>
      <motion.div
        className="absolute right-3 bottom-3 rounded-full bg-emerald px-2 py-1 font-heading text-[10px] font-semibold text-loft"
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.95, duration: 0.4 }}
      >
        NEW
      </motion.div>
    </div>
  )
}

const FEATURES: Feature[] = [
  {
    id: "softbox",
    title: "Виртуальный Софтбокс",
    description: "Настройка угла света, температуры и мягкости тени.",
    icon: Lamp,
    demo: <SoftboxDemo />,
  },
  {
    id: "cutout",
    title: "AI-Вырезка без дефектов",
    description: "Чистые края товара без белых пикселей и ореолов.",
    icon: Scissors,
    demo: <CutoutDemo />,
  },
  {
    id: "rotate-360",
    title: "360° Обзор товара",
    description: "Генерация 3D-видео вращения для маркетплейсов.",
    icon: Rotate3d,
    demo: <Rotate360Demo />,
  },
  {
    id: "infographic",
    title: "Готовая Инфографика",
    description: "Автоматический рендер плашек, скидок и шрифтов без ошибок.",
    icon: BadgePercent,
    demo: <InfographicDemo />,
  },
]

const cardVariants = {
  hidden: { opacity: 0, y: 28 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      delay: 0.08 + i * 0.1,
      duration: 0.5,
      ease: [0.22, 1, 0.36, 1] as const,
    },
  }),
}

function FeaturesSection() {
  const sectionRef = useRef<HTMLElement>(null)
  const inView = useInView(sectionRef, { once: true, amount: 0.2 })

  return (
    <section
      id="features"
      ref={sectionRef}
      className="relative isolate scroll-mt-24 py-20 sm:py-28"
    >
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden>
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_40%_at_50%_0%,rgba(16,185,129,0.08),transparent_55%)]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_40%_30%_at_10%_80%,rgba(194,166,140,0.06),transparent_50%)]" />
      </div>

      <div className="mx-auto max-w-6xl px-5">
        <SectionHeader
          align="center"
          title="Возможности"
          subtitle="Студийный свет, чистая вырезка, 360° и инфографика — всё в одном пайплайне CARD AI"
          className="mb-12 sm:mb-14"
        />

        <div className="grid gap-5 sm:grid-cols-2 lg:gap-6">
          {FEATURES.map((feature, i) => {
            const Icon = feature.icon
            return (
              <motion.div
                key={feature.id}
                custom={i}
                variants={cardVariants}
                initial="hidden"
                animate={inView ? "show" : "hidden"}
              >
                <GlassCard className="group flex h-full flex-col gap-4" padding="md">
                  <div className="overflow-hidden rounded-lg border border-white/5">
                    {feature.demo}
                  </div>
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg border border-emerald/25 bg-emerald/10 text-emerald transition-colors group-hover:border-emerald/40 group-hover:bg-emerald/15">
                      <Icon className="size-4" strokeWidth={1.75} aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <h3 className="font-heading text-lg font-semibold tracking-tight text-foreground">
                        {feature.title}
                      </h3>
                      <p className="mt-1.5 text-sm leading-relaxed text-text-muted">
                        {feature.description}
                      </p>
                    </div>
                  </div>
                </GlassCard>
              </motion.div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

export { FeaturesSection }
