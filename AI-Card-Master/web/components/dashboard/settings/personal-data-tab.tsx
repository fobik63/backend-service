"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { Loader2 } from "lucide-react"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { GlassButton } from "@/components/ui/glass-button"
import { Input } from "@/components/ui/input"
import {
  displayNameFromEmail,
  getStoredUser,
} from "@/lib/auth/session"
import { fetchCurrentUser, getApiErrorMessage } from "@/lib/api"
import {
  personalDataSchema,
  type PersonalDataValues,
} from "@/lib/validators/settings"

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <p className="mt-1.5 text-xs text-destructive">{message}</p>
}

function PersonalDataTab() {
  const stored = getStoredUser()
  const form = useForm<PersonalDataValues>({
    resolver: zodResolver(personalDataSchema),
    defaultValues: {
      displayName: stored ? displayNameFromEmail(stored.email) : "",
      email: stored?.email ?? "",
      telegram: "",
    },
    mode: "onSubmit",
  })

  useEffect(() => {
    let cancelled = false
    void fetchCurrentUser()
      .then((user) => {
        if (cancelled) return
        form.reset({
          displayName: displayNameFromEmail(user.email),
          email: user.email,
          telegram: "",
        })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        toast.error(
          getApiErrorMessage(error, "Не удалось загрузить профиль")
        )
      })
    return () => {
      cancelled = true
    }
  }, [form])

  // eslint-disable-next-line react-hooks/incompatible-library -- react-hook-form watch
  const displayName = form.watch("displayName")
  const initials = (displayName || "??")
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  const onSubmit = form.handleSubmit(async () => {
    toast.error(
      "Обновление имени, Telegram и аватара пока недоступно: API профиля поддерживает только чтение /auth/me."
    )
  })

  const busy = form.formState.isSubmitting

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <Avatar
          className="size-20 after:rounded-full data-[size=default]:size-20"
          size="lg"
        >
          <AvatarFallback className="bg-sage/60 text-lg text-emerald">
            {initials}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-foreground">Профиль аккаунта</p>
          <p className="text-xs text-muted-foreground">
            Email загружается из API. Имя/Telegram/аватар пока нельзя сохранить
            на сервере.
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label
            htmlFor="settings-name"
            className="mb-1.5 block text-sm font-medium text-foreground/90"
          >
            Имя
          </label>
          <Input
            id="settings-name"
            autoComplete="name"
            placeholder="Как к вам обращаться"
            aria-invalid={!!form.formState.errors.displayName}
            className="h-10 bg-loft-surface/60"
            {...form.register("displayName")}
          />
          <FieldError message={form.formState.errors.displayName?.message} />
        </div>

        <div>
          <label
            htmlFor="settings-email"
            className="mb-1.5 block text-sm font-medium text-foreground/90"
          >
            Email
          </label>
          <Input
            id="settings-email"
            type="email"
            autoComplete="email"
            readOnly
            placeholder="you@example.com"
            aria-invalid={!!form.formState.errors.email}
            className="h-10 bg-loft-surface/60 opacity-80"
            {...form.register("email")}
          />
          <FieldError message={form.formState.errors.email?.message} />
        </div>

        <div>
          <label
            htmlFor="settings-telegram"
            className="mb-1.5 block text-sm font-medium text-foreground/90"
          >
            Telegram
          </label>
          <Input
            id="settings-telegram"
            autoComplete="username"
            placeholder="@username"
            aria-invalid={!!form.formState.errors.telegram}
            className="h-10 bg-loft-surface/60"
            {...form.register("telegram")}
          />
          <FieldError message={form.formState.errors.telegram?.message} />
        </div>
      </div>

      <div className="flex justify-end pt-1">
        <GlassButton type="submit" disabled={busy}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : null}
          Сохранить
        </GlassButton>
      </div>
    </form>
  )
}

export { PersonalDataTab }
