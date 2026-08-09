"use client"

import { Maximize2, Play, Sparkles, X } from "lucide-react"
import Image from "next/image"
import { useRouter } from "next/navigation"
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type PointerEvent as ReactPointerEvent,
} from "react"
import { createPortal } from "react-dom"
import { AnimatePresence, motion } from "framer-motion"

import { Modal360 } from "@/components/landing/360-modal"
import { TropicalLeaves } from "@/components/landing/tropical-leaves"
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

const AUTO_ROTATE_MS = 30_000

type ProductPair = {
  id: string
  label: string
  beforeSrc: string
  afterSrc: string
  beforeAlt: string
  afterAlt: string
}

/** Real cutout «До» + finished marketplace card «После». */
const PRODUCT_EXAMPLES: ProductPair[] = [
  {
    id: "sneakers",
    label: "Кроссовки",
    beforeSrc: "/landing/before-product.png",
    afterSrc: "/landing/after-card.png",
    beforeAlt: "Сырое фото кроссовок до обработки",
    afterAlt: "Готовая карточка кроссовок с инфографикой",
  },
  {
    id: "perfume",
    label: "Парфюм",
    beforeSrc: "/landing/before-perfume.png",
    afterSrc: "/landing/after-perfume.png",
    beforeAlt: "Вырезанный флакон парфюма на студийном фоне",
    afterAlt: "Готовая карточка парфюма с инфографикой",
  },
  {
    id: "stationery",
    label: "Канцелярия",
    beforeSrc: "/landing/before-stationery.png",
    afterSrc: "/landing/after-stationery.png",
    beforeAlt: "Вырезанный набор карандашей на студийном фоне",
    afterAlt: "Готовая карточка канцелярии с инфографикой",
  },
  {
    id: "cosmetics",
    label: "Косметика",
    beforeSrc: "/landing/before-cosmetics.png",
    afterSrc: "/landing/after-cosmetics.png",
    beforeAlt: "Вырезанная баночка крема на студийном фоне",
    afterAlt: "Готовая карточка косметики с инфографикой",
  },
]

function ExampleLayer({
  example,
  mode,
  priority,
}: {
  example: ProductPair
  mode: "before" | "after"
  priority?: boolean
}) {
  const src = mode === "before" ? example.beforeSrc : example.afterSrc
  const alt = mode === "before" ? example.beforeAlt : example.afterAlt
  return (
    <div className="absolute inset-0">
      <Image
        src={src}
        alt={alt}
        fill
        priority={priority}
        sizes="(max-width: 768px) 100vw, 36rem"
        className="object-cover object-center"
      />
      <span
        className={cn(
          "absolute top-3 rounded-md px-2 py-1 font-heading text-[11px] font-semibold tracking-wide",
          mode === "before"
            ? "left-3 bg-loft/80 text-foreground backdrop-blur-sm"
            : "right-3 bg-emerald/90 text-loft"
        )}
      >
        {mode === "before" ? "До" : "После"}
      </span>
    </div>
  )
}

type CompareFrameProps = {
  example: ProductPair
  position: number
  onPositionChange: (value: number) => void
  onInteract: () => void
  className?: string
  sliderId: string
  showMaximize?: boolean
  onMaximize?: () => void
  priority?: boolean
}

function CompareFrame({
  example,
  position,
  onPositionChange,
  onInteract,
  className,
  sliderId,
  showMaximize = false,
  onMaximize,
  priority,
}: CompareFrameProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const updateFromClientX = useCallback(
    (clientX: number) => {
      const el = containerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const next = ((clientX - rect.left) / rect.width) * 100
      onPositionChange(Math.min(96, Math.max(4, next)))
    },
    [onPositionChange]
  )

  const onHandlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
    e.preventDefault()
    onInteract()
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

  const clipInset = Math.min(96, Math.max(4, 100 - position))

  return (
    <div
      ref={containerRef}
      className={cn(
        "relative isolate overflow-hidden rounded-2xl",
        "bg-loft-surface copper-border",
        "shadow-[0_24px_80px_rgba(0,0,0,0.45)]",
        "select-none",
        className
      )}
      role="img"
      aria-label={`Сравнение до/после: ${example.label}`}
    >
      {/* After — finished render with studio background */}
      <div className="pointer-events-none absolute inset-0 z-0">
        <ExampleLayer example={example} mode="after" priority={priority} />
      </div>

      {/* Before — full-size layer clipped from the right so product switch never drops the mask */}
      <div
        className="pointer-events-none absolute inset-0 z-[1] will-change-[clip-path]"
        style={{
          clipPath: `inset(0 ${clipInset}% 0 0)`,
          WebkitClipPath: `inset(0 ${clipInset}% 0 0)`,
        }}
      >
        <ExampleLayer example={example} mode="before" priority={priority} />
      </div>

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
          onInteract()
          if (e.key === "ArrowLeft") {
            onPositionChange(Math.min(96, Math.max(4, position - 2)))
          }
          if (e.key === "ArrowRight") {
            onPositionChange(Math.min(96, Math.max(4, position + 2)))
          }
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

      <div
        className="absolute inset-x-0 bottom-0 z-30 flex items-end justify-center gap-3 px-4 pb-3 pt-8"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <label className="sr-only" htmlFor={sliderId}>
          Ползунок сравнения до и после
        </label>
        <input
          id={sliderId}
          type="range"
          min={4}
          max={96}
          value={position}
          onChange={(e) => {
            onInteract()
            onPositionChange(Number(e.target.value))
          }}
          onPointerDown={(e) => {
            e.stopPropagation()
            onInteract()
          }}
          className="h-2 w-[min(70%,14rem)] cursor-pointer appearance-none rounded-full bg-white/15 accent-emerald"
        />
      </div>

      {showMaximize && onMaximize ? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onMaximize()
          }}
          className={cn(
            "absolute bottom-3 right-3 z-40 inline-flex items-center gap-1.5 rounded-lg",
            "border border-white/15 bg-loft/80 px-2.5 py-1.5",
            "font-heading text-[11px] font-medium text-foreground backdrop-blur-md",
            "shadow-[0_8px_24px_rgba(0,0,0,0.35)] transition-colors hover:bg-loft hover:border-emerald/40"
          )}
          aria-label="Раскрыть на весь экран"
        >
          <Maximize2 className="size-3.5 text-emerald" aria-hidden />
          <span className="hidden sm:inline">Раскрыть на весь экран</span>
        </button>
      ) : null}
    </div>
  )
}

function BeforeAfterSlider() {
  const baseId = useId()
  const [activeIndex, setActiveIndex] = useState(0)
  const [position, setPosition] = useState(52)
  const [fullscreenOpen, setFullscreenOpen] = useState(false)
  const portalReady = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false
  )
  const interacted = useRef(false)
  const example = PRODUCT_EXAMPLES[activeIndex]

  const markInteracted = useCallback(() => {
    interacted.current = true
  }, [])

  const goToExample = useCallback((index: number) => {
    setActiveIndex(index)
    setPosition(52)
    interacted.current = false
  }, [])

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
  }, [activeIndex])

  useEffect(() => {
    if (fullscreenOpen) return
    const id = window.setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % PRODUCT_EXAMPLES.length)
      setPosition(52)
      interacted.current = false
    }, AUTO_ROTATE_MS)
    return () => window.clearInterval(id)
  }, [fullscreenOpen, activeIndex])

  useEffect(() => {
    if (!fullscreenOpen) return
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreenOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => {
      document.body.style.overflow = prevOverflow
      window.removeEventListener("keydown", onKey)
    }
  }, [fullscreenOpen])

  const fullscreenOverlay =
    portalReady && typeof document !== "undefined"
      ? createPortal(
          <AnimatePresence>
            {fullscreenOpen ? (
              <motion.div
                key="compare-fullscreen"
                className="fixed inset-0 z-[90] flex flex-col items-center justify-center p-3 sm:p-6"
                role="dialog"
                aria-modal="true"
                aria-label={`Сравнение до и после — ${example.label}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.22 }}
              >
                <button
                  type="button"
                  className="absolute inset-0 bg-loft/90 backdrop-blur-md"
                  aria-label="Закрыть полноэкранный режим"
                  onClick={() => setFullscreenOpen(false)}
                />

                <motion.div
                  className="relative z-10 flex h-full max-h-[100svh] w-full max-w-3xl flex-col items-center justify-center gap-3"
                  initial={{ opacity: 0, scale: 0.96, y: 12 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.98, y: 8 }}
                  transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                >
                  <div className="flex w-full items-center justify-between gap-3 px-1">
                    <p className="font-heading text-sm font-medium text-foreground">
                      {example.label}
                      <span className="ml-2 text-text-muted">· до / после</span>
                    </p>
                    <button
                      type="button"
                      onClick={() => setFullscreenOpen(false)}
                      className="inline-flex size-10 items-center justify-center rounded-full border border-white/15 bg-loft/80 text-foreground backdrop-blur-md transition-colors hover:border-emerald/40 hover:bg-loft"
                      aria-label="Закрыть"
                    >
                      <X className="size-4" />
                    </button>
                  </div>

                  <CompareFrame
                    key={`fs-${example.id}`}
                    example={example}
                    position={position}
                    onPositionChange={setPosition}
                    onInteract={markInteracted}
                    sliderId={`${baseId}-compare-fs`}
                    priority
                    className="aspect-[3/4] h-auto max-h-[min(82svh,52rem)] w-full max-w-xl"
                  />

                  <div className="flex items-center gap-2 pb-1">
                    {PRODUCT_EXAMPLES.map((item, index) => {
                      const active = index === activeIndex
                      return (
                        <button
                          key={`fs-${item.id}`}
                          type="button"
                          aria-label={item.label}
                          title={item.label}
                          onClick={() => goToExample(index)}
                          className={cn(
                            "h-2 rounded-full transition-all duration-300",
                            active
                              ? "w-6 bg-emerald"
                              : "w-2 bg-white/25 hover:bg-white/45"
                          )}
                        />
                      )
                    })}
                  </div>
                </motion.div>
              </motion.div>
            ) : null}
          </AnimatePresence>,
          document.body
        )
      : null

  return (
    <div className="flex w-full max-w-md flex-col items-center gap-3">
      <div className="relative w-full">
        <CompareFrame
          key={example.id}
          example={example}
          position={position}
          onPositionChange={setPosition}
          onInteract={markInteracted}
          sliderId={`${baseId}-compare`}
          showMaximize
          onMaximize={() => setFullscreenOpen(true)}
          priority={activeIndex === 0}
          className="aspect-[4/5] w-full"
        />
      </div>

      <div
        className="flex items-center gap-2"
        role="tablist"
        aria-label="Примеры товаров"
      >
        {PRODUCT_EXAMPLES.map((item, index) => {
          const active = index === activeIndex
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-label={item.label}
              title={item.label}
              onClick={() => goToExample(index)}
              className={cn(
                "h-2 rounded-full transition-all duration-300",
                active
                  ? "w-6 bg-emerald shadow-[0_0_12px_rgba(16,185,129,0.45)]"
                  : "w-2 bg-white/25 hover:bg-white/45"
              )}
            />
          )
        })}
      </div>

      {fullscreenOverlay}
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
    <section className="relative isolate min-h-[100svh] overflow-hidden pt-28 pb-2 sm:pt-32 sm:pb-3">
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden>
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_60%_at_50%_-10%,rgba(16,185,129,0.12),transparent_55%)]" />
        <TropicalLeaves />
      </div>

      <div className="mx-auto max-w-6xl px-5">
        <div className="section-glass relative overflow-hidden rounded-3xl px-6 py-10 sm:px-10 sm:py-14 lg:px-12">
          <div className="grid items-center gap-12 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
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
        </div>
      </div>

      <AnimatePresence>
        {demoOpen ? <Modal360 onClose={() => setDemoOpen(false)} /> : null}
      </AnimatePresence>
    </section>
  )
}

export { HeroSection }
