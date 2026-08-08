"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { CheckCircle2, Eye, EyeOff, Loader2, PlugZap } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"

import {
  OzonLogo,
  WildberriesLogo,
} from "@/components/onboarding/brand-logos"
import { Button } from "@/components/ui/button"
import { GlassButton } from "@/components/ui/glass-button"
import { Input } from "@/components/ui/input"
import {
  integrationsSchema,
  type IntegrationsValues,
} from "@/lib/validators/settings"
import { cn } from "@/lib/utils"

type ConnectionStatus = "idle" | "checking" | "ok" | "error"

function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <p className="mt-1.5 text-xs text-destructive">{message}</p>
}

function ApiKeyField({
  id,
  label,
  placeholder,
  value,
  onChange,
  error,
  disabled,
}: {
  id: string
  label: string
  placeholder: string
  value: string
  onChange: (value: string) => void
  error?: string
  disabled?: boolean
}) {
  const [visible, setVisible] = useState(false)

  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-sm font-medium text-foreground/90"
      >
        {label}
      </label>
      <div className="relative">
        <Input
          id={id}
          type={visible ? "text" : "password"}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={!!error}
          disabled={disabled}
          className="h-10 bg-loft-surface/60 pr-10 font-mono text-sm"
        />
        <button
          type="button"
          aria-label={visible ? "Скрыть ключ" : "Показать ключ"}
          className={cn(
            "absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md",
            "text-text-muted transition-colors hover:bg-muted hover:text-foreground",
            "outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          )}
          onClick={() => setVisible((v) => !v)}
          disabled={disabled}
        >
          {visible ? (
            <EyeOff className="size-3.5" aria-hidden />
          ) : (
            <Eye className="size-3.5" aria-hidden />
          )}
        </button>
      </div>
      <FieldError message={error} />
    </div>
  )
}

function StatusHint({ status }: { status: ConnectionStatus }) {
  if (status === "idle") return null
  if (status === "checking") {
    return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        Проверяем соединение…
      </p>
    )
  }
  if (status === "ok") {
    return (
      <p className="flex items-center gap-1.5 text-xs text-emerald">
        <CheckCircle2 className="size-3.5" aria-hidden />
        Связь установлена
      </p>
    )
  }
  return (
    <p className="text-xs text-destructive" role="alert">
      Не удалось подключиться. Проверьте ключ.
    </p>
  )
}

function IntegrationsTab() {
  const form = useForm<IntegrationsValues>({
    resolver: zodResolver(integrationsSchema),
    defaultValues: {
      ozonApiKey: "",
      ozonClientId: "",
      wildberriesApiKey: "",
    },
    mode: "onSubmit",
  })

  const [ozonStatus, setOzonStatus] = useState<ConnectionStatus>("idle")
  const [wbStatus, setWbStatus] = useState<ConnectionStatus>("idle")

  const checkConnection = async (
    marketplace: "ozon" | "wb",
    hasKey: boolean
  ) => {
    const setStatus = marketplace === "ozon" ? setOzonStatus : setWbStatus
    const label = marketplace === "ozon" ? "Ozon Seller" : "Wildberries"

    if (!hasKey) {
      toast.error(`Введите API-ключ ${label}`)
      setStatus("error")
      return
    }

    setStatus("checking")
    await new Promise((r) => setTimeout(r, 800))
    // UI stub until marketplace credentials API is wired
    setStatus("ok")
    toast.success(`${label}: связь установлена`)
  }

  const onSubmit = form.handleSubmit(async () => {
    await new Promise((r) => setTimeout(r, 500))
    toast.success("Ключи интеграций сохранены")
  })

  const busy = form.formState.isSubmitting
  const values = form.watch()

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <p className="text-sm text-muted-foreground">
        Ключи нужны для авто-импорта карточек с маркетплейсов. Они хранятся в
        зашифрованном виде и не отображаются полностью после сохранения.
      </p>

      <section className="space-y-4 rounded-xl border border-white/10 bg-loft-surface/40 p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <OzonLogo className="h-6 sm:h-7" />
            <div>
              <h3 className="text-sm font-medium text-foreground">
                Ozon Seller
              </h3>
              <p className="text-xs text-muted-foreground">
                Client ID и API-ключ из кабинета продавца
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5 border-white/10 bg-transparent"
            disabled={busy || ozonStatus === "checking"}
            onClick={() =>
              checkConnection(
                "ozon",
                Boolean(values.ozonApiKey.trim() && values.ozonClientId.trim())
              )
            }
          >
            {ozonStatus === "checking" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <PlugZap className="size-3.5" aria-hidden />
            )}
            Проверить связь
          </Button>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label
              htmlFor="ozon-client-id"
              className="mb-1.5 block text-sm font-medium text-foreground/90"
            >
              Client ID
            </label>
            <Input
              id="ozon-client-id"
              autoComplete="off"
              placeholder="123456"
              className="h-10 bg-loft/50 font-mono text-sm"
              aria-invalid={!!form.formState.errors.ozonClientId}
              {...form.register("ozonClientId")}
            />
            <FieldError
              message={form.formState.errors.ozonClientId?.message}
            />
          </div>
          <ApiKeyField
            id="ozon-api-key"
            label="API-ключ"
            placeholder="••••••••••••••••"
            value={values.ozonApiKey}
            onChange={(v) => {
              form.setValue("ozonApiKey", v, { shouldDirty: true })
              setOzonStatus("idle")
            }}
            error={form.formState.errors.ozonApiKey?.message}
            disabled={busy}
          />
        </div>
        <StatusHint status={ozonStatus} />
      </section>

      <section className="space-y-4 rounded-xl border border-white/10 bg-loft-surface/40 p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <WildberriesLogo className="h-5 sm:h-6" />
            <div>
              <h3 className="text-sm font-medium text-foreground">
                Wildberries
              </h3>
              <p className="text-xs text-muted-foreground">
                Токен «Контент» или «Статистика» из WB API
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5 border-white/10 bg-transparent"
            disabled={busy || wbStatus === "checking"}
            onClick={() =>
              checkConnection("wb", Boolean(values.wildberriesApiKey.trim()))
            }
          >
            {wbStatus === "checking" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <PlugZap className="size-3.5" aria-hidden />
            )}
            Проверить связь
          </Button>
        </div>

        <ApiKeyField
          id="wb-api-key"
          label="API-ключ"
          placeholder="••••••••••••••••"
          value={values.wildberriesApiKey}
          onChange={(v) => {
            form.setValue("wildberriesApiKey", v, { shouldDirty: true })
            setWbStatus("idle")
          }}
          error={form.formState.errors.wildberriesApiKey?.message}
          disabled={busy}
        />
        <StatusHint status={wbStatus} />
      </section>

      <div className="flex justify-end pt-1">
        <GlassButton type="submit" disabled={busy}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : null}
          Сохранить ключи
        </GlassButton>
      </div>
    </form>
  )
}

export { IntegrationsTab }
