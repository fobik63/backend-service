"use client"

import {
  Crown,
  Footprints,
  Grip,
  Leaf,
  Play,
  Star,
  Wind,
  X,
} from "lucide-react"
import { useEffect, useState } from "react"
import { motion } from "framer-motion"

import dynamic from "next/dynamic"
import { useRouter } from "next/navigation"

import { ErrorBoundary } from "@/components/error-boundary"
import { GlassButton } from "@/components/ui/glass-button"
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

const DEMO_360_CALLOUTS = [
  {
    id: "light",
    Icon: Leaf,
    label: "Лёгкие для максимального комфорта",
    className: "left-3 top-[14%] max-w-[9.5rem] sm:left-5 sm:top-[12%]",
  },
  {
    id: "mesh",
    Icon: Wind,
    label: "Дышащий сетчатый материал",
    className: "right-3 top-[16%] max-w-[9rem] sm:right-5 sm:top-[14%]",
  },
  {
    id: "sole",
    Icon: Footprints,
    label: "Эргономичная подошва снижает нагрузку",
    className: "left-3 bottom-[28%] max-w-[10rem] sm:left-5 sm:bottom-[26%]",
  },
  {
    id: "grip",
    Icon: Grip,
    label: "Надёжное сцепление с поверхностью",
    className: "right-3 bottom-[30%] max-w-[9.5rem] sm:right-5 sm:bottom-[28%]",
  },
] as const

type Modal360Props = {
  onClose: () => void
}

function Modal360({ onClose }: Modal360Props) {
  const router = useRouter()
  const [overlaysVisible, setOverlaysVisible] = useState(true)
  const [interacting, setInteracting] = useState(false)

  useEffect(() => {
    if (interacting) return
    const id = window.setTimeout(() => setOverlaysVisible(true), 420)
    return () => window.clearTimeout(id)
  }, [interacting])

  const beginInteract = () => {
    setInteracting(true)
    setOverlaysVisible(false)
  }

  const endInteract = () => {
    setInteracting(false)
  }

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
        className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl bg-loft-surface copper-border shadow-[0_32px_100px_rgba(0,0,0,0.55)]"
      >
        <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
          <div>
            <p className="font-heading text-xs tracking-[0.16em] text-copper uppercase">
              Demo 360°
            </p>
            <p className="text-sm text-muted-foreground">
              Полноценная 3D-модель — вращайте во всех плоскостях и приближайте
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
          className="relative aspect-[4/5] select-none overflow-hidden sm:aspect-[4/3.4]"
          onPointerDown={beginInteract}
          onPointerUp={endInteract}
          onPointerLeave={endInteract}
          onWheel={() => {
            beginInteract()
            window.setTimeout(() => endInteract(), 600)
          }}
        >
          <ErrorBoundary
            title="3D-демо недоступно"
            description="Не удалось инициализировать WebGL. Закройте окно и попробуйте снова."
            className="absolute inset-0 rounded-none border-0"
          >
            <Sneaker3DViewer
              variant="modal"
              className="absolute inset-0"
              autoRotate={!interacting}
              enableZoom
              showHint={false}
            />
          </ErrorBoundary>

          <div
            className={cn(
              "pointer-events-none absolute inset-0 z-20 transition-opacity duration-500 ease-out",
              overlaysVisible ? "opacity-100" : "opacity-0"
            )}
          >
            <div className="absolute left-3 top-3 flex flex-col gap-1.5 sm:left-4 sm:top-4">
              <span className="inline-flex w-fit items-center gap-1 rounded-md bg-gradient-to-r from-copper to-[#8a5230] px-2 py-1 font-heading text-[10px] font-semibold text-loft shadow-[0_8px_20px_rgba(0,0,0,0.35)]">
                <Star className="size-3 fill-current" aria-hidden />
                Хит продаж
              </span>
              <span className="w-fit rounded-md bg-[#1b3e2b] px-2 py-1 font-heading text-[10px] font-semibold text-emerald shadow-[0_8px_20px_rgba(0,0,0,0.35)]">
                −35%
              </span>
            </div>

            <div className="absolute right-3 top-3 text-right sm:right-4 sm:top-4">
              <p className="font-heading text-lg font-semibold tracking-[0.08em] text-white sm:text-xl">
                NEXORA
              </p>
              <p className="font-heading text-[9px] tracking-[0.22em] text-white/55 uppercase">
                Premium Shoes
              </p>
            </div>

            {DEMO_360_CALLOUTS.map(({ id, Icon, label, className }) => (
              <div
                key={id}
                className={cn(
                  "absolute flex items-start gap-1.5 rounded-md border border-white/12 bg-loft/70 px-2 py-1.5 backdrop-blur-md",
                  "shadow-[0_8px_20px_rgba(0,0,0,0.35)]",
                  className
                )}
              >
                <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald/20 text-emerald">
                  <Icon className="size-3" aria-hidden />
                </span>
                <p className="font-heading text-[10px] leading-snug text-foreground">
                  {label}
                </p>
              </div>
            ))}

            <div className="absolute inset-x-0 bottom-0 border-t border-white/8 bg-loft/55 px-4 pb-11 pt-3 backdrop-blur-sm sm:px-5">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="font-heading text-xl font-semibold text-foreground sm:text-2xl">
                    4 990 ₽{" "}
                    <span className="text-xs font-normal text-text-muted line-through">
                      7 690 ₽
                    </span>
                  </p>
                  <div className="mt-1.5 inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-loft/60 px-2 py-1">
                    <Crown className="size-3 text-copper" aria-hidden />
                    <span className="font-heading text-[9px] leading-tight text-text-muted">
                      Премиальное качество для активной жизни
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <p className="mb-1 font-heading text-[9px] tracking-wide text-text-muted uppercase">
                    Размеры:
                  </p>
                  <div className="flex gap-1">
                    {[40, 41, 42, 43, 44].map((size) => (
                      <span
                        key={size}
                        className={cn(
                          "flex size-6 items-center justify-center rounded-sm font-heading text-[10px]",
                          size === 42
                            ? "bg-copper text-loft"
                            : "border border-white/15 bg-white/5 text-foreground/80"
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

          <div className="pointer-events-none absolute bottom-3 left-1/2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-full border border-white/10 bg-loft/75 px-3 py-1 font-heading text-[11px] text-emerald backdrop-blur-md">
            <Play className="size-3" />
            тяните · крутите · pinch/scroll zoom
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-white/8 px-4 py-3">
          <GlassButton
            size="sm"
            onClick={() => {
              onClose()
              router.push("/editor")
            }}
          >
            Открыть в редакторе
          </GlassButton>
        </div>
      </motion.div>
    </div>
  )
}

export { Modal360 }
