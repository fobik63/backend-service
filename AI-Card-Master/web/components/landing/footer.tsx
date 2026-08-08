import { Send } from "lucide-react"
import Link from "next/link"

const DOC_LINKS = [
  { href: "/legal/terms", label: "Оферта" },
  { href: "/legal/privacy", label: "Политика конфиденциальности" },
] as const

const PRODUCT_LINKS = [
  { href: "#features", label: "Возможности" },
  { href: "#testimonials", label: "Отзывы" },
  { href: "#pricing", label: "Цены" },
  { href: "#faq", label: "FAQ" },
] as const

const TELEGRAM_SUPPORT_URL = "https://t.me/cardai_support"

function Footer() {
  return (
    <footer className="relative isolate border-t border-white/8 bg-loft">
      <div
        className="pointer-events-none absolute inset-0 -z-10"
        aria-hidden
      >
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_50%_40%_at_50%_0%,rgba(16,185,129,0.06),transparent_55%)]" />
      </div>

      <div className="mx-auto max-w-6xl px-5 pt-14 pb-8">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4 lg:gap-8">
          {/* Brand */}
          <div className="sm:col-span-2 lg:col-span-1">
            <Link href="/landing" className="inline-flex items-center gap-2">
              <span className="font-heading text-lg font-semibold tracking-tight text-foreground">
                CARD AI
                <span
                  aria-hidden
                  className="ml-0.5 inline-block size-1.5 translate-y-[-0.35em] rounded-full bg-emerald shadow-[0_0_10px_rgba(16,185,129,0.7)]"
                />
              </span>
            </Link>
            <p className="mt-3 max-w-xs text-sm leading-relaxed text-text-muted">
              AI-студия карточек для Ozon и Wildberries
            </p>
          </div>

          {/* Product */}
          <div>
            <h3 className="font-heading text-xs font-semibold tracking-[0.14em] text-foreground uppercase">
              Продукт
            </h3>
            <ul className="mt-4 flex flex-col gap-2.5">
              {PRODUCT_LINKS.map((link) => (
                <li key={link.href}>
                  <a
                    href={link.href}
                    className="text-sm text-text-muted transition-colors hover:text-foreground"
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {/* Documents */}
          <div>
            <h3 className="font-heading text-xs font-semibold tracking-[0.14em] text-foreground uppercase">
              Документы
            </h3>
            <ul className="mt-4 flex flex-col gap-2.5">
              {DOC_LINKS.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="text-sm text-text-muted transition-colors hover:text-foreground"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Support */}
          <div>
            <h3 className="font-heading text-xs font-semibold tracking-[0.14em] text-foreground uppercase">
              Поддержка
            </h3>
            <ul className="mt-4 flex flex-col gap-2.5">
              <li>
                <a
                  href={TELEGRAM_SUPPORT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 text-sm text-text-muted transition-colors hover:text-emerald"
                >
                  <Send className="size-3.5 shrink-0" aria-hidden />
                  Telegram
                </a>
              </li>
              <li>
                <a
                  href={TELEGRAM_SUPPORT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-text-muted transition-colors hover:text-foreground"
                >
                  @cardai_support
                </a>
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-12 flex flex-col gap-4 border-t border-white/8 pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-text-muted">
            © 2026 CARD AI Inc.
          </p>

          <div
            className="inline-flex w-fit items-center gap-2 rounded-full border border-emerald/25 bg-emerald/10 px-3 py-1.5"
            role="status"
            aria-label="Статус серверов: All Systems Operational"
          >
            <span
              className="relative flex size-2"
              aria-hidden
            >
              <span className="absolute inset-0 animate-ping rounded-full bg-emerald opacity-40" />
              <span className="relative size-2 rounded-full bg-emerald" />
            </span>
            <span className="font-heading text-xs font-medium tracking-wide text-emerald">
              All Systems Operational
            </span>
          </div>
        </div>
      </div>
    </footer>
  )
}

export { Footer }
