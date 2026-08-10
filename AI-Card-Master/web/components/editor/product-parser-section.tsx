"use client"

import { AnimatePresence } from "framer-motion"
import { Loader2, PackageSearch } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import {
  AnalysisStatusBar,
  FadeInBlock,
  ProductMetaSkeleton,
} from "@/components/editor/analysis-loading"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  categoryFromCharacteristics,
  fetchProductByArticle,
  getApiErrorMessage,
  isAntibotDetectedError,
} from "@/lib/api"
import { seedAiPromptFromProduct } from "@/lib/editor/canvas-actions"
import { useI18n } from "@/lib/i18n"
import { ANTIBOT_USER_MESSAGE } from "@/lib/parser/antibot"
import { useEditorStore } from "@/lib/store/editor-store"

const PARSER_STATUS_KEYS = [
  "editor.parserStatusCollecting",
  "editor.parserStatusReading",
  "editor.parserStatusFilling",
] as const

function ProductParserSection() {
  const { t } = useI18n()
  const productMeta = useEditorStore((s) => s.productMeta)
  const setProductMeta = useEditorStore((s) => s.setProductMeta)
  const applyParsedProduct = useEditorStore((s) => s.applyParsedProduct)
  const setAiStudioBusy = useEditorStore((s) => s.setAiStudioBusy)
  const generating = useEditorStore((s) => s.busyKind === "generating")

  const [articleInput, setArticleInput] = useState("")
  const [parsing, setParsing] = useState(false)
  const [statusStep, setStatusStep] = useState(0)
  const parsingRef = useRef(false)
  const requestIdRef = useRef(0)

  const locked = parsing || generating

  useEffect(() => {
    parsingRef.current = parsing
  }, [parsing])

  useEffect(() => {
    return () => {
      // Invalidate in-flight parse so late responses skip setState.
      requestIdRef.current += 1
      if (parsingRef.current) setAiStudioBusy(false)
    }
  }, [setAiStudioBusy])

  useEffect(() => {
    if (!parsing) return

    const timers = [
      window.setTimeout(() => setStatusStep(1), 4500),
      window.setTimeout(() => setStatusStep(2), 10000),
    ]
    return () => {
      for (const id of timers) window.clearTimeout(id)
    }
  }, [parsing])

  const handleParse = async () => {
    const value = articleInput.trim()
    if (!value) {
      toast.error(t("editor.parserInputRequired"))
      return
    }
    if (parsing) return

    const requestId = ++requestIdRef.current
    setStatusStep(0)
    setParsing(true)
    setAiStudioBusy(true)
    try {
      const product = await fetchProductByArticle(value, "auto")
      if (requestId !== requestIdRef.current) return

      const images = [
        ...(product.image_urls ?? []),
        ...(product.source_image_urls ?? []),
      ].filter((url, index, all) => url && all.indexOf(url) === index)

      const name = (product.name || product.title || "").trim()
      const category =
        (product.category || "").trim() ||
        categoryFromCharacteristics(product.characteristics)

      const brand = product.brand ?? ""
      const description = product.description ?? ""

      applyParsedProduct({
        images,
        title: name,
        category,
        brand,
        description,
      })
      seedAiPromptFromProduct({
        title: name,
        category,
        brand,
        description,
      })

      if (images.length === 0) {
        toast.message(t("editor.parserSuccessNoImages", { title: name }))
      } else {
        toast.success(
          t("editor.parserSuccess", {
            title: name,
            count: String(images.length),
          }),
        )
      }
    } catch (error) {
      if (requestId !== requestIdRef.current) return
      // Antibot: keep form fields untouched for manual entry (no garbage title).
      if (isAntibotDetectedError(error)) {
        toast.error(
          getApiErrorMessage(error, ANTIBOT_USER_MESSAGE),
          { description: t("editor.parserAntibotHint") },
        )
        return
      }
      toast.error(getApiErrorMessage(error, t("editor.parserError")), {
        description: t("editor.parserErrorHint"),
      })
    } finally {
      if (requestId !== requestIdRef.current) return
      setParsing(false)
      setAiStudioBusy(false)
    }
  }

  const statusLabel = t(PARSER_STATUS_KEYS[statusStep] ?? PARSER_STATUS_KEYS[0])

  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2">
        <PackageSearch className="size-4 text-emerald" aria-hidden />
        <h3 className="font-heading text-sm font-semibold tracking-tight">
          {t("editor.parserTitle")}
        </h3>
      </div>

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        {t("editor.parserHint")}
      </p>

      <div className="flex flex-col gap-2">
        <Input
          value={articleInput}
          onChange={(e) => setArticleInput(e.target.value)}
          placeholder={t("editor.parserPlaceholder")}
          aria-label={t("editor.parserPlaceholder")}
          disabled={locked}
          className="h-9 border-white/10 bg-white/[0.04] text-xs"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !locked) void handleParse()
          }}
        />
        <Button
          type="button"
          size="sm"
          disabled={locked}
          aria-busy={parsing}
          onClick={() => void handleParse()}
          className="w-full gap-1.5"
        >
          {parsing ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <PackageSearch className="size-3.5" aria-hidden />
          )}
          {parsing ? t("editor.parserParsing") : t("editor.parserAction")}
        </Button>
      </div>

      <AnimatePresence mode="wait">
        {parsing ? (
          <AnalysisStatusBar
            key="parser-status"
            label={statusLabel}
            accent="emerald"
            step={statusStep + 1}
            totalSteps={PARSER_STATUS_KEYS.length}
          />
        ) : null}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        {parsing ? (
          <FadeInBlock
            key="parser-skeleton"
            aria-busy="true"
            aria-live="polite"
          >
            <ProductMetaSkeleton />
          </FadeInBlock>
        ) : (
          <FadeInBlock
            key="parser-form"
            className="space-y-2 border-t border-white/8 pt-2.5"
          >
            <label className="block space-y-1">
              <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                {t("editor.parserProductTitle")}
              </span>
              <Input
                value={productMeta.title}
                onChange={(e) => setProductMeta({ title: e.target.value })}
                placeholder={t("editor.parserProductTitlePlaceholder")}
                disabled={locked}
                className="h-8 border-white/10 bg-white/[0.04] text-xs"
              />
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label className="block space-y-1">
                <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                  {t("editor.parserCategory")}
                </span>
                <Input
                  value={productMeta.category}
                  onChange={(e) => setProductMeta({ category: e.target.value })}
                  placeholder={t("editor.parserCategoryPlaceholder")}
                  disabled={locked}
                  className="h-8 border-white/10 bg-white/[0.04] text-xs"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                  {t("editor.parserBrand")}
                </span>
                <Input
                  value={productMeta.brand}
                  onChange={(e) => setProductMeta({ brand: e.target.value })}
                  placeholder={t("editor.parserBrandPlaceholder")}
                  disabled={locked}
                  className="h-8 border-white/10 bg-white/[0.04] text-xs"
                />
              </label>
            </div>

            <label className="block space-y-1">
              <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                {t("editor.parserDescription")}
              </span>
              <Textarea
                value={productMeta.description}
                onChange={(e) =>
                  setProductMeta({ description: e.target.value })
                }
                placeholder={t("editor.parserDescriptionPlaceholder")}
                rows={4}
                disabled={locked}
                className="min-h-[5.5rem] resize-y border-white/10 bg-white/[0.04] text-xs"
              />
            </label>
          </FadeInBlock>
        )}
      </AnimatePresence>
    </section>
  )
}

export { ProductParserSection }
