"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { Laptop, Loader2, Monitor, Smartphone, Trash2 } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { GlassButton } from "@/components/ui/glass-button"
import { Input } from "@/components/ui/input"
import {
  changePasswordSchema,
  type ChangePasswordValues,
} from "@/lib/validators/settings"
import { cn } from "@/lib/utils"

type SessionDevice = "desktop" | "mobile" | "laptop"

type ActiveSession = {
  id: string
  device: SessionDevice
  label: string
  location: string
  lastActive: string
  current: boolean
}

const INITIAL_SESSIONS: ActiveSession[] = [
  {
    id: "s1",
    device: "laptop",
    label: "Chrome · Windows",
    location: "Москва, Россия",
    lastActive: "Сейчас",
    current: true,
  },
  {
    id: "s2",
    device: "mobile",
    label: "Safari · iPhone",
    location: "Санкт-Петербург, Россия",
    lastActive: "2 часа назад",
    current: false,
  },
  {
    id: "s3",
    device: "desktop",
    label: "Firefox · macOS",
    location: "Казань, Россия",
    lastActive: "Вчера",
    current: false,
  },
]

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <p className="mt-1.5 text-xs text-destructive">{message}</p>
}

function DeviceIcon({ device }: { device: SessionDevice }) {
  const Icon =
    device === "mobile" ? Smartphone : device === "laptop" ? Laptop : Monitor
  return <Icon className="size-4 text-copper" aria-hidden />
}

function SecurityTab() {
  const [sessions, setSessions] = useState(INITIAL_SESSIONS)
  const [revokingId, setRevokingId] = useState<string | null>(null)

  const form = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: {
      currentPassword: "",
      newPassword: "",
      confirmPassword: "",
    },
    mode: "onSubmit",
  })

  const onSubmit = form.handleSubmit(async () => {
    await new Promise((r) => setTimeout(r, 500))
    form.reset()
    toast.success("Пароль обновлён")
  })

  const revokeSession = async (id: string) => {
    setRevokingId(id)
    await new Promise((r) => setTimeout(r, 400))
    setSessions((prev) => prev.filter((s) => s.id !== id))
    setRevokingId(null)
    toast.success("Сессия завершена")
  }

  const revokeOthers = async () => {
    const others = sessions.filter((s) => !s.current)
    if (others.length === 0) {
      toast.message("Других активных сессий нет")
      return
    }
    setRevokingId("all")
    await new Promise((r) => setTimeout(r, 500))
    setSessions((prev) => prev.filter((s) => s.current))
    setRevokingId(null)
    toast.success("Остальные сессии завершены")
  }

  const busy = form.formState.isSubmitting

  return (
    <div className="space-y-8">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <div>
          <h3 className="text-sm font-medium text-foreground">Смена пароля</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Используйте уникальный пароль длиной не менее 8 символов
          </p>
        </div>

        <div className="grid gap-4 sm:max-w-md">
          <div>
            <label
              htmlFor="current-password"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              Текущий пароль
            </label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              aria-invalid={!!form.formState.errors.currentPassword}
              className="h-10 bg-loft-surface/60"
              {...form.register("currentPassword")}
            />
            <FieldError
              message={form.formState.errors.currentPassword?.message}
            />
          </div>

          <div>
            <label
              htmlFor="new-password"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              Новый пароль
            </label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              placeholder="••••••••"
              aria-invalid={!!form.formState.errors.newPassword}
              className="h-10 bg-loft-surface/60"
              {...form.register("newPassword")}
            />
            <FieldError
              message={form.formState.errors.newPassword?.message}
            />
          </div>

          <div>
            <label
              htmlFor="confirm-password"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              Подтверждение
            </label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              placeholder="••••••••"
              aria-invalid={!!form.formState.errors.confirmPassword}
              className="h-10 bg-loft-surface/60"
              {...form.register("confirmPassword")}
            />
            <FieldError
              message={form.formState.errors.confirmPassword?.message}
            />
          </div>
        </div>

        <GlassButton type="submit" disabled={busy}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : null}
          Обновить пароль
        </GlassButton>
      </form>

      <div className="h-px bg-white/10" aria-hidden />

      <section className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-foreground">
              Активные сессии
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Устройства, с которых выполнен вход в аккаунт
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-white/10 bg-transparent"
            disabled={revokingId === "all"}
            onClick={revokeOthers}
          >
            {revokingId === "all" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : null}
            Завершить остальные
          </Button>
        </div>

        <ul className="space-y-2">
          {sessions.map((session) => (
            <li
              key={session.id}
              className={cn(
                "flex items-center gap-3 rounded-xl border border-white/10 bg-loft-surface/40 px-3 py-3 sm:px-4"
              )}
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-sage/40">
                <DeviceIcon device={session.device} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate text-sm font-medium text-foreground">
                    {session.label}
                  </p>
                  {session.current ? (
                    <Badge
                      variant="secondary"
                      className="bg-emerald/15 text-emerald"
                    >
                      Текущая
                    </Badge>
                  ) : null}
                </div>
                <p className="truncate text-xs text-muted-foreground">
                  {session.location} · {session.lastActive}
                </p>
              </div>
              {!session.current ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Завершить сессию ${session.label}`}
                  disabled={revokingId === session.id}
                  onClick={() => revokeSession(session.id)}
                  className="shrink-0 text-text-muted hover:text-destructive"
                >
                  {revokingId === session.id ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Trash2 className="size-4" aria-hidden />
                  )}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

export { SecurityTab }
