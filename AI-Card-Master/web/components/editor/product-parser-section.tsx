"use client"

import { Loader2, PackageSearch } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  categoryFromCharacteristics,
  fetchProductByArticle,
  getApiErrorMessage,
} from "@/lib/api"
import { useI18n } from "@/lib/i18n"
import { useEditorStore } from "@/lib/store/editor-store"

function ProductParserSection() {
  const { t } = useI18n()
  const productMeta = useEditorStore((s) => s.productMeta)
  const setProductMeta = useEditorStore((s) => s.setProductMeta)
  const applyParsedProduct = useEditorStore((s) => s.applyParsedProduct)

  const [articleInput, setArticleInput] = useState("")
  const [parsing, setParsing] = useState(false)

  const handleParse = async () => {
    const value = articleInput.trim()
    if (!value) {
      toast.error(t("editor.parserInputRequired"))
      return
    }

    setParsing(true)
    try {
      const product = await fetchProductByArticle(value, "auto")
      const images = [
        ...(product.image_urls ?? []),
        ...(product.source_image_urls ?? []),
      ].filter((url, index, all) => url && all.indexOf(url) === index)

      if (images.length === 0) {
        toast.error(t("editor.parserNoImages"))
        return
      }

      applyParsedProduct({
        images,
        title: product.title,
        category: categoryFromCharacteristics(product.characteristics),
        brand: product.brand ?? "",
        description: product.description ?? "",
      })
      toast.success(
        t("editor.parserSuccess", {
          title: product.title,
          count: String(images.length),
        }),
      )
    } catch (error) {
      toast.error(getApiErrorMessage(error, t("editor.parserError")))
    } finally {
      setParsing(false)
    }
  }

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
          className="h-9 border-white/10 bg-white/[0.04] text-xs"
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleParse()
          }}
        />
        <Button
          type="button"
          size="sm"
          disabled={parsing}
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

      <div className="space-y-2 border-t border-white/8 pt-2.5">
        <label className="block space-y-1">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("editor.parserProductTitle")}
          </span>
          <Input
            value={productMeta.title}
            onChange={(e) => setProductMeta({ title: e.target.value })}
            placeholder={t("editor.parserProductTitlePlaceholder")}
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
            onChange={(e) => setProductMeta({ description: e.target.value })}
            placeholder={t("editor.parserDescriptionPlaceholder")}
            rows={4}
            className="min-h-[5.5rem] resize-y border-white/10 bg-white/[0.04] text-xs"
          />
        </label>
      </div>
    </section>
  )
}

export { ProductParserSection }
