"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { CheckCircle2, Eye, EyeOff, Loader2, PlugZap } from "lucide-react"
import { useEffect, useState } from "react"
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
  getApiErrorMessage,
  listExportCredentials,
  saveExportCredentials,
} from "@/lib/api"
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
  const [showKey, setShowKey] = useState(false)

  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-sm font-medium text-foreground/90"
      >
        {label}
      </label>
      <div className="relative">
        {/* Native input: Base UI Input does not reliably toggle type password/text */}
        <input
          id={id}
          type={showKey ? "text" : "password"}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={!!error}
          disabled={disabled}
          className={cn(
            "h-10 w-full min-w-0 rounded-lg border border-input bg-loft-surface/60 px-2.5 py-1 pr-10 font-mono text-sm outline-none transition-colors",
            "placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
            "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
            "aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20"
          )}
        />
        <button
          type="button"
          aria-label={showKey ? "Скрыть ключ" : "Показать ключ"}
          aria-pressed={showKey}
          className={cn(
            "absolute top-1/2 right-2 z-10 flex size-7 -translate-y-1/2 items-center justify-center rounded-md",
            "text-text-muted transition-colors hover:bg-muted hover:text-foreground",
            "outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
            "disabled:pointer-events-none disabled:opacity-50"
          )}
          onClick={() => setShowKey((prev) => !prev)}
          disabled={disabled}
        >
          {showKey ? (
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
  const [configured, setConfigured] = useState<{
    ozon: boolean
    wildberries: boolean
  }>({ ozon: false, wildberries: false })

  useEffect(() => {
    let cancelled = false
    void listExportCredentials()
      .then((items) => {
        if (cancelled) return
        setConfigured({
          ozon: items.some((item) => item.platform === "ozon" && item.is_configured),
          wildberries: items.some(
            (item) => item.platform === "wildberries" && item.is_configured
          ),
        })
        if (items.some((item) => item.platform === "ozon" && item.is_configured)) {
          setOzonStatus("ok")
        }
        if (
          items.some(
            (item) => item.platform === "wildberries" && item.is_configured
          )
        ) {
          setWbStatus("ok")
        }
      })
      .catch(() => {
        // Credentials list is optional for the form; save still works.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const checkConnection = async (
    marketplace: "ozon" | "wb",
    hasKey: boolean
  ) => {
    const setStatus = marketplace === "ozon" ? setOzonStatus : setWbStatus
    const label = marketplace === "ozon" ? "Ozon Seller" : "Wildberries"
    const values = form.getValues()

    if (!hasKey) {
      toast.error(`Введите API-ключ ${label}`)
      setStatus("error")
      return
    }

    setStatus("checking")
    try {
      if (marketplace === "ozon") {
        await saveExportCredentials("ozon", {
          client_id: values.ozonClientId.trim(),
          api_key: values.ozonApiKey.trim(),
        })
        setConfigured((prev) => ({ ...prev, ozon: true }))
      } else {
        await saveExportCredentials("wildberries", {
          api_key: values.wildberriesApiKey.trim(),
        })
        setConfigured((prev) => ({ ...prev, wildberries: true }))
      }
      setStatus("ok")
      toast.success(`${label}: ключи сохранены и доступны для экспорта`)
    } catch (error) {
      setStatus("error")
      toast.error(
        getApiErrorMessage(
          error,
          `${label}: не удалось проверить/сохранить ключи`
        )
      )
    }
  }

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      const jobs: Promise<unknown>[] = []
      if (values.ozonApiKey.trim() && values.ozonClientId.trim()) {
        jobs.push(
          saveExportCredentials("ozon", {
            client_id: values.ozonClientId.trim(),
            api_key: values.ozonApiKey.trim(),
          })
        )
      }
      if (values.wildberriesApiKey.trim()) {
        jobs.push(
          saveExportCredentials("wildberries", {
            api_key: values.wildberriesApiKey.trim(),
          })
        )
      }
      if (jobs.length === 0) {
        toast.error("Заполните хотя бы один маркетплейс перед сохранением")
        return
      }
      await Promise.all(jobs)
      toast.success("Ключи интеграций сохранены")
    } catch (error) {
      toast.error(
        getApiErrorMessage(error, "Не удалось сохранить ключи интеграций")
      )
    }
  })

  const busy = form.formState.isSubmitting
  // React Compiler cannot memoize RHF watch; values are local form state only.
  // eslint-disable-next-line react-hooks/incompatible-library -- react-hook-form watch
  const values = form.watch()

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <p className="text-sm text-muted-foreground">
        Ключи нужны для one-click export на маркетплейсы. Они хранятся в
        зашифрованном виде
        {configured.ozon || configured.wildberries
          ? ` · уже настроено: ${[
              configured.ozon ? "Ozon" : null,
              configured.wildberries ? "WB" : null,
            ]
              .filter(Boolean)
              .join(", ")}`
          : ""}
        .
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
