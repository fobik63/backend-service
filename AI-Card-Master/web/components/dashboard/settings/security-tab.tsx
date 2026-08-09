"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { Loader2 } from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"

import { GlassButton } from "@/components/ui/glass-button"
import { Input } from "@/components/ui/input"
import { changePassword, getApiErrorMessage } from "@/lib/api"
import {
  changePasswordSchema,
  type ChangePasswordValues,
} from "@/lib/validators/settings"

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <p className="mt-1.5 text-xs text-destructive">{message}</p>
}

function SecurityTab() {
  const form = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: {
      currentPassword: "",
      newPassword: "",
      confirmPassword: "",
    },
    mode: "onSubmit",
  })

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await changePassword(values.currentPassword, values.newPassword)
      form.reset()
      toast.success("Пароль обновлён")
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Не удалось обновить пароль"))
    }
  })

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

      <section className="space-y-2 rounded-xl border border-white/10 bg-loft-surface/40 px-4 py-4">
        <h3 className="text-sm font-medium text-foreground">Активные сессии</h3>
        <p className="text-xs text-muted-foreground">
          Управление удалёнными сессиями пока недоступно: backend не
          предоставляет session-list API. Текущий вход защищён JWT refresh
          rotation.
        </p>
      </section>
    </div>
  )
}

export { SecurityTab }
