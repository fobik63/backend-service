"use client"

import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import { useState } from "react"

import { AuthForm } from "@/components/auth/auth-form"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { APP_NAME } from "@/lib/constants/api"
import type { AuthMode } from "@/lib/validators/auth"

type AuthModalProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  initialMode?: AuthMode
}

function AuthModal({
  open,
  onOpenChange,
  initialMode = "login",
}: AuthModalProps) {
  const [mode, setMode] = useState<AuthMode>(initialMode)

  const title =
    mode === "register"
      ? "Регистрация"
      : mode === "otp"
        ? "Вход по коду"
        : "Вход"

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) setMode(initialMode)
      }}
    >
      <DialogContent
        showCloseButton
        className="max-w-[calc(100%-1.5rem)] border-0 bg-transparent p-0 shadow-none ring-0 sm:max-w-md"
      >
        <DialogHeader className="sr-only">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Авторизация в {APP_NAME}: email, Telegram или One-Time Code
          </DialogDescription>
        </DialogHeader>

        <div className="mb-2 flex items-center justify-between px-1">
          <Link
            href="/landing"
            onClick={() => onOpenChange(false)}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            Назад на главную
          </Link>
        </div>

        <AuthForm
          key={open ? `open-${initialMode}` : "closed"}
          compact
          hideHomeLink
          initialMode={initialMode}
          onModeChange={setMode}
          onSuccess={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  )
}

export { AuthModal }
export type { AuthModalProps }
