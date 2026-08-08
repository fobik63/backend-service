"use client"

import { useEffect, useRef } from "react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"

export type TelegramLoginPayload = {
  id: number
  first_name: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date: number
  hash: string
}

type TelegramLoginButtonProps = {
  onAuth: (user: TelegramLoginPayload) => void
  disabled?: boolean
  className?: string
  botUsername?: string
}

declare global {
  interface Window {
    onTelegramAuth?: (user: TelegramLoginPayload) => void
  }
}

/**
 * Official Telegram Login Widget.
 * Requires NEXT_PUBLIC_TELEGRAM_BOT_USERNAME and matching bot domain in BotFather.
 */
function TelegramLoginButton({
  onAuth,
  disabled = false,
  className,
  botUsername,
}: TelegramLoginButtonProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bot =
    botUsername?.replace(/^@/, "") ||
    process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME?.replace(/^@/, "") ||
    ""

  useEffect(() => {
    if (!bot || disabled) return
    const el = containerRef.current
    if (!el) return

    window.onTelegramAuth = (user) => {
      onAuth(user)
    }

    el.innerHTML = ""
    const script = document.createElement("script")
    script.src = "https://telegram.org/js/telegram-widget.js?22"
    script.async = true
    script.setAttribute("data-telegram-login", bot)
    script.setAttribute("data-size", "large")
    script.setAttribute("data-radius", "8")
    script.setAttribute("data-request-access", "write")
    script.setAttribute("data-onauth", "onTelegramAuth(user)")
    script.setAttribute("data-userpic", "false")
    el.appendChild(script)

    return () => {
      delete window.onTelegramAuth
      el.innerHTML = ""
    }
  }, [bot, disabled, onAuth])

  if (!bot) {
    return (
      <button
        type="button"
        disabled={disabled}
        className={cn(
          "flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-white/10 bg-[#229ED9]/10 text-sm text-foreground hover:bg-[#229ED9]/20 disabled:opacity-50",
          className
        )}
        onClick={() =>
          toast.message("Telegram-вход", {
            description:
              "Укажите NEXT_PUBLIC_TELEGRAM_BOT_USERNAME и токен бота на бэкенде.",
          })
        }
      >
        Вход через Telegram
      </button>
    )
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        "flex min-h-10 w-full items-center justify-center overflow-hidden rounded-lg",
        disabled && "pointer-events-none opacity-50",
        className
      )}
      aria-label="Вход через Telegram"
    />
  )
}

export { TelegramLoginButton }
