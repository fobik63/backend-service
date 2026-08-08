"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { Camera, Loader2 } from "lucide-react"
import { useRef, useState, type ChangeEvent } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { GlassButton } from "@/components/ui/glass-button"
import { Input } from "@/components/ui/input"
import {
  personalDataSchema,
  type PersonalDataValues,
} from "@/lib/validators/settings"
import { cn } from "@/lib/utils"

const DEFAULTS: PersonalDataValues = {
  displayName: "Алексей Иванов",
  email: "alexey@example.com",
  telegram: "@alexey_seller",
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <p className="mt-1.5 text-xs text-destructive">{message}</p>
}

function PersonalDataTab() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null)
  const [avatarFileName, setAvatarFileName] = useState<string | null>(null)

  const form = useForm<PersonalDataValues>({
    resolver: zodResolver(personalDataSchema),
    defaultValues: DEFAULTS,
    mode: "onSubmit",
  })

  const initials = (form.watch("displayName") || "??")
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  const onPickAvatar = () => fileInputRef.current?.click()

  const onAvatarChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    if (!file.type.startsWith("image/")) {
      toast.error("Выберите изображение")
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error("Файл больше 5 МБ")
      return
    }

    const url = URL.createObjectURL(file)
    setAvatarPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return url
    })
    setAvatarFileName(file.name)
    toast.message("Аватар выбран", {
      description: "Сохраните изменения, чтобы применить",
    })
  }

  const onSubmit = form.handleSubmit(async () => {
    await new Promise((r) => setTimeout(r, 500))
    toast.success("Личные данные сохранены")
  })

  const busy = form.formState.isSubmitting

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="relative shrink-0">
          <Avatar
            className="size-20 after:rounded-full data-[size=default]:size-20"
            size="lg"
          >
            {avatarPreview ? (
              <AvatarImage src={avatarPreview} alt="Аватар" />
            ) : null}
            <AvatarFallback className="bg-sage/60 text-lg text-emerald">
              {initials}
            </AvatarFallback>
          </Avatar>
          <button
            type="button"
            onClick={onPickAvatar}
            disabled={busy}
            aria-label="Загрузить аватар"
            className={cn(
              "absolute -bottom-1 -right-1 flex size-8 items-center justify-center rounded-full",
              "border border-white/15 bg-loft-surface text-copper",
              "transition-colors hover:bg-muted hover:text-foreground",
              "outline-none focus-visible:ring-2 focus-visible:ring-emerald/50"
            )}
          >
            <Camera className="size-3.5" aria-hidden />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="sr-only"
            onChange={onAvatarChange}
          />
        </div>
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-foreground">Фото профиля</p>
          <p className="text-xs text-muted-foreground">
            PNG, JPG или WebP до 5 МБ
            {avatarFileName ? ` · ${avatarFileName}` : null}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-2 border-white/10 bg-transparent"
            onClick={onPickAvatar}
            disabled={busy}
          >
            Загрузить файл
          </Button>
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
            placeholder="you@example.com"
            aria-invalid={!!form.formState.errors.email}
            className="h-10 bg-loft-surface/60"
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
