"use client"

import { AnimatePresence } from "framer-motion"
import {
  Eye,
  Loader2,
  MessageSquareWarning,
  Sparkles,
  Target,
  BadgeCheck,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import {
  AnalysisStatusBar,
  EyeCompetitorsSkeleton,
  EyeInsightsSkeleton,
  FadeInBlock,
} from "@/components/editor/analysis-loading"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  analyzeCompetitorPains,
  collectCompetitorReviews,
  enqueueEyeOfGodSpy,
  getApiErrorMessage,
  searchCompetitors,
  type BuyerPain,
  type InfographicOffer,
  type NicheCompetitorCard,
} from "@/lib/api"
import { applyEyeInsightsToProject } from "@/lib/editor/canvas-actions"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

type SpyPhase =
  | "idle"
  | "discovering"
  | "collecting"
  | "analyzing"
  | "ready"

const TOP_N = 5
const REVIEWS_TO_PURCHASES = 12.5

const PHASE_STEP: Record<"discovering" | "collecting" | "analyzing", number> = {
  discovering: 1,
  collecting: 2,
  analyzing: 3,
}

/** Map WB volume shard → basket host (same convention as CDN gallery). */
function wbBasketHost(vol: number): string {
  const ranges: Array<[number, number]> = [
    [143, 1],
    [287, 2],
    [431, 3],
    [719, 4],
    [1007, 5],
    [1061, 6],
    [1115, 7],
    [1169, 8],
    [1313, 9],
    [1601, 10],
    [1655, 11],
    [1919, 12],
    [2045, 13],
    [2189, 14],
    [2405, 15],
    [2621, 16],
    [2837, 17],
    [3053, 18],
    [3269, 19],
    [3485, 20],
    [3701, 21],
    [3917, 22],
    [4133, 23],
    [4349, 24],
    [4565, 25],
    [4781, 26],
    [4997, 27],
    [5213, 28],
    [5429, 29],
    [5645, 30],
  ]
  for (const [maxVol, basket] of ranges) {
    if (vol <= maxVol) {
      return `https://basket-${String(basket).padStart(2, "0")}.wbbasket.ru`
    }
  }
  return "https://basket-31.wbbasket.ru"
}

function wbThumbnailUrl(article: string): string | null {
  const nmId = Number(article)
  if (!Number.isFinite(nmId) || nmId <= 0) return null
  const vol = Math.floor(nmId / 100_000)
  const part = Math.floor(nmId / 1_000)
  const host = wbBasketHost(vol)
  return `${host}/vol${vol}/part${part}/${nmId}/images/c246x328/1.webp`
}

function formatEstimatedRevenue(value: number): string {
  if (value >= 1_000_000) {
    const millions = value / 1_000_000
    const rounded =
      millions >= 10 ? Math.round(millions) : Math.round(millions * 10) / 10
    return `${rounded.toLocaleString("ru-RU")} млн ₽`
  }
  if (value >= 1_000) {
    return `${Math.round(value / 1_000).toLocaleString("ru-RU")} тыс ₽`
  }
  return `${Math.round(value).toLocaleString("ru-RU")} ₽`
}

function estimateRevenueRub(
  feedbacks: number | null | undefined,
  priceRub: number | null | undefined,
): number | null {
  if (feedbacks == null || feedbacks < 0) return null
  if (priceRub == null || priceRub < 0) return null
  return Math.round(feedbacks * REVIEWS_TO_PURCHASES * priceRub)
}

function looksLikeCompetitorRef(value: string): boolean {
  if (/^https?:\/\//i.test(value)) return true
  if (/wildberries\.|wb\.ru|ozon\./i.test(value)) return true
  if (/^\d{6,}$/.test(value)) return true
  return false
}

function withThumbnail(card: NicheCompetitorCard): NicheCompetitorCard {
  if (card.thumbnail_url) return card
  return { ...card, thumbnail_url: wbThumbnailUrl(card.article) }
}

function normalizeCompetitors(
  cards: NicheCompetitorCard[],
): NicheCompetitorCard[] {
  let leaderRevenue: number | null = null
  const normalized = cards.slice(0, TOP_N).map((card, index) => {
    const revenue =
      card.estimated_revenue_rub ??
      estimateRevenueRub(card.feedbacks, card.price_rub)
    const next = withThumbnail({
      ...card,
      rank: card.rank || index + 1,
      estimated_revenue_rub: revenue,
    })
    if (revenue != null && (leaderRevenue == null || revenue > leaderRevenue)) {
      leaderRevenue = revenue
    }
    return next
  })
  return normalized
}

function CompetitorThumb({
  card,
  isLeader,
  revenueLabel,
}: {
  card: NicheCompetitorCard
  isLeader: boolean
  revenueLabel: string
}) {
  const [broken, setBroken] = useState(false)
  const title = card.title || card.article
  const revenue = card.estimated_revenue_rub

  return (
    <a
      href={card.url}
      target="_blank"
      rel="noreferrer"
      className={cn(
        "group flex flex-col overflow-hidden rounded-lg border bg-white/[0.03] transition-colors hover:bg-white/[0.06]",
        isLeader ? "border-amber/40" : "border-white/8",
      )}
    >
      <div className="relative aspect-[3/4] bg-zinc-950/60">
        {card.thumbnail_url && !broken ? (
          // eslint-disable-next-line @next/next/no-img-element -- WB CDN; remotePatterns may not cover all baskets
          <img
            src={card.thumbnail_url}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="size-full object-cover"
            onError={() => setBroken(true)}
          />
        ) : (
          <div className="flex size-full items-center justify-center text-[10px] text-muted-foreground">
            #{card.rank}
          </div>
        )}
        <span className="absolute top-1 left-1 rounded bg-black/65 px-1 py-0.5 font-mono text-[9px] text-white/90">
          #{card.rank}
        </span>
      </div>
      <div className="space-y-0.5 p-1.5">
        <p className="line-clamp-2 text-[10px] leading-snug text-foreground/90">
          {title}
        </p>
        {revenue != null ? (
          <p
            className={cn(
              "font-mono text-[10px] tabular-nums",
              isLeader ? "text-amber" : "text-muted-foreground",
            )}
            title={revenueLabel}
          >
            ~{formatEstimatedRevenue(revenue)}
          </p>
        ) : (
          <p className="text-[10px] text-muted-foreground/70">—</p>
        )}
      </div>
    </a>
  )
}

function EyeOfGodSection() {
  const { t } = useI18n()
  const productMeta = useEditorStore((s) => s.productMeta)
  const setAiStudioBusy = useEditorStore((s) => s.setAiStudioBusy)
  const generating = useEditorStore((s) => s.busyKind === "generating")

  const [queryInput, setQueryInput] = useState("")
  const [phase, setPhase] = useState<SpyPhase>("idle")
  const [statusLabel, setStatusLabel] = useState<string | null>(null)
  const [competitors, setCompetitors] = useState<NicheCompetitorCard[]>([])
  const [pains, setPains] = useState<BuyerPain[]>([])
  const [recommendations, setRecommendations] = useState<InfographicOffer[]>(
    [],
  )
  const abortRef = useRef<AbortController | null>(null)
  const requestIdRef = useRef(0)

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      requestIdRef.current += 1
      setAiStudioBusy(false)
    }
  }, [setAiStudioBusy])

  const busy =
    phase === "discovering" ||
    phase === "collecting" ||
    phase === "analyzing"
  const locked = busy || generating

  const statusStep =
    phase === "discovering" ||
    phase === "collecting" ||
    phase === "analyzing"
      ? PHASE_STEP[phase]
      : undefined

  const leaderRevenue = competitors.reduce<number | null>((max, card) => {
    const value = card.estimated_revenue_rub
    if (value == null) return max
    if (max == null || value > max) return value
    return max
  }, null)

  const resolveCompetitors = async (
    value: string,
  ): Promise<NicheCompetitorCard[]> => {
    if (looksLikeCompetitorRef(value)) {
      const enqueued = await enqueueEyeOfGodSpy({
        input: value,
        platform: "auto",
        limit: TOP_N,
      })
      return normalizeCompetitors(
        enqueued.discovery.map((hit) => ({
          rank: hit.rank,
          article: hit.article,
          title: hit.title,
          brand: hit.brand,
          price_rub: hit.price_rub,
          rating: hit.rating,
          feedbacks: hit.feedbacks,
          url: hit.url,
          estimated_revenue_rub: estimateRevenueRub(
            hit.feedbacks,
            hit.price_rub,
          ),
        })),
      )
    }

    const result = await searchCompetitors({ query: value, limit: TOP_N })
    return normalizeCompetitors(result.competitors)
  }

  const handleAnalyze = async () => {
    const value = queryInput.trim()
    if (!value) {
      toast.error(t("editor.eyeInputRequired"))
      return
    }
    if (busy || generating) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const requestId = ++requestIdRef.current

    setPhase("discovering")
    setStatusLabel(t("editor.eyeDiscovering"))
    setCompetitors([])
    setPains([])
    setRecommendations([])
    setAiStudioBusy(true)

    try {
      const top = await resolveCompetitors(value)
      if (controller.signal.aborted) {
        throw new DOMException("Aborted", "AbortError")
      }
      if (top.length === 0) {
        throw new Error(t("editor.eyeNoCompetitors"))
      }

      setCompetitors(top)
      setPhase("collecting")
      setStatusLabel(t("editor.eyeCollectingReviews"))

      const reviews = await collectCompetitorReviews({
        articles: top.map((c) => c.article),
      })
      if (controller.signal.aborted) {
        throw new DOMException("Aborted", "AbortError")
      }
      if (reviews.complaint_texts.length === 0) {
        throw new Error(t("editor.eyeNoComplaints"))
      }

      setPhase("analyzing")
      setStatusLabel(t("editor.eyeAnalyzingPains"))

      const productContext = [
        productMeta.title,
        productMeta.brand,
        productMeta.category,
        productMeta.description,
      ]
        .map((part) => part.trim())
        .filter(Boolean)
        .join(" · ")
        .slice(0, 1000)

      const analysis = await analyzeCompetitorPains({
        complaintTexts: reviews.complaint_texts,
        productContext,
      })
      if (controller.signal.aborted) {
        throw new DOMException("Aborted", "AbortError")
      }

      setPains(analysis.pains)
      setRecommendations(analysis.recommendations)
      setPhase("ready")
      setStatusLabel(null)

      const badgeLabels = analysis.recommendations.map((item) => item.offer_text)
      const painsSummary = analysis.pains
        .map((pain) => `${pain.rank}. ${pain.title}: ${pain.summary}`)
        .join("\n")

      const { badgesCreated } = applyEyeInsightsToProject({
        badgeLabels,
        description: painsSummary,
        title: top[0]?.title ?? value,
        generatorPrompt:
          `Инфографика карточки маркетплейса. Закрой боли конкурентов плашками: ` +
          badgeLabels.join(", ") +
          `.`,
      })

      toast.success(
        t("editor.eyeAppliedToProject", {
          count: String(badgesCreated),
        }),
      )
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        if (requestIdRef.current === requestId) {
          setPhase("idle")
          setStatusLabel(null)
        }
        return
      }
      const message = getApiErrorMessage(error, t("editor.eyeError"))
      setPhase("idle")
      setStatusLabel(null)
      toast.error(message)
    } finally {
      if (requestIdRef.current === requestId) {
        setAiStudioBusy(false)
      }
    }
  }

  const applyBadges = () => {
    if (busy || recommendations.length === 0) return
    const { badgesCreated } = applyEyeInsightsToProject({
      badgeLabels: recommendations.map((item) => item.offer_text),
      generatorPrompt:
        `Инфографика карточки маркетплейса. Плашки: ` +
        recommendations.map((item) => item.offer_text).join(", "),
    })
    window.dispatchEvent(new CustomEvent("editor:focus-generate-tab"))
    toast.success(
      t("editor.eyeAppliedToProject", { count: String(badgesCreated) }),
    )
  }

  const hasResults =
    competitors.length > 0 || pains.length > 0 || recommendations.length > 0
  const showCompetitorSkeleton = busy && competitors.length === 0
  const showInsightsSkeleton =
    busy &&
    (phase === "collecting" || phase === "analyzing") &&
    pains.length === 0

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
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder={t("editor.eyePlaceholder")}
          aria-label={t("editor.eyePlaceholder")}
          disabled={locked}
          className="h-9 border-white/10 bg-white/[0.04] text-xs"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !locked) void handleAnalyze()
          }}
        />

        <Button
          type="button"
          size="sm"
          disabled={locked}
          aria-busy={busy}
          onClick={() => void handleAnalyze()}
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

      <AnimatePresence>
        {statusLabel ? (
          <AnalysisStatusBar
            key="eye-status"
            label={statusLabel}
            accent="amber"
            step={statusStep}
            totalSteps={3}
          />
        ) : null}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        {showCompetitorSkeleton ? (
          <FadeInBlock
            key="eye-competitors-skeleton"
            className="border-t border-white/8 pt-3"
            aria-busy="true"
          >
            <EyeCompetitorsSkeleton count={TOP_N} />
          </FadeInBlock>
        ) : null}
      </AnimatePresence>

      {hasResults ? (
        <div className="max-h-[28rem] space-y-3 overflow-y-auto overscroll-contain border-t border-white/8 pt-3 pr-0.5">
          {competitors.length > 0 ? (
            <FadeInBlock className="space-y-2">
              <div className="flex items-baseline justify-between gap-2">
                <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                  {t("editor.eyeTopCompetitors")}
                </h4>
                <span className="text-[10px] text-muted-foreground">
                  {t("editor.eyeAnalyzed", {
                    count: String(competitors.length),
                  })}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                {competitors.map((card) => (
                  <CompetitorThumb
                    key={`${card.rank}-${card.article}`}
                    card={card}
                    isLeader={
                      leaderRevenue != null &&
                      card.estimated_revenue_rub === leaderRevenue
                    }
                    revenueLabel={t("editor.eyeEstimatedRevenue")}
                  />
                ))}
              </div>
            </FadeInBlock>
          ) : null}

          <AnimatePresence mode="wait">
            {showInsightsSkeleton ? (
              <FadeInBlock key="eye-insights-skeleton" aria-busy="true">
                <EyeInsightsSkeleton />
              </FadeInBlock>
            ) : (
              <FadeInBlock key="eye-insights" className="space-y-3">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    <MessageSquareWarning
                      className="size-3 text-amber"
                      aria-hidden
                    />
                    <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                      {t("editor.eyeCustomerPains")}
                    </h4>
                  </div>
                  {pains.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground/80">
                      {t("editor.eyeEmpty")}
                    </p>
                  ) : (
                    <ul className="space-y-1.5">
                      {pains.map((pain) => (
                        <li
                          key={pain.rank}
                          className="rounded-md border border-white/8 bg-white/[0.03] px-2.5 py-2"
                        >
                          <p className="text-[11px] font-medium text-foreground/95">
                            <span className="mr-1 font-mono text-amber/90">
                              {pain.rank}.
                            </span>
                            {pain.title}
                          </p>
                          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                            {pain.summary}
                          </p>
                          {pain.evidence_quotes.length > 0 ? (
                            <p className="mt-1.5 line-clamp-2 text-[10px] italic text-muted-foreground/75">
                              {t("editor.eyeEvidence")}: «
                              {pain.evidence_quotes.slice(0, 2).join("»; «")}»
                            </p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    <Sparkles className="size-3 text-emerald" aria-hidden />
                    <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                      {t("editor.eyeBadgeRecommendations")}
                    </h4>
                  </div>
                  {recommendations.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground/80">
                      {t("editor.eyeEmpty")}
                    </p>
                  ) : (
                    <>
                      <ul className="space-y-1">
                        {recommendations.map((item) => {
                          const linkedPain = pains.find(
                            (pain) => pain.rank === item.pain_rank,
                          )
                          return (
                            <li
                              key={`${item.pain_rank}-${item.offer_text}`}
                              className="rounded-md border border-emerald/25 bg-emerald/10 px-2.5 py-2"
                            >
                              <p className="text-[11px] font-medium text-foreground/95">
                                {item.offer_text}
                              </p>
                              {linkedPain ? (
                                <p className="mt-0.5 text-[10px] text-muted-foreground">
                                  → {linkedPain.title}
                                </p>
                              ) : null}
                            </li>
                          )
                        })}
                      </ul>
                      <Button
                        type="button"
                        size="sm"
                        disabled={locked}
                        className="mt-1 h-7 w-full gap-1 text-[10px]"
                        onClick={applyBadges}
                      >
                        <BadgeCheck className="size-3" aria-hidden />
                        {t("editor.eyeApplyBadges")}
                      </Button>
                    </>
                  )}
                </div>
              </FadeInBlock>
            )}
          </AnimatePresence>
        </div>
      ) : null}
    </section>
  )
}

export { EyeOfGodSection }
