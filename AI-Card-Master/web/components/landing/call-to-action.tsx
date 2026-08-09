"use client"

import { Sparkles } from "lucide-react"
import { useRouter } from "next/navigation"
import { useRef } from "react"
import { motion, useInView } from "framer-motion"

import { GlassButton } from "@/components/ui/glass-button"

function CallToActionSection() {
  const router = useRouter()
  const sectionRef = useRef<HTMLElement>(null)
  const inView = useInView(sectionRef, { once: true, amount: 0.35 })

  return (
    <section
      id="cta"
      ref={sectionRef}
      className="relative isolate scroll-mt-24 px-5 py-16 md:py-24"
    >
      <div className="relative mx-auto max-w-6xl overflow-hidden rounded-2xl section-glass">
        <motion.div
          className="relative flex flex-col items-center gap-5 px-6 py-12 text-center sm:px-10 sm:py-14"
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        >
          <p className="font-heading text-sm font-medium tracking-[0.18em] text-muted-foreground uppercase">
            Старт за минуту
          </p>
          <h2 className="max-w-2xl font-heading text-2xl font-semibold tracking-tight text-foreground sm:text-3xl lg:text-4xl">
            Готовы собрать первую продающую карточку?
          </h2>
          <p className="max-w-lg text-sm leading-relaxed text-text-muted sm:text-base">
            Без студии, дизайнеров и подписки на старте — загрузите фото и
            получите карточку для Ozon или WB
          </p>

          <motion.div
            className="mt-3"
            initial={{ opacity: 0, y: 8 }}
            animate={
              inView
                ? { opacity: 1, y: 0 }
                : { opacity: 0, y: 8 }
            }
            transition={{ delay: 0.12, duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          >
            <GlassButton
              size="lg"
              icon={Sparkles}
              onClick={() => router.push("/editor")}
            >
              Создать карточку
            </GlassButton>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}

export { CallToActionSection }
