"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { KeyRound, Loader2 } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"

import { TelegramIcon } from "@/components/auth/telegram-icon"
import { Button } from "@/components/ui/button"
import { GlassButton } from "@/components/ui/glass-button"
import { GlassCard } from "@/components/ui/glass-card"
import { Input } from "@/components/ui/input"
import { apiClient } from "@/lib/api"
import { APP_NAME } from "@/lib/constants/api"
import { useAuthStore } from "@/lib/store"
import { cn } from "@/lib/utils"
import {
  authCredentialsSchema,
  otpAuthSchema,
  type AuthCredentialsValues,
  type AuthMode,
  type OtpAuthValues,
} from "@/lib/validators/auth"

type AuthSessionResponse = {
  user: { id: string; email: string }
  tokens: { access_token: string; refresh_token: string }
}

type AuthFormProps = {
  initialMode?: AuthMode
  /** Compact title for modal context */
  compact?: boolean
  className?: string
  onSuccess?: () => void
  onModeChange?: (mode: AuthMode) => void
}

function persistSession(tokens: AuthSessionResponse["tokens"]) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem("access_token", tokens.access_token)
    window.localStorage.setItem("refresh_token", tokens.refresh_token)
  }
  useAuthStore.getState().setAccessToken(tokens.access_token)
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <p className="mt-1.5 text-xs text-destructive">{message}</p>
}

function AuthForm({
  initialMode = "login",
  compact = false,
  className,
  onSuccess,
  onModeChange,
}: AuthFormProps) {
  const router = useRouter()
  const [mode, setMode] = useState<AuthMode>(initialMode)
  const [isPending, startTransition] = useTransition()
  const [formError, setFormError] = useState<string | null>(null)

  const credentialsForm = useForm<AuthCredentialsValues>({
    resolver: zodResolver(authCredentialsSchema),
    defaultValues: { email: "", password: "" },
    mode: "onSubmit",
  })

  const otpForm = useForm<OtpAuthValues>({
    resolver: zodResolver(otpAuthSchema),
    defaultValues: { email: "", code: "" },
    mode: "onSubmit",
  })

  const switchMode = (next: AuthMode) => {
    setFormError(null)
    setMode(next)
    onModeChange?.(next)
  }

  const finishAuth = (message: string) => {
    toast.success(message)
    onSuccess?.()
    startTransition(() => {
      router.push("/dashboard")
      router.refresh()
    })
  }

  const onCredentialsSubmit = credentialsForm.handleSubmit(async (values) => {
    setFormError(null)
    const endpoint = mode === "register" ? "/auth/register" : "/auth/login"
    try {
      const { data } = await apiClient.post<AuthSessionResponse>(
        endpoint,
        values
      )
      persistSession(data.tokens)
      finishAuth(
        mode === "register" ? "Аккаунт создан" : "Вы вошли в аккаунт"
      )
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        (mode === "register"
          ? "Не удалось зарегистрироваться"
          : "Неверный email или пароль")
      setFormError(typeof detail === "string" ? detail : "Ошибка авторизации")
    }
  })

  const onOtpSubmit = otpForm.handleSubmit(async (values) => {
    setFormError(null)
    try {
      const { data } = await apiClient.post<AuthSessionResponse>(
        "/auth/otp/verify",
        values
      )
      persistSession(data.tokens)
      finishAuth("Вы вошли по коду")
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Неверный или просроченный код"
      setFormError(typeof detail === "string" ? detail : "Ошибка входа по коду")
    }
  })

  const handleTelegram = () => {
    setFormError(null)
    const bot = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME
    if (bot) {
      window.open(`https://t.me/${bot}?start=auth`, "_blank", "noopener,noreferrer")
      return
    }
    toast.message("Telegram-вход", {
      description: "Скоро будет доступен. Пока войдите по email.",
    })
  }

  const busy =
    isPending ||
    credentialsForm.formState.isSubmitting ||
    otpForm.formState.isSubmitting

  const title =
    mode === "register"
      ? "Регистрация"
      : mode === "otp"
        ? "Вход по коду"
        : "Вход"

  const subtitle =
    mode === "register"
      ? "Создайте аккаунт и соберите первую карточку"
      : mode === "otp"
        ? "Введите email и одноразовый код из письма"
        : `Добро пожаловать в ${APP_NAME}`

  return (
    <GlassCard
      hoverLift={false}
      padding="lg"
      className={cn("w-full border-white/10 copper-border", className)}
    >
      <div className={cn("mb-6", compact ? "space-y-1" : "space-y-2")}>
        <p className="font-heading text-xs font-medium tracking-[0.18em] text-copper uppercase">
          {APP_NAME}
        </p>
        <h1
          className={cn(
            "font-heading font-semibold tracking-tight text-foreground",
            compact ? "text-xl" : "text-2xl"
          )}
        >
          {title}
        </h1>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>

      {mode === "otp" ? (
        <form onSubmit={onOtpSubmit} className="space-y-4" noValidate>
          <div>
            <label
              htmlFor="otp-email"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              Email
            </label>
            <Input
              id="otp-email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={!!otpForm.formState.errors.email}
              className="h-10 bg-loft-surface/60"
              {...otpForm.register("email")}
            />
            <FieldError message={otpForm.formState.errors.email?.message} />
          </div>

          <div>
            <label
              htmlFor="otp-code"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              One-Time Code
            </label>
            <Input
              id="otp-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="123456"
              aria-invalid={!!otpForm.formState.errors.code}
              className="h-10 bg-loft-surface/60 tracking-[0.2em]"
              {...otpForm.register("code")}
            />
            <FieldError message={otpForm.formState.errors.code?.message} />
          </div>

          {formError ? (
            <p className="text-sm text-destructive" role="alert">
              {formError}
            </p>
          ) : null}

          <GlassButton type="submit" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Подтвердить код
          </GlassButton>

          <Button
            type="button"
            variant="ghost"
            className="w-full"
            disabled={busy}
            onClick={() => switchMode("login")}
          >
            Назад к входу по паролю
          </Button>
        </form>
      ) : (
        <form onSubmit={onCredentialsSubmit} className="space-y-4" noValidate>
          <div>
            <label
              htmlFor="auth-email"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              Email
            </label>
            <Input
              id="auth-email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={!!credentialsForm.formState.errors.email}
              className="h-10 bg-loft-surface/60"
              {...credentialsForm.register("email")}
            />
            <FieldError
              message={credentialsForm.formState.errors.email?.message}
            />
          </div>

          <div>
            <label
              htmlFor="auth-password"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              Пароль
            </label>
            <Input
              id="auth-password"
              type="password"
              autoComplete={
                mode === "register" ? "new-password" : "current-password"
              }
              placeholder="••••••••"
              aria-invalid={!!credentialsForm.formState.errors.password}
              className="h-10 bg-loft-surface/60"
              {...credentialsForm.register("password")}
            />
            <FieldError
              message={credentialsForm.formState.errors.password?.message}
            />
          </div>

          {formError ? (
            <p className="text-sm text-destructive" role="alert">
              {formError}
            </p>
          ) : null}

          <div className="flex flex-col gap-2.5 pt-1">
            {mode === "login" ? (
              <>
                <GlassButton type="submit" className="w-full" disabled={busy}>
                  {busy ? <Loader2 className="size-4 animate-spin" /> : null}
                  Войти
                </GlassButton>
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 w-full border-white/10 bg-transparent"
                  disabled={busy}
                  onClick={() => switchMode("register")}
                >
                  Зарегистрироваться
                </Button>
              </>
            ) : (
              <>
                <GlassButton type="submit" className="w-full" disabled={busy}>
                  {busy ? <Loader2 className="size-4 animate-spin" /> : null}
                  Зарегистрироваться
                </GlassButton>
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 w-full border-white/10 bg-transparent"
                  disabled={busy}
                  onClick={() => switchMode("login")}
                >
                  Войти
                </Button>
              </>
            )}
          </div>
        </form>
      )}

      {mode !== "otp" ? (
        <>
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center" aria-hidden>
              <div className="w-full border-t border-white/10" />
            </div>
            <div className="relative flex justify-center text-xs">
              <span className="bg-[rgba(22,24,30,0.95)] px-3 text-muted-foreground">
                быстрый вход
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            <Button
              type="button"
              variant="outline"
              className="h-10 w-full gap-2 border-white/10 bg-[#229ED9]/10 text-foreground hover:bg-[#229ED9]/20"
              disabled={busy}
              onClick={handleTelegram}
            >
              <TelegramIcon className="size-4 text-[#229ED9]" />
              Вход через Telegram
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-10 w-full gap-2 border-white/10 bg-transparent"
              disabled={busy}
              onClick={() => switchMode("otp")}
            >
              <KeyRound className="size-4 text-emerald" />
              Вход по One-Time Code
            </Button>
          </div>
        </>
      ) : null}

      {!compact && mode === "login" ? (
        <p className="mt-6 text-center text-xs text-muted-foreground">
          Нет аккаунта?{" "}
          <Link
            href="/register"
            className="text-emerald underline-offset-4 hover:underline"
            onClick={(e) => {
              e.preventDefault()
              switchMode("register")
            }}
          >
            Зарегистрироваться
          </Link>
        </p>
      ) : null}
    </GlassCard>
  )
}

export { AuthForm }
export type { AuthFormProps }
