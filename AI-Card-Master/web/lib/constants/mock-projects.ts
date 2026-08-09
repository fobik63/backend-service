import type { EditorDocumentDTO } from "@/types/api"

export type ProjectMarketplace = "ozon" | "wb"

export type ProjectStatus = "ready" | "processing"

export type Project = {
  id: string
  title: string
  marketplace: ProjectMarketplace
  status: ProjectStatus
  createdAt: string
  /** Marketplace-style card preview (local Unsplash-quality photo) */
  previewImage: string
  /**
   * Isolated transparent product cutout for the editor canvas.
   * Falls back to `previewImage` when omitted.
   */
  productImage?: string
  accentLabel: string
  editorDocument?: EditorDocumentDTO | null
}

export const MOCK_PROJECTS: Project[] = [
  {
    id: "prj_01",
    title: "Крем для рук «Sage Mist»",
    marketplace: "ozon",
    status: "ready",
    createdAt: "2026-08-02T10:24:00.000Z",
    previewImage: "/projects/cream-sage-mist.png",
    productImage: "/projects/cream-sage-mist-product.png",
    accentLabel: "Уход",
  },
  {
    id: "prj_02",
    title: "Масло арганы Cold Press",
    marketplace: "wb",
    status: "ready",
    createdAt: "2026-08-05T14:08:00.000Z",
    previewImage: "/projects/oil-argan.png",
    accentLabel: "Масла",
  },
  {
    id: "prj_03",
    title: "Свеча «Cedar & Copper»",
    marketplace: "ozon",
    status: "processing",
    createdAt: "2026-08-07T09:40:00.000Z",
    previewImage: "/projects/candle-cedar.png",
    accentLabel: "Home",
  },
  {
    id: "prj_04",
    title: "Духи / Парфюм «Noir Amber»",
    marketplace: "wb",
    status: "ready",
    createdAt: "2026-07-28T16:55:00.000Z",
    previewImage: "/projects/perfume.png",
    accentLabel: "Аромат",
  },
  {
    id: "prj_05",
    title: "Карандаши / Канцелярия Studio Set",
    marketplace: "ozon",
    status: "processing",
    createdAt: "2026-08-08T08:12:00.000Z",
    previewImage: "/projects/stationery.png",
    accentLabel: "Канцелярия",
  },
  {
    id: "prj_06",
    title: "Кроссовки NEXORA Run",
    marketplace: "wb",
    status: "ready",
    createdAt: "2026-07-19T11:30:00.000Z",
    previewImage: "/projects/sneakers.png",
    accentLabel: "Обувь",
  },
]
