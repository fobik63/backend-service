import type { ParsedCharacteristic, ParsedProduct } from "@/lib/parser/types"

/** Normalized product fields returned to the editor frontend. */
export type NormalizedProductFields = {
  name: string
  brand: string
  category: string
  description: string
}

const EMPTY_FIELDS: NormalizedProductFields = {
  name: "",
  brand: "",
  category: "",
  description: "",
}

export function normalizeProductFields(
  partial: Partial<NormalizedProductFields>,
): NormalizedProductFields {
  return {
    name: cleanText(partial.name) || "",
    brand: cleanText(partial.brand) || "",
    category: cleanText(partial.category) || "",
    description: cleanText(partial.description) || "",
  }
}

export function buildParsedProduct(input: {
  marketplace: ParsedProduct["marketplace"]
  sku: string
  productUrl: string
  fields: Partial<NormalizedProductFields>
  characteristics?: ParsedCharacteristic[]
  imageUrls?: string[]
  cached?: boolean
}): ParsedProduct {
  const fields = normalizeProductFields(input.fields)
  const characteristics = ensureCategoryCharacteristic(
    input.characteristics ?? [],
    fields.category,
  )
  const images = (input.imageUrls ?? []).filter(Boolean)

  return {
    marketplace: input.marketplace,
    sku: input.sku,
    product_url: input.productUrl,
    // Canonical normalized fields
    name: fields.name,
    brand: fields.brand || null,
    category: fields.category,
    description: fields.description || null,
    // Backward-compatible alias used by existing editor code
    title: fields.name,
    characteristics,
    image_urls: images,
    source_image_urls: images,
    cached: input.cached ?? false,
  }
}

export function categoryFromCharacteristics(
  characteristics: ParsedCharacteristic[] | undefined,
  fallback = "",
): string {
  const found = characteristics?.find((row) =>
    /категор|category|предмет|тип\s*товара/i.test(row.name),
  )?.value
  return cleanText(found) || fallback
}

export function brandFromCharacteristics(
  characteristics: ParsedCharacteristic[] | undefined,
): string {
  const found = characteristics?.find((row) =>
    /бренд|brand|торговая\s*марка|марка/i.test(row.name),
  )?.value
  return cleanText(found) || ""
}

export function cleanText(value: unknown): string {
  if (typeof value !== "string") return ""
  return value.replace(/\s+/g, " ").trim()
}

export function stripHtml(value: string): string {
  return cleanText(value.replace(/<[^>]+>/g, " "))
}

function ensureCategoryCharacteristic(
  rows: ParsedCharacteristic[],
  category: string,
): ParsedCharacteristic[] {
  if (!category) return rows
  const hasCategory = rows.some((row) =>
    /категор|category|предмет/i.test(row.name),
  )
  if (hasCategory) return rows
  return [{ name: "Категория", value: category }, ...rows]
}

export { EMPTY_FIELDS }
