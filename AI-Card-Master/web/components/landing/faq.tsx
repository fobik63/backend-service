"use client"

import { useEffect, useRef } from "react"
import { motion, useInView } from "framer-motion"

import { SectionHeader } from "@/components/ui/section-header"

const FAQ_ITEMS = [
  {
    q: "Нужна ли студия или дизайнер?",
    a: "Нет. Загрузите фото товара — CARD AI сделает чистую вырезку, студийный свет и инфографику под Ozon и Wildberries.",
  },
  {
    q: "Сколько времени занимает карточка?",
    a: "Базовый вариант обычно готов за несколько минут: загрузка → обработка → правки в редакторе → экспорт.",
  },
  {
    q: "Можно ли править результат вручную?",
    a: "Да. В редакторе доступны текст, плашки, свет, фон и композиция — всё под ваш бренд и требования маркетплейса.",
  },
  {
    q: "Как связаться с поддержкой?",
    a: "Напишите в Telegram @cardai_support или на email support@cardai.pro — ответим по доступу, биллингу и работе редактора.",
  },
] as const

function FaqSection() {
  const sectionRef = useRef<HTMLElement>(null)
  const inView = useInView(sectionRef, { once: true, amount: 0.2 })

  useEffect(() => {
    if (typeof window === "undefined") return
    if (window.location.hash !== "#faq") return
    const t = window.setTimeout(() => {
      document.getElementById("faq")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      })
    }, 80)
    return () => window.clearTimeout(t)
  }, [])

  return (
    <section
      id="faq"
      ref={sectionRef}
      className="relative isolate scroll-mt-28 px-5 py-16 sm:py-24"
      aria-labelledby="faq-heading"
    >
      <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden>
        <div className="absolute left-1/2 top-0 size-96 -translate-x-1/2 rounded-full bg-[#059669]/10 blur-[120px]" />
      </div>

      <div className="mx-auto max-w-3xl">
        <div className="section-glass rounded-3xl px-5 py-10 sm:px-8 sm:py-12">
          <SectionHeader
            align="center"
            as="h2"
            title={<span id="faq-heading">FAQ</span>}
            subtitle="Короткие ответы на частые вопросы о CARD AI"
            className="mb-10 sm:mb-12"
          />

          <ul className="flex flex-col gap-3">
            {FAQ_ITEMS.map((item, i) => (
              <motion.li
                key={item.q}
                initial={{ opacity: 0, y: 16 }}
                animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }}
                transition={{
                  duration: 0.4,
                  delay: 0.06 * i,
                  ease: [0.22, 1, 0.36, 1],
                }}
                className="rounded-2xl border border-white/5 bg-[#14171d]/60 px-5 py-4 backdrop-blur-xl copper-border"
              >
                <h3 className="font-heading text-base font-semibold tracking-tight text-foreground">
                  {item.q}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-text-muted">
                  {item.a}
                </p>
              </motion.li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

export { FaqSection }
