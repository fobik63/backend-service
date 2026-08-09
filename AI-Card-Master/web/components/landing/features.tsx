"use client"

import {
  BadgePercent,
  Gem,
  Grip,
  Lamp,
  Leaf,
  Link2,
  MessageSquareWarning,
  Rotate3d,
  Scissors,
  Star,
  Wind,
  type LucideIcon,
} from "lucide-react"
import dynamic from "next/dynamic"
import Image from "next/image"
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react"
import { motion, useInView } from "framer-motion"

import { ErrorBoundary } from "@/components/error-boundary"
import { GlassCard } from "@/components/ui/glass-card"
import { SectionHeader } from "@/components/ui/section-header"
import { cn } from "@/lib/utils"

const Sneaker3DViewer = dynamic(
  () =>
    import("@/components/landing/sneaker-3d-viewer").then(
      (mod) => mod.Sneaker3DViewer
    ),
  {
    ssr: false,
    loading: () => (
      <div className="absolute inset-0 flex items-center justify-center bg-[#1a1612]">
        <div className="size-10 animate-pulse rounded-full border border-copper/40 bg-copper/10" />
      </div>
    ),
  }
)

type Feature = {
  id: string
  title: string
  description: string
  icon: LucideIcon
  demo: ReactNode
}

function SoftboxDemo() {
  const ref = useRef<HTMLDivElement>(null)
  const [angle, setAngle] = useState(-32)
  const [warmth, setWarmth] = useState(0.32)
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

  const rad = (angle * Math.PI) / 180
  const lx = 50 + Math.cos(rad) * 36
  const ly = 42 + Math.sin(rad) * 32
  const lightColor = `color-mix(in srgb, #f8fafc ${Math.round((1 - warmth) * 100)}%, #f59e0b ${Math.round(warmth * 100)}%)`
  const soft = 18 + warmth * 28

  return (
    <div
      ref={ref}
      className="relative aspect-[16/10] w-full cursor-crosshair touch-none overflow-hidden rounded-lg bg-[#0c0e12] select-none"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      role="img"
      aria-label="Демо виртуального софтбокса: перетащите курсор, чтобы менять угол и температуру света"
    >
      {/* Studio floor + backdrop */}
      <div className="absolute inset-0 bg-[linear-gradient(180deg,#14171d_0%,#0d0f12_55%,#0a0b0e_100%)]" />
      <div className="absolute inset-x-0 bottom-0 h-[42%] bg-[linear-gradient(180deg,transparent,rgba(27,62,43,0.25))]" />

      {/* Softbox key light bloom */}
      <div
        className="absolute size-16 -translate-x-1/2 -translate-y-1/2 rounded-lg border border-white/30"
        style={{
          left: `${lx}%`,
          top: `${ly}%`,
          background: `linear-gradient(135deg, ${lightColor}, rgba(255,255,255,0.35))`,
          boxShadow: `0 0 ${soft}px ${lightColor}`,
        }}
      />

      {/* Vector light rays (SVG) */}
      <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => {
          const spread = (i - 2) * 7
          const tx = 50 + Math.cos(rad + (spread * Math.PI) / 180) * 8
          const ty = 58 + Math.sin(rad + (spread * Math.PI) / 180) * 6
          return (
            <line
              key={i}
              x1={`${lx}%`}
              y1={`${ly}%`}
              x2={`${tx}%`}
              y2={`${ty}%`}
              stroke={lightColor}
              strokeOpacity={0.12 + (2 - Math.abs(i - 2)) * 0.08}
              strokeWidth={1.2}
            />
          )
        })}
      </svg>

      {/* Real product cutout under soft light */}
      <div
        className="absolute left-1/2 top-[56%] h-24 w-20 -translate-x-1/2 -translate-y-1/2"
        style={{
          filter: `drop-shadow(${Math.cos(rad) * 10}px ${8 + Math.sin(rad) * 6}px ${soft * 0.55}px rgba(0,0,0,0.55))`,
        }}
      >
        <Image
          src="/landing/perfume-transparent.png"
          alt=""
          fill
          sizes="80px"
          className="object-contain"
          aria-hidden
        />
      </div>
      <div
        className="absolute left-1/2 top-[78%] h-3 w-24 -translate-x-1/2 rounded-[100%] bg-black/45 blur-md"
        style={{ opacity: 0.45 + warmth * 0.25 }}
      />

      <span className="absolute bottom-2 left-2 font-heading text-[10px] tracking-wide text-text-muted uppercase">
        Источник · товар · лучи
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
      className="relative aspect-[16/10] w-full overflow-hidden rounded-lg bg-[linear-gradient(135deg,#161a20_25%,#0e1116_25%,#0e1116_50%,#161a20_50%,#161a20_75%,#0e1116_75%)] bg-[length:16px_16px] select-none"
      role="img"
      aria-label="Демо AI-вырезки: товар по центру, аккуратный край без белых пикселей и лесенки"
    >
      {/* Phase 0 — raw with white halo fringe */}
      <div
        className={cn(
          "absolute inset-0 transition-opacity duration-500",
          phase === 0 ? "opacity-100" : "opacity-0"
        )}
      >
        <div className="absolute inset-[8%] flex items-center justify-center">
          <div className="relative h-full w-[42%] max-w-[7.5rem]">
            <Image
              src="/landing/perfume-raw.png"
              alt=""
              fill
              sizes="140px"
              className="object-contain object-center"
              aria-hidden
            />
            {/* Simulated cutout halo / fringe */}
            <div
              className="pointer-events-none absolute inset-[-3%] rounded-[28%] ring-[5px] ring-white/75 blur-[0.4px]"
              aria-hidden
            />
          </div>
        </div>
        <span className="absolute top-2 left-2 z-10 rounded bg-loft/80 px-1.5 py-0.5 font-heading text-[10px] text-amber">
          До: ореол
        </span>
      </div>

      {/* Phase 1 — edge scan grid */}
      <div
        className={cn(
          "absolute inset-0 transition-opacity duration-500",
          phase === 1 ? "opacity-100" : "opacity-0"
        )}
      >
        <div className="absolute inset-[8%] flex items-center justify-center">
          <motion.div
            className="relative h-full w-[42%] max-w-[7.5rem]"
            animate={{ scale: [0.98, 1.02, 1] }}
            transition={{ duration: 1.2, ease: "easeOut" }}
          >
            <Image
              src="/landing/perfume-transparent.png"
              alt=""
              fill
              sizes="140px"
              className="object-contain object-center"
              aria-hidden
            />
          </motion.div>
        </div>

        {/* Centered scanner frame + grid */}
        <div className="pointer-events-none absolute inset-[10%] rounded-md border border-emerald/50">
          <div
            className="absolute inset-0 opacity-80"
            style={{
              backgroundImage:
                "linear-gradient(to right, rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,0.08) 1px, transparent 1px)",
              backgroundSize: "14px 14px",
              backgroundPosition: "center",
            }}
          />
          {/* Corner brackets */}
          <span className="absolute top-0 left-0 size-3 border-t-2 border-l-2 border-emerald" />
          <span className="absolute top-0 right-0 size-3 border-t-2 border-r-2 border-emerald" />
          <span className="absolute bottom-0 left-0 size-3 border-b-2 border-l-2 border-emerald" />
          <span className="absolute bottom-0 right-0 size-3 border-b-2 border-r-2 border-emerald" />
          <motion.div
            className="absolute inset-x-2 h-0.5 bg-gradient-to-r from-transparent via-emerald to-transparent"
            animate={{ top: ["8%", "88%", "8%"] }}
            transition={{ duration: 1.6, ease: "easeInOut", repeat: Infinity }}
          />
        </div>
        <span className="absolute top-2 left-2 z-10 rounded bg-loft/80 px-1.5 py-0.5 font-heading text-[10px] text-emerald">
          Скан краёв
        </span>
      </div>

      {/* Phase 2 — clean cutout */}
      <div
        className={cn(
          "absolute inset-0 transition-opacity duration-500",
          phase === 2 ? "opacity-100" : "opacity-0"
        )}
      >
        <div className="absolute inset-[8%] flex items-center justify-center">
          <div className="relative h-full w-[42%] max-w-[7.5rem] drop-shadow-[0_14px_28px_rgba(0,0,0,0.45)]">
            <Image
              src="/landing/perfume-transparent.png"
              alt=""
              fill
              sizes="140px"
              className="object-contain object-center"
              aria-hidden
            />
          </div>
        </div>
        <span className="absolute top-2 left-2 z-10 rounded bg-loft/80 px-1.5 py-0.5 font-heading text-[10px] text-emerald">
          После: чисто
        </span>
        <span className="absolute right-2 bottom-2 z-10 rounded bg-loft/80 px-1.5 py-0.5 font-heading text-[9px] tracking-wide text-text-muted uppercase">
          Край без белых пикселей
        </span>
      </div>
    </div>
  )
}

function Rotate360Demo() {
  return (
    <div className="relative aspect-[16/10] w-full overflow-hidden rounded-lg">
      <ErrorBoundary
        title="3D-превью недоступно"
        description="WebGL-вьюер не смог отрисовать модель. Остальной лендинг продолжает работать."
        className="absolute inset-0 rounded-none border-0"
      >
        <Sneaker3DViewer
          variant="card"
          className="absolute inset-0"
          autoRotate
          enableZoom
        />
      </ErrorBoundary>
    </div>
  )
}

function InfographicDemo() {
  return (
    <div
      className="relative aspect-[16/10] w-full overflow-hidden rounded-lg select-none"
      role="img"
      aria-label="Демо готовой инфографики: полная карточка товара с ценой, скидкой и материалами"
    >
      {/* Accent studio backdrop */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_55%_40%,#2a3d32_0%,#12151a_55%,#0c0e12_100%)]" />
      <div
        className="pointer-events-none absolute -right-6 top-0 h-full w-1/2 opacity-40"
        style={{
          background:
            "linear-gradient(115deg, transparent 20%, rgba(125,143,120,0.35) 45%, transparent 70%)",
        }}
        aria-hidden
      />

      <div className="absolute inset-2.5 overflow-hidden rounded-xl border border-white/10 bg-[#10131a]/90 copper-border shadow-[0_16px_40px_rgba(0,0,0,0.45)]">
        {/* Full product — not cropped */}
        <div className="absolute inset-x-[18%] top-[6%] bottom-[34%]">
          <Image
            src="/landing/sneaker-transparent.png"
            alt=""
            fill
            sizes="(max-width: 768px) 70vw, 240px"
            className="object-contain object-center drop-shadow-[0_18px_28px_rgba(0,0,0,0.55)]"
            aria-hidden
          />
        </div>

        {/* Discount + hit badges */}
        <motion.div
          className="absolute top-2 left-2 flex flex-col gap-1"
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.12, duration: 0.35 }}
        >
          <span className="inline-flex w-fit items-center gap-1 rounded-md bg-gradient-to-r from-copper to-[#8a5230] px-1.5 py-0.5 font-heading text-[9px] font-semibold text-loft">
            <Star className="size-2.5 fill-current" aria-hidden />
            Хит продаж
          </span>
          <span className="w-fit rounded-md bg-[#1b3e2b] px-1.5 py-0.5 font-heading text-[9px] font-semibold text-emerald">
            −35%
          </span>
        </motion.div>

        {/* Brand */}
        <div className="absolute top-2 right-2 text-right">
          <p className="font-heading text-[11px] font-semibold tracking-[0.14em] text-white">
            NEXORA
          </p>
          <p className="font-heading text-[8px] tracking-[0.18em] text-white/50 uppercase">
            Premium
          </p>
        </div>

        {/* Material callouts */}
        <div className="absolute top-[28%] right-2 flex flex-col gap-1.5">
          {[
            { label: "Mesh", Icon: Wind },
            { label: "Grip", Icon: Grip },
            { label: "Light", Icon: Leaf },
          ].map(({ label, Icon }, i) => (
            <motion.div
              key={label}
              className="flex items-center gap-1 rounded-md border border-white/12 bg-loft/70 px-1.5 py-1 backdrop-blur-sm"
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.2 + i * 0.1, duration: 0.3 }}
            >
              <span className="flex size-4 items-center justify-center rounded-full bg-emerald/20 text-emerald">
                <Icon className="size-2.5" aria-hidden />
              </span>
              <span className="font-heading text-[8px] text-foreground/90">
                {label}
              </span>
            </motion.div>
          ))}
        </div>

        {/* Price + CTA bar */}
        <div className="absolute inset-x-0 bottom-0 border-t border-white/8 bg-loft/70 px-2.5 py-2 backdrop-blur-md">
          <div className="flex items-end justify-between gap-2">
            <div>
              <p className="font-heading text-base font-semibold leading-none text-foreground">
                4 990 ₽{" "}
                <span className="text-[10px] font-normal text-text-muted line-through">
                  7 690 ₽
                </span>
              </p>
              <p className="mt-1 font-heading text-[8px] text-copper">
                Премиальное качество
              </p>
            </div>
            <div className="flex gap-0.5">
              {[40, 41, 42, 43].map((size) => (
                <span
                  key={size}
                  className={cn(
                    "flex size-5 items-center justify-center rounded-sm font-heading text-[8px]",
                    size === 42
                      ? "bg-copper text-loft"
                      : "border border-white/15 bg-white/5 text-foreground/75"
                  )}
                >
                  {size}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function CompetitorParserDemo() {
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => {
      setPhase((p) => (p + 1) % 3)
    }, 2000)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div
      className="relative aspect-[16/10] w-full overflow-hidden rounded-lg bg-[#0c0e12] select-none"
      role="img"
      aria-label="Демо умного парсера: ссылка конкурента превращается в структуру карточки"
    >
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_30%_40%,rgba(5,150,105,0.14),transparent_60%)]" />

      <div className="absolute inset-3 flex flex-col gap-2">
        <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-[#14171d]/90 px-2.5 py-2">
          <Link2 className="size-3.5 shrink-0 text-emerald" aria-hidden />
          <motion.span
            className="truncate font-heading text-[10px] text-text-muted"
            key={phase}
            initial={{ opacity: 0.4 }}
            animate={{ opacity: 1 }}
          >
            ozon.ru/product/competitor-sku-48291
          </motion.span>
          <motion.span
            className="ml-auto shrink-0 rounded bg-emerald/15 px-1.5 py-0.5 font-heading text-[9px] text-emerald"
            animate={{ opacity: phase === 0 ? [0.5, 1, 0.5] : 1 }}
            transition={{ duration: 1.2, repeat: phase === 0 ? Infinity : 0 }}
          >
            {phase === 0 ? "Парсинг…" : "Готово"}
          </motion.span>
        </div>

        <div className="grid flex-1 grid-cols-[1fr_1.15fr] gap-2">
          <div className="relative overflow-hidden rounded-lg border border-white/8 bg-[#12141a]">
            <motion.div
              className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-transparent via-emerald to-transparent"
              animate={{ y: phase === 0 ? [0, 72, 0] : 72 }}
              transition={{
                duration: 1.6,
                ease: "easeInOut",
                repeat: phase === 0 ? Infinity : 0,
              }}
            />
            <div className="absolute left-1/2 top-1/2 h-12 w-14 -translate-x-1/2 -translate-y-1/2 rounded-md bg-gradient-to-b from-copper/50 to-sage/70" />
            <span className="absolute bottom-1.5 left-1.5 font-heading text-[9px] text-text-muted uppercase">
              Фото
            </span>
          </div>

          <div className="flex flex-col justify-center gap-1.5 rounded-lg border border-white/8 bg-[#12141a] px-2.5 py-2">
            {["Структура карточки", "Характеристики", "Галерея 6 фото"].map(
              (label, i) => (
                <motion.div
                  key={label}
                  className="flex items-center gap-2"
                  initial={{ opacity: 0, x: 8 }}
                  animate={{
                    opacity: phase >= 1 ? 1 : 0.25,
                    x: phase >= 1 ? 0 : 8,
                  }}
                  transition={{
                    delay: phase >= 1 ? i * 0.12 : 0,
                    duration: 0.35,
                  }}
                >
                  <span
                    className={cn(
                      "size-1.5 rounded-full",
                      phase >= 2 ? "bg-emerald" : "bg-white/25"
                    )}
                  />
                  <span className="font-heading text-[10px] text-foreground/90">
                    {label}
                  </span>
                </motion.div>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function SmartSeoDemo() {
  return (
    <div
      className="relative aspect-[16/10] w-full overflow-hidden rounded-lg bg-[#0c0e12] select-none"
      role="img"
      aria-label="Демо Smart SEO: негативные отзывы закрываются инфографикой"
    >
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_70%_20%,rgba(194,166,140,0.12),transparent_55%)]" />

      <div className="absolute inset-3 grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1.5 rounded-lg border border-white/8 bg-[#12141a] p-2">
          <span className="font-heading text-[9px] tracking-wide text-amber uppercase">
            Негатив конкурентов
          </span>
          {[
            "Тонкий материал",
            "Нет размеров",
            "Фото не как в жизни",
          ].map((pain, i) => (
            <motion.div
              key={pain}
              className="flex items-start gap-1.5 rounded-md border border-white/5 bg-loft/50 px-1.5 py-1"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 + i * 0.12 }}
            >
              <MessageSquareWarning
                className="mt-0.5 size-3 shrink-0 text-copper/80"
                aria-hidden
              />
              <span className="font-heading text-[9px] leading-snug text-text-muted">
                {pain}
              </span>
            </motion.div>
          ))}
        </div>

        <div className="relative overflow-hidden rounded-lg border border-emerald/25 bg-[#12141a] p-2">
          <span className="font-heading text-[9px] tracking-wide text-emerald uppercase">
            Закрытие болей
          </span>
          <div className="relative mt-2 flex flex-col items-center justify-center py-1">
            <div className="h-10 w-12 rounded-md bg-gradient-to-b from-[#e8d5c0] to-[#7d8f78] shadow-[0_8px_18px_rgba(0,0,0,0.4)]" />
            <motion.div
              className="absolute top-0 right-0 rounded bg-[#1b3e2b] px-1.5 py-0.5 font-heading text-[8px] font-semibold text-emerald"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.45 }}
            >
              Плотность ✓
            </motion.div>
            <motion.div
              className="absolute bottom-1 left-0 rounded border border-copper/40 bg-loft/80 px-1.5 py-0.5 font-heading text-[8px] text-copper"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.65 }}
            >
              Таблица размеров
            </motion.div>
          </div>
          <motion.p
            className="mt-2 font-heading text-[9px] text-emerald/90"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.85 }}
          >
            SEO + инфографика → ТОП
          </motion.p>
        </div>
      </div>
    </div>
  )
}

function UltraHdDemo() {
  const [shine, setShine] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => {
      setShine((s) => (s + 1) % 3)
    }, 1600)
    return () => window.clearInterval(id)
  }, [])

  const textures = [
    { label: "Кожа", from: "#8b5a3c", to: "#3d2418" },
    { label: "Ткань", from: "#6b7c6e", to: "#2f3a34" },
    { label: "Металл", from: "#c9c4bc", to: "#6a6560" },
  ] as const

  return (
    <div
      className="relative aspect-[16/10] w-full overflow-hidden rounded-lg bg-[#0c0e12] select-none"
      role="img"
      aria-label="Демо 3D Ultra-HD: студийный рендер текстур кожи, ткани и металла"
    >
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(255,255,255,0.04),transparent_65%)]" />

      <div className="absolute inset-3 flex items-end justify-center gap-2 pb-6">
        {textures.map((tex, i) => {
          const active = shine === i
          return (
            <motion.div
              key={tex.label}
              className="relative flex flex-col items-center gap-1.5"
              animate={{
                y: active ? -4 : 0,
                scale: active ? 1.05 : 1,
              }}
              transition={{ type: "spring", stiffness: 320, damping: 22 }}
            >
              <div
                className="relative h-14 w-12 overflow-hidden rounded-md border border-white/15 shadow-[0_12px_28px_rgba(0,0,0,0.45)]"
                style={{
                  background: `linear-gradient(145deg, ${tex.from}, ${tex.to})`,
                }}
              >
                <motion.div
                  className="absolute inset-0 bg-gradient-to-br from-white/35 via-transparent to-transparent"
                  animate={{ opacity: active ? 0.85 : 0.25 }}
                />
                <motion.div
                  className="absolute -inset-y-2 w-6 -skew-x-12 bg-white/25 blur-[1px]"
                  animate={{
                    x: active ? [-20, 48] : -20,
                    opacity: active ? [0, 0.7, 0] : 0,
                  }}
                  transition={{ duration: 1.1, ease: "easeInOut" }}
                />
              </div>
              <span
                className={cn(
                  "font-heading text-[9px] tracking-wide uppercase",
                  active ? "text-emerald" : "text-text-muted"
                )}
              >
                {tex.label}
              </span>
            </motion.div>
          )
        })}
      </div>

      <span className="absolute top-2 right-2 flex items-center gap-1 rounded-md border border-emerald/30 bg-loft/80 px-2 py-0.5 font-heading text-[9px] text-emerald">
        <Gem className="size-3" aria-hidden />
        Ultra-HD
      </span>
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
    description:
      "Интерактивная 3D-модель: вращайте во всех плоскостях, приближайте и рассматривайте товар со всех сторон.",
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
  {
    id: "competitor-parser",
    title: "Умный парсер & Сканер конкурентов",
    description:
      "Вставляешь ссылку на товар конкурента — система парсит фото, структуру и характеристики.",
    icon: Link2,
    demo: <CompetitorParserDemo />,
  },
  {
    id: "smart-seo",
    title: "Smart SEO & Закрытие негатива",
    description:
      "AI генерирует описание и инфографику на основе анализа частых негативных отзывов конкурентов, закрывая боли покупателей и выводя карточку в ТОП.",
    icon: MessageSquareWarning,
    demo: <SmartSeoDemo />,
  },
  {
    id: "ultra-hd",
    title: "3D Ultra-HD качество",
    description:
      "Студийный рендер текстур кожи, ткани и металла для максимального CTR.",
    icon: Gem,
    demo: <UltraHdDemo />,
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
      className="relative isolate scroll-mt-24 py-16 md:py-24"
    >
      <div className="mx-auto max-w-6xl px-5">
        <div className="section-glass flex flex-col gap-12 rounded-3xl px-5 py-10 sm:px-8 sm:py-12 lg:px-10">
          <SectionHeader
            align="center"
            title="Возможности"
            subtitle="Студийный свет, вырезка, 360°, парсер конкурентов, Smart SEO и Ultra-HD — всё в одном пайплайне CARD AI"
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
                      <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg border border-white/12 bg-white/[0.04] text-foreground transition-colors group-hover:border-white/20 group-hover:bg-white/[0.06]">
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
      </div>
    </section>
  )
}

export { FeaturesSection }
