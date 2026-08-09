"use client"

import {
  Check,
  Copy,
  Loader2,
  PackageOpen,
  Sparkles,
  Upload,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  categoryFromCharacteristics,
  fetchProductByArticle,
  generateSeoDescription,
  getApiErrorMessage,
  listSellerProducts,
  publishToOzon,
  publishToWildberries,
  type SellerProductDTO,
  type SeoTargetPlatform,
} from "@/lib/api"
import { addBadgeToCanvas, seedAiPromptFromProduct } from "@/lib/editor/canvas-actions"
import { useEditorStore } from "@/lib/store/editor-store"
import { cn } from "@/lib/utils"

type ImportPublishDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectTitle?: string
}

type PublishPhase = "idle" | "loading" | "success" | "error"

function httpsImageUrls(urls: string[]): string[] {
  return urls.filter((url) => /^https:\/\//i.test(url))
}

function ImportPublishDialog({
  open,
  onOpenChange,
  projectTitle,
}: ImportPublishDialogProps) {
  const applyParsedProduct = useEditorStore((s) => s.applyParsedProduct)
  const importGalleryUrls = useEditorStore((s) => s.importGalleryUrls)
  const productPreviewUrl = useEditorStore((s) => s.productPreviewUrl)
  const productMeta = useEditorStore((s) => s.productMeta)
  const setProductPreviewUrl = useEditorStore((s) => s.setProductPreviewUrl)

  const [articleInput, setArticleInput] = useState("")
  const [importing, setImporting] = useState(false)
  const [importedTitle, setImportedTitle] = useState<string | null>(null)
  const [importedCategory, setImportedCategory] = useState("Товары")
  const [importedFeatures, setImportedFeatures] = useState<
    Record<string, string>
  >({})

  const [seoPlatform, setSeoPlatform] = useState<SeoTargetPlatform>("wb")
  const [seoLoading, setSeoLoading] = useState(false)
  const [seoTitle, setSeoTitle] = useState("")
  const [seoBenefits, setSeoBenefits] = useState<string[]>([])
  const [seoDescription, setSeoDescription] = useState("")

  // Keep dialog SEO seed in sync with the panel parser / store meta.
  useEffect(() => {
    if (!open) return
    if (productMeta.title) {
      setImportedTitle(productMeta.title)
      setSeoTitle((prev) => prev || productMeta.title)
    }
    if (productMeta.category) setImportedCategory(productMeta.category)
    if (productMeta.description) {
      setSeoDescription((prev) => prev || productMeta.description)
    }
  }, [open, productMeta.title, productMeta.category, productMeta.description])

  const [publishPlatform, setPublishPlatform] =
    useState<SeoTargetPlatform>("wb")
  const [products, setProducts] = useState<SellerProductDTO[]>([])
  const [productsLoading, setProductsLoading] = useState(false)
  const [selectedProductId, setSelectedProductId] = useState("")
  const [publishPhase, setPublishPhase] = useState<PublishPhase>("idle")
  const [publishMessage, setPublishMessage] = useState<string | null>(null)
  const productsFetchKey = open ? publishPlatform : null
  const [activeProductsFetchKey, setActiveProductsFetchKey] = useState<
    string | null
  >(null)

  // Reset loading when the dialog opens or marketplace changes (React-recommended
  // adjust-state-during-render; avoids sync setState inside an effect).
  if (productsFetchKey !== activeProductsFetchKey) {
    setActiveProductsFetchKey(productsFetchKey)
    setProductsLoading(productsFetchKey !== null)
    if (productsFetchKey === null) {
      setProducts([])
    }
  }

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void listSellerProducts(publishPlatform)
      .then((items) => {
        if (cancelled) return
        setProducts(items)
        setSelectedProductId((prev) =>
          items.some((item) => item.product_id === prev)
            ? prev
            : (items[0]?.product_id ?? ""),
        )
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setProducts([])
        setSelectedProductId("")
        toast.error(
          getApiErrorMessage(
            error,
            "Не удалось загрузить список товаров. Проверьте API-ключи в настройках.",
          ),
        )
      })
      .finally(() => {
        if (!cancelled) setProductsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, publishPlatform])

  const galleryPreview = useMemo(() => {
    if (importGalleryUrls.length > 0) return importGalleryUrls
    return productPreviewUrl ? [productPreviewUrl] : []
  }, [importGalleryUrls, productPreviewUrl])

  const handleImport = async () => {
    const value = articleInput.trim()
    if (!value) {
      toast.error("Введите ссылку или артикул товара")
      return
    }
    setImporting(true)
    try {
      const product = await fetchProductByArticle(value, "auto")
      const images = [
        ...(product.image_urls ?? []),
        ...(product.source_image_urls ?? []),
      ].filter((url, index, all) => url && all.indexOf(url) === index)

      if (images.length === 0) {
        toast.error("У товара не найдены изображения")
        return
      }

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
      setImportedTitle(name)
      setImportedCategory(category)
      const features: Record<string, string> = {}
      for (const row of product.characteristics ?? []) {
        if (row.name && row.value) features[row.name] = row.value
      }
      setImportedFeatures(features)
      if (!seoTitle) setSeoTitle(name)
      if (!seoDescription && product.description) {
        setSeoDescription(product.description)
      }
      toast.success(`Импортировано: ${name} (${images.length} фото)`)
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Не удалось импортировать товар"))
    } finally {
      setImporting(false)
    }
  }

  const handleGenerateSeo = async () => {
    const title = (seoTitle || importedTitle || projectTitle || "").trim()
    if (!title) {
      toast.error("Укажите название товара для SEO-генерации")
      return
    }
    setSeoLoading(true)
    try {
      const result = await generateSeoDescription({
        title,
        category: importedCategory || "Товары",
        features: importedFeatures,
        targetPlatform: seoPlatform,
      })
      setSeoTitle(result.optimized_title)
      setSeoBenefits(result.benefits)
      setSeoDescription(result.description)
      toast.success(
        `SEO готово (−${result.coins_charged} коинов, баланс ${result.new_balance})`,
      )
    } catch (error) {
      toast.error(
        getApiErrorMessage(error, "Не удалось сгенерировать SEO-описание"),
      )
    } finally {
      setSeoLoading(false)
    }
  }

  const handleCopySeo = async () => {
    const text = [
      seoTitle ? `Оффер:\n${seoTitle}` : "",
      seoBenefits.length > 0
        ? `Ключевые теги:\n${seoBenefits.map((b) => `• ${b}`).join("\n")}`
        : "",
      seoDescription ? `Подробное описание:\n${seoDescription}` : "",
    ]
      .filter(Boolean)
      .join("\n\n")
    if (!text.trim()) return
    try {
      await navigator.clipboard.writeText(text)
      toast.success("SEO-текст скопирован")
    } catch {
      toast.error("Не удалось скопировать текст")
    }
  }

  const handleApplyBullets = () => {
    if (seoBenefits.length === 0) {
      toast.error("Сначала сгенерируйте SEO-описание")
      return
    }
    let created = 0
    for (const benefit of seoBenefits) {
      const result = addBadgeToCanvas({
        label: benefit.slice(0, 48),
        bgColor: "rgba(15,17,21,0.55)",
        iconId: "icon_spark",
        variant: "glass",
        blur: 12,
        textColor: "#FFFFFF",
        borderRadius: 14,
      })
      if (result.created) created += 1
    }
    toast.success(
      created > 0
        ? `На холст добавлено плашек: ${created}`
        : "Плашки уже есть на холсте",
    )
  }

  const handlePublish = async () => {
    if (!selectedProductId) {
      toast.error("Выберите артикул товара")
      return
    }
    const images = httpsImageUrls(galleryPreview)
    if (images.length === 0) {
      toast.error(
        "Нужны публичные HTTPS-ссылки на изображения (импортируйте товар или загрузите CDN-фото)",
      )
      return
    }
    const seoText = (seoDescription || seoBenefits.join("\n") || "").trim()
    if (!seoText) {
      toast.error("Сгенерируйте или введите SEO-описание перед публикацией")
      return
    }

    setPublishPhase("loading")
    setPublishMessage(null)
    try {
      const result =
        publishPlatform === "wb"
          ? await publishToWildberries({
              nm_id: Number(selectedProductId),
              image_urls: images.slice(0, 30),
              seo_text: seoText.slice(0, 5000),
              title: seoTitle || undefined,
            })
          : await publishToOzon({
              product_id: Number(selectedProductId),
              image_urls: images.slice(0, 15),
              description: seoText.slice(0, 10_000),
            })

      if (result.status === "Failed") {
        setPublishPhase("error")
        setPublishMessage(result.message)
        toast.error(result.message || "Ошибка публикации")
        return
      }
      setPublishPhase("success")
      setPublishMessage(result.message)
      toast.success(
        result.status === "Pending"
          ? "Публикация отправлена (ожидает синхронизации кабинета)"
          : "Карточка успешно опубликована",
      )
    } catch (error) {
      setPublishPhase("error")
      const message = getApiErrorMessage(error, "Ошибка публикации")
      setPublishMessage(message)
      toast.error(message)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[min(92vh,920px)] w-full overflow-y-auto sm:max-w-2xl"
        showCloseButton
      >
        <DialogHeader>
          <DialogTitle>Импорт и Постинг</DialogTitle>
          <DialogDescription>
            Импорт по артикулу, SEO-копирайтер и публикация на WB / Ozon
          </DialogDescription>
        </DialogHeader>

        <section className="space-y-2.5 rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center gap-2">
            <PackageOpen className="size-4 text-emerald" aria-hidden />
            <h3 className="font-heading text-sm font-semibold">
              Импорт по Артикулу
            </h3>
          </div>
          <div className="flex gap-2">
            <Input
              value={articleInput}
              onChange={(e) => setArticleInput(e.target.value)}
              placeholder="Ссылка или артикул WB / Ozon"
              className="h-9 border-white/10 bg-white/[0.04] text-xs"
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleImport()
              }}
            />
            <Button
              type="button"
              size="sm"
              disabled={importing}
              onClick={() => void handleImport()}
              className="shrink-0 gap-1.5"
            >
              {importing ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Upload className="size-3.5" aria-hidden />
              )}
              Загрузить
            </Button>
          </div>
          {galleryPreview.length > 0 ? (
            <div className="flex gap-2 overflow-x-auto pb-0.5">
              {galleryPreview.slice(0, 12).map((url) => {
                const active = url === productPreviewUrl
                return (
                  <button
                    key={url}
                    type="button"
                    onClick={() => setProductPreviewUrl(url)}
                    className={cn(
                      "relative size-14 shrink-0 overflow-hidden rounded-md border",
                      active
                        ? "border-white/40 ring-1 ring-white/25"
                        : "border-white/10",
                    )}
                    title="Показать на холсте"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={url}
                      alt=""
                      className="size-full object-cover"
                    />
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-white/12 px-3 py-4 text-center">
              <p className="text-[11px] text-muted-foreground">
                Галерея пуста — загрузите артикул или URL, чтобы увидеть превью
              </p>
            </div>
          )}
        </section>

        <section className="space-y-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-muted-foreground" aria-hidden />
              <h3 className="font-heading text-sm font-semibold">
                AI SEO-Копирайтер
              </h3>
            </div>
            <div className="flex gap-1">
              {(["wb", "ozon"] as const).map((platform) => (
                <button
                  key={platform}
                  type="button"
                  onClick={() => setSeoPlatform(platform)}
                  className={cn(
                    "rounded-md border px-2 py-1 text-[10px] font-medium uppercase",
                    seoPlatform === platform
                      ? "border-white/25 bg-white/10 text-foreground"
                      : "border-white/10 text-muted-foreground",
                  )}
                >
                  {platform}
                </button>
              ))}
            </div>
          </div>

          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Продающий текст о товаре для карточки WB / Ozon — без описания
            дизайна и визуала фото.
          </p>

          <label className="block space-y-1.5">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Оффер
            </span>
            <Input
              value={seoTitle}
              onChange={(e) => setSeoTitle(e.target.value)}
              placeholder="Название товара или готовый оффер с ключевыми словами"
              className="h-9 border-white/10 bg-white/[0.04] text-xs"
            />
          </label>

          <Button
            type="button"
            size="sm"
            disabled={seoLoading}
            onClick={() => void handleGenerateSeo()}
            className="w-full gap-1.5"
          >
            {seoLoading ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="size-3.5" aria-hidden />
            )}
            Сгенерировать SEO-описание
          </Button>

          <div className="space-y-1.5">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Ключевые теги
            </span>
            {seoBenefits.length > 0 ? (
              <div className="flex flex-wrap gap-1.5 rounded-lg border border-white/8 bg-black/20 p-2.5">
                {seoBenefits.map((benefit) => (
                  <span
                    key={benefit}
                    className="rounded-md border border-white/12 bg-white/[0.06] px-2 py-1 text-[11px] text-foreground/90"
                  >
                    {benefit}
                  </span>
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-white/12 px-3 py-3 text-center">
                <p className="text-[11px] text-muted-foreground">
                  После генерации здесь появятся ключевые теги и УТП
                </p>
              </div>
            )}
          </div>

          <label className="block space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                Подробное описание
              </span>
              {seoDescription ? (
                <span className="text-[10px] tabular-nums text-muted-foreground">
                  {seoDescription.length} симв.
                </span>
              ) : null}
            </div>
            <Textarea
              value={seoDescription}
              onChange={(e) => setSeoDescription(e.target.value)}
              placeholder="Подробное продающее SEO-описание товара (800–1200 символов)…"
              className="min-h-44 resize-y border-white/10 bg-white/[0.04] text-xs leading-relaxed"
            />
          </label>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!seoDescription && seoBenefits.length === 0}
              onClick={() => void handleCopySeo()}
              className="gap-1.5"
            >
              <Copy className="size-3.5" aria-hidden />
              Копировать
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={seoBenefits.length === 0}
              onClick={handleApplyBullets}
              className="gap-1.5"
            >
              Применить теги на холст
            </Button>
          </div>
        </section>

        <section className="space-y-2.5 rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-heading text-sm font-semibold">Публикация</h3>
            <div className="flex gap-1">
              {(["wb", "ozon"] as const).map((platform) => (
                <button
                  key={platform}
                  type="button"
                  onClick={() => {
                    setPublishPlatform(platform)
                    setPublishPhase("idle")
                    setPublishMessage(null)
                  }}
                  className={cn(
                    "rounded-md border px-2 py-1 text-[10px] font-medium uppercase",
                    publishPlatform === platform
                      ? "border-emerald/40 bg-emerald/15 text-emerald"
                      : "border-white/10 text-muted-foreground",
                  )}
                >
                  {platform === "wb" ? "Wildberries" : "Ozon"}
                </button>
              ))}
            </div>
          </div>

          <label className="block space-y-1.5">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Артикул товара
            </span>
            <select
              value={selectedProductId}
              disabled={productsLoading || products.length === 0}
              onChange={(e) => setSelectedProductId(e.target.value)}
              className="h-9 w-full rounded-lg border border-white/10 bg-white/[0.04] px-2.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
            >
              {productsLoading ? (
                <option value="">Загрузка…</option>
              ) : products.length === 0 ? (
                <option value="">Нет товаров — подключите API-ключи</option>
              ) : (
                products.map((product) => (
                  <option key={product.product_id} value={product.product_id}>
                    {product.product_id}
                    {product.vendor_code ? ` · ${product.vendor_code}` : ""}
                    {` — ${product.title}`}
                  </option>
                ))
              )}
            </select>
          </label>

          <Button
            type="button"
            size="sm"
            disabled={publishPhase === "loading" || !selectedProductId}
            onClick={() => void handlePublish()}
            className="w-full gap-1.5"
          >
            {publishPhase === "loading" ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : publishPhase === "success" ? (
              <Check className="size-3.5" aria-hidden />
            ) : null}
            Опубликовать на Маркетплейс
          </Button>

          {publishMessage ? (
            <p
              className={cn(
                "text-[11px]",
                publishPhase === "success" && "text-emerald",
                publishPhase === "error" && "text-destructive",
                publishPhase === "idle" && "text-muted-foreground",
              )}
              role="status"
            >
              {publishMessage}
            </p>
          ) : null}
        </section>
      </DialogContent>
    </Dialog>
  )
}

export { ImportPublishDialog }
export type { ImportPublishDialogProps }
