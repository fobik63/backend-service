"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { ArrowLeft, KeyRound, Loader2 } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useState, useTransition } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"

import {
  TelegramLoginButton,
  type TelegramLoginPayload,
} from "@/components/auth/telegram-login-button"
import { Button } from "@/components/ui/button"
import { GlassButton } from "@/components/ui/glass-button"
import { GlassCard } from "@/components/ui/glass-card"
import { Input } from "@/components/ui/input"
import {
  loginWithPassword,
  loginWithTelegram,
  registerWithPassword,
  sendOtp,
  verifyOtp,
} from "@/lib/api/auth"
import {
  getApiErrorMessage,
  isNetworkError,
  NETWORK_ERROR_MESSAGES,
} from "@/lib/api/errors"
import { APP_NAME, DEFAULT_API_BASE_URL } from "@/lib/constants/api"
import {
  IS_MOCK,
  MOCK_AUTH_TOKENS,
  MOCK_AUTH_USER,
} from "@/lib/constants/mock"
import { useAuthStore } from "@/lib/store"
import { cn } from "@/lib/utils"
import {
  authCredentialsSchema,
  otpCodeSchema,
  otpEmailSchema,
  type AuthCredentialsValues,
  type AuthMode,
  type OtpCodeValues,
  type OtpEmailValues,
} from "@/lib/validators/auth"

type AuthFormProps = {
  initialMode?: AuthMode
  /** Compact title for modal context */
  compact?: boolean
  className?: string
  onSuccess?: () => void
  onModeChange?: (mode: AuthMode) => void
  /** Hide built-in home link when parent already shows one */
  hideHomeLink?: boolean
  /** When true, start on OTP email step (modal default). */
  otpFirst?: boolean
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
  hideHomeLink = false,
  otpFirst = false,
}: AuthFormProps) {
  const router = useRouter()
  const setSession = useAuthStore((s) => s.setSession)
  const [mode, setMode] = useState<AuthMode>(
    otpFirst ? "otp" : initialMode,
  )
  const [otpStep, setOtpStep] = useState<1 | 2>(1)
  const [otpEmail, setOtpEmail] = useState("")
  const [resendIn, setResendIn] = useState(0)
  const [isPending, startTransition] = useTransition()
  const [formError, setFormError] = useState<string | null>(null)
  const [sendingOtp, setSendingOtp] = useState(false)

  const credentialsForm = useForm<AuthCredentialsValues>({
    resolver: zodResolver(authCredentialsSchema),
    defaultValues: { email: "", password: "" },
    mode: "onSubmit",
  })

  const otpEmailForm = useForm<OtpEmailValues>({
    resolver: zodResolver(otpEmailSchema),
    defaultValues: { email: "" },
    mode: "onSubmit",
  })

  const otpCodeForm = useForm<OtpCodeValues>({
    resolver: zodResolver(otpCodeSchema),
    defaultValues: { code: "" },
    mode: "onSubmit",
  })

  useEffect(() => {
    if (resendIn <= 0) return
    const id = window.setInterval(() => {
      setResendIn((s) => Math.max(0, s - 1))
    }, 1000)
    return () => window.clearInterval(id)
  }, [resendIn])

  useEffect(() => {
    if (!IS_MOCK) return
    setSession(MOCK_AUTH_TOKENS, MOCK_AUTH_USER)
    onSuccess?.()
    startTransition(() => {
      // Stay on current page (modal); dedicated auth pages return home.
      if (!compact) router.replace("/")
      router.refresh()
    })
    // Auto-login once on mount when mock mode is enabled.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional one-shot bypass
  }, [])

  const switchMode = (next: AuthMode) => {
    setFormError(null)
    setMode(next)
    setOtpStep(1)
    setResendIn(0)
    onModeChange?.(next)
  }

  const finishAuth = (message: string) => {
    toast.success(message)
    onSuccess?.()
    startTransition(() => {
      // Modal (compact): remain on current URL. Auth pages: go to landing.
      if (!compact) router.replace("/")
      router.refresh()
    })
  }

  const mapAuthError = (err: unknown, fallback: string) => {
    if (isNetworkError(err)) {
      return `${NETWORK_ERROR_MESSAGES.offline}. Запустите API на ${DEFAULT_API_BASE_URL}`
    }
    return getApiErrorMessage(err, fallback)
  }

  const onCredentialsSubmit = credentialsForm.handleSubmit(async (values) => {
    setFormError(null)
    try {
      const data =
        mode === "register"
          ? await registerWithPassword(values.email, values.password)
          : await loginWithPassword(values.email, values.password)
      setSession(data.tokens, data.user)
      finishAuth(
        mode === "register" ? "Аккаунт создан" : "Вы вошли в аккаунт",
      )
    } catch (err: unknown) {
      setFormError(
        mapAuthError(
          err,
          mode === "register"
            ? "Не удалось зарегистрироваться"
            : "Неверный email или пароль",
        ),
      )
    }
  })

  const requestOtp = async (email: string) => {
    setSendingOtp(true)
    setFormError(null)
    try {
      const data = await sendOtp(email)
      setOtpEmail(email)
      setOtpStep(2)
      setResendIn(60)
      otpCodeForm.reset({ code: "" })
      toast.success(data.message || "Код отправлен на email")
    } catch (err: unknown) {
      setFormError(mapAuthError(err, "Не удалось отправить код"))
    } finally {
      setSendingOtp(false)
    }
  }

  const onOtpEmailSubmit = otpEmailForm.handleSubmit(async (values) => {
    await requestOtp(values.email.trim().toLowerCase())
  })

  const onOtpCodeSubmit = otpCodeForm.handleSubmit(async (values) => {
    setFormError(null)
    try {
      const data = await verifyOtp(otpEmail, values.code)
      setSession(data.tokens, data.user)
      finishAuth("Вы вошли по коду")
    } catch (err: unknown) {
      setFormError(mapAuthError(err, "Неверный или просроченный код"))
    }
  })

  const handleTelegramAuth = useCallback(
    async (user: TelegramLoginPayload) => {
      setFormError(null)
      try {
        const data = await loginWithTelegram({
          id: user.id,
          first_name: user.first_name,
          last_name: user.last_name || "",
          username: user.username || "",
          photo_url: user.photo_url || "",
          auth_date: user.auth_date,
          hash: user.hash,
        })
        setSession(data.tokens, data.user)
        finishAuth("Вы вошли через Telegram")
      } catch (err: unknown) {
        setFormError(mapAuthError(err, "Не удалось войти через Telegram"))
      }
    },
    // finishAuth closes over router/onSuccess — intentional
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setSession],
  )

  const busy =
    isPending ||
    sendingOtp ||
    credentialsForm.formState.isSubmitting ||
    otpEmailForm.formState.isSubmitting ||
    otpCodeForm.formState.isSubmitting

  const title =
    mode === "register"
      ? "Регистрация"
      : mode === "otp"
        ? otpStep === 1
          ? "Вход по email"
          : "Подтверждение"
        : "Вход"

  const subtitle =
    mode === "register"
      ? "Создайте аккаунт и соберите первую карточку"
      : mode === "otp"
        ? otpStep === 1
          ? "Укажите email — отправим 6-значный код"
          : `Код отправлен на ${otpEmail}`
        : `Добро пожаловать в ${APP_NAME}`

  if (IS_MOCK) {
    return (
      <GlassCard
        hoverLift={false}
        padding="lg"
        className={cn("relative w-full border-white/10 copper-border", className)}
      >
        <div className="flex flex-col items-center gap-3 py-8 text-center">
          <Loader2 className="size-6 animate-spin text-emerald" aria-hidden />
          <p className="font-heading text-sm font-semibold">Mock-вход…</p>
          <p className="text-xs text-muted-foreground">
            {MOCK_AUTH_USER.email} · без OTP и пароля
          </p>
        </div>
      </GlassCard>
    )
  }

  return (
    <GlassCard
      hoverLift={false}
      padding="lg"
      className={cn("relative w-full border-white/10 copper-border", className)}
    >
      {!hideHomeLink ? (
        <Link
          href="/"
          className="absolute top-4 left-4 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Назад на главную
        </Link>
      ) : null}

      <div
        className={cn(
          "mb-6",
          !hideHomeLink ? "mt-4" : "",
          compact ? "space-y-1" : "space-y-2",
        )}
      >
        <p className="font-heading text-xs font-medium tracking-[0.18em] text-copper uppercase">
          {APP_NAME}
        </p>
        <h1
          className={cn(
            "font-heading font-semibold tracking-tight text-foreground",
            compact ? "text-xl" : "text-2xl",
          )}
        >
          {title}
        </h1>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
        {mode === "otp" ? (
          <div className="flex items-center gap-2 pt-2" aria-hidden>
            <span
              className={cn(
                "h-1 flex-1 rounded-full",
                otpStep >= 1 ? "bg-foreground" : "bg-white/10",
              )}
            />
            <span
              className={cn(
                "h-1 flex-1 rounded-full",
                otpStep >= 2 ? "bg-foreground" : "bg-white/10",
              )}
            />
          </div>
        ) : null}
      </div>

      {mode === "otp" && otpStep === 1 ? (
        <form onSubmit={onOtpEmailSubmit} className="space-y-4" noValidate>
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
              aria-invalid={!!otpEmailForm.formState.errors.email}
              className="h-12 bg-loft-surface/60 text-base"
              {...otpEmailForm.register("email")}
            />
            <FieldError message={otpEmailForm.formState.errors.email?.message} />
          </div>

          {formError ? (
            <p className="text-sm text-destructive" role="alert">
              {formError}
            </p>
          ) : null}

          <GlassButton
            type="submit"
            className="h-12 w-full text-base"
            disabled={busy}
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Отправить код
          </GlassButton>

          {!otpFirst ? (
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              disabled={busy}
              onClick={() => switchMode("login")}
            >
              Назад к входу по паролю
            </Button>
          ) : (
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              disabled={busy}
              onClick={() => switchMode("login")}
            >
              Войти по паролю
            </Button>
          )}
        </form>
      ) : null}

      {mode === "otp" && otpStep === 2 ? (
        <form onSubmit={onOtpCodeSubmit} className="space-y-4" noValidate>
          <div>
            <label
              htmlFor="otp-code"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              6-значный код
            </label>
            <Input
              id="otp-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="••••••"
              maxLength={6}
              aria-invalid={!!otpCodeForm.formState.errors.code}
              className="h-12 bg-loft-surface/60 text-center text-xl tracking-[0.35em]"
              {...otpCodeForm.register("code")}
            />
            <FieldError message={otpCodeForm.formState.errors.code?.message} />
          </div>

          {formError ? (
            <p className="text-sm text-destructive" role="alert">
              {formError}
            </p>
          ) : null}

          <GlassButton
            type="submit"
            className="h-12 w-full text-base"
            disabled={busy}
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Подтвердить
          </GlassButton>

          <div className="flex flex-col gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-10 w-full border-white/10 bg-transparent"
              disabled={busy || resendIn > 0}
              onClick={() => void requestOtp(otpEmail)}
            >
              {resendIn > 0
                ? `Отправить снова через ${resendIn} с`
                : "Отправить код снова"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              disabled={busy}
              onClick={() => {
                setOtpStep(1)
                setFormError(null)
              }}
            >
              Изменить email
            </Button>
          </div>
        </form>
      ) : null}

      {mode !== "otp" ? (
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
      ) : null}

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
            <TelegramLoginButton
              disabled={busy}
              onAuth={(user) => void handleTelegramAuth(user)}
            />
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
