"use client"

import {
  Eye,
  Loader2,
  Sparkles,
  Target,
  KeyRound,
  Palette,
  BadgeCheck,
  Copy,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  enqueueEyeOfGodSpy,
  getApiErrorMessage,
  pollEyeOfGodSpyJob,
  type EyeOfGodDashboard,
  type EyeOfGodFrequencyItem,
  type EyeOfGodPlatform,
} from "@/lib/api"
import { applyEyeInsightsToProject } from "@/lib/editor/canvas-actions"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

type SpyPhase = "idle" | "discovering" | "polling" | "ready" | "error"

function FrequencyList({
  title,
  items,
  empty,
}: {
  title: string
  items: EyeOfGodFrequencyItem[]
  empty: string
}) {
  if (items.length === 0) {
    return (
      <div className="space-y-1.5">
        <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          {title}
        </h4>
        <p className="text-[11px] text-muted-foreground/80">{empty}</p>
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        {title}
      </h4>
      <ul className="space-y-1">
        {items.slice(0, 6).map((item) => (
          <li
            key={`${title}-${item.text}`}
            className="flex items-center justify-between gap-2 rounded-md border border-white/8 bg-white/[0.03] px-2 py-1.5"
          >
            <span className="min-w-0 truncate text-[11px] text-foreground/90">
              {item.text}
            </span>
            <span className="shrink-0 font-mono text-[10px] tabular-nums text-amber/90">
              {item.count}·{Math.round(item.share_percent)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function EyeOfGodSection() {
  const { t } = useI18n()

  const [articleInput, setArticleInput] = useState("")
  const [platform, setPlatform] = useState<EyeOfGodPlatform>("auto")
  const [phase, setPhase] = useState<SpyPhase>("idle")
  const [statusLabel, setStatusLabel] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<EyeOfGodDashboard | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const busy = phase === "discovering" || phase === "polling"

  const handleParse = async () => {
    const value = articleInput.trim()
    if (!value) {
      toast.error(t("editor.eyeInputRequired"))
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setPhase("discovering")
    setStatusLabel(t("editor.eyeDiscovering"))
    setErrorMessage(null)
    setDashboard(null)

    try {
      const resolvedPlatform: EyeOfGodPlatform =
        platform === "auto" && !/^https?:\/\//i.test(value) && !value.includes(".")
          ? "wb"
          : platform

      const enqueued = await enqueueEyeOfGodSpy({
        input: value,
        platform: resolvedPlatform,
        limit: 10,
      })

      setPhase("polling")
      setStatusLabel(
        t("editor.eyePolling", {
          count: String(enqueued.competitors_count || 10),
        }),
      )

      const job = await pollEyeOfGodSpyJob(enqueued.task_id, {
        signal: controller.signal,
      })

      if (job.status === "failed") {
        throw new Error(job.error_message || t("editor.eyeError"))
      }

      if (!job.dashboard) {
        throw new Error(t("editor.eyeNoDashboard"))
      }

      setDashboard(job.dashboard)
      setPhase("ready")
      setStatusLabel(null)

      const badgeLabels = [
        ...job.dashboard.badge_patterns.map((item) => item.text),
        ...job.dashboard.strong_triggers.map((item) => item.text),
      ]
      const { badgesCreated } = applyEyeInsightsToProject({
        generatorPrompt: job.dashboard.generator_prompt,
        badgeLabels,
        description: job.dashboard.ai_recommendation,
        title: job.dashboard.seed_title,
      })

      toast.success(
        t("editor.eyeAppliedToProject", {
          count: String(badgesCreated),
        }),
      )
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setPhase("idle")
        setStatusLabel(null)
        return
      }
      const message = getApiErrorMessage(error, t("editor.eyeError"))
      setErrorMessage(message)
      setPhase("error")
      setStatusLabel(null)
      toast.error(message)
    }
  }

  const applyPrompt = async () => {
    if (!dashboard?.generator_prompt) return
    try {
      await navigator.clipboard.writeText(dashboard.generator_prompt)
      applyEyeInsightsToProject({
        generatorPrompt: dashboard.generator_prompt,
        badgeLabels: [
          ...dashboard.badge_patterns.map((item) => item.text),
          ...dashboard.strong_triggers.map((item) => item.text),
        ],
        description: dashboard.ai_recommendation,
        title: dashboard.seed_title,
      })
      window.dispatchEvent(new CustomEvent("editor:focus-generate-tab"))
      toast.success(t("editor.eyePromptApplied"))
    } catch {
      toast.error(t("editor.eyeCopyFailed"))
    }
  }

  const copyRecommendation = async () => {
    if (!dashboard?.ai_recommendation) return
    try {
      await navigator.clipboard.writeText(dashboard.ai_recommendation)
      toast.success(t("editor.eyeCopied"))
    } catch {
      toast.error(t("editor.eyeCopyFailed"))
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <Eye className="size-4 text-amber" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.eyeTitle")}
        </h3>
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        {t("editor.eyeHint")}
      </p>

      <div className="flex flex-col gap-2">
        <Input
          value={articleInput}
          onChange={(e) => setArticleInput(e.target.value)}
          placeholder={t("editor.eyePlaceholder")}
          aria-label={t("editor.eyePlaceholder")}
          disabled={busy}
          className="h-9 border-white/10 bg-white/[0.04] text-xs"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy) void handleParse()
          }}
        />

        <div className="flex gap-1.5">
          {(
            [
              ["auto", t("editor.eyePlatformAuto")],
              ["wb", "WB"],
              ["ozon", "Ozon"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              disabled={busy}
              onClick={() => setPlatform(value)}
              className={cn(
                "h-7 flex-1 rounded-md border text-[10px] font-medium tracking-wide uppercase transition-colors",
                platform === value
                  ? "border-amber/40 bg-amber/15 text-amber"
                  : "border-white/10 bg-white/[0.03] text-muted-foreground hover:border-white/20",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <Button
          type="button"
          size="sm"
          disabled={busy}
          onClick={() => void handleParse()}
          className="w-full gap-1.5"
        >
          {busy ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <Target className="size-3.5" aria-hidden />
          )}
          {busy ? t("editor.eyeParsing") : t("editor.eyeAction")}
        </Button>
      </div>

      {statusLabel ? (
        <p
          role="status"
          className="rounded-md border border-amber/20 bg-amber/10 px-2.5 py-2 text-[11px] leading-relaxed text-amber"
        >
          {statusLabel}
        </p>
      ) : null}

      {errorMessage && phase === "error" ? (
        <p role="alert" className="text-[11px] leading-relaxed text-destructive">
          {errorMessage}
        </p>
      ) : null}

      {dashboard ? (
        <div className="space-y-3 border-t border-white/8 pt-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-foreground">
                {dashboard.seed_title || dashboard.seed_article}
              </p>
              <p className="text-[10px] text-muted-foreground">
                {t("editor.eyeAnalyzed", {
                  count: String(dashboard.competitors_analyzed),
                })}
              </p>
            </div>
          </div>

          <div className="max-h-[22rem] space-y-3 overflow-y-auto overscroll-contain pr-0.5">
            <FrequencyList
              title={t("editor.eyeBadges")}
              items={dashboard.badge_patterns}
              empty={t("editor.eyeEmpty")}
            />
            <FrequencyList
              title={t("editor.eyeTriggers")}
              items={dashboard.strong_triggers}
              empty={t("editor.eyeEmpty")}
            />
            <FrequencyList
              title={t("editor.eyeKeywords")}
              items={dashboard.frequent_keywords}
              empty={t("editor.eyeEmpty")}
            />

            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <Palette className="size-3 text-copper" aria-hidden />
                <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                  {t("editor.eyeVisual")}
                </h4>
              </div>
              {dashboard.visual_hooks.length === 0 ? (
                <p className="text-[11px] text-muted-foreground/80">
                  {t("editor.eyeEmpty")}
                </p>
              ) : (
                <ul className="space-y-1">
                  {dashboard.visual_hooks.slice(0, 6).map((hook) => (
                    <li
                      key={hook}
                      className="rounded-md border border-white/8 bg-white/[0.03] px-2 py-1.5 text-[11px] leading-snug text-foreground/85"
                    >
                      {hook}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <Sparkles className="size-3 text-emerald" aria-hidden />
                <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                  {t("editor.eyeRecommendation")}
                </h4>
              </div>
              <p className="rounded-md border border-emerald/25 bg-emerald/10 px-2.5 py-2 text-[11px] leading-relaxed text-foreground/90">
                {dashboard.ai_recommendation || t("editor.eyeEmpty")}
              </p>
              <div className="flex gap-1.5">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 flex-1 gap-1 border-white/10 text-[10px]"
                  onClick={() => void copyRecommendation()}
                  disabled={!dashboard.ai_recommendation}
                >
                  <Copy className="size-3" aria-hidden />
                  {t("editor.eyeCopy")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="h-7 flex-1 gap-1 text-[10px]"
                  onClick={() => void applyPrompt()}
                  disabled={!dashboard.generator_prompt}
                >
                  <BadgeCheck className="size-3" aria-hidden />
                  {t("editor.eyeApplyPrompt")}
                </Button>
              </div>
            </div>

            {dashboard.competitors.length > 0 ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <KeyRound className="size-3 text-muted-foreground" aria-hidden />
                  <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                    {t("editor.eyeCompetitors")}
                  </h4>
                </div>
                <ul className="space-y-1">
                  {dashboard.competitors.slice(0, 10).map((card) => (
                    <li
                      key={`${card.marketplace}-${card.article}`}
                      className="rounded-md border border-white/8 bg-white/[0.03] px-2 py-1.5"
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-[11px] font-medium text-foreground/90">
                          #{card.rank} {card.title || card.article}
                        </span>
                        {card.price_rub != null ? (
                          <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                            {Math.round(card.price_rub)}₽
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                        {card.article}
                        {card.brand ? ` · ${card.brand}` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}

export { EyeOfGodSection }
