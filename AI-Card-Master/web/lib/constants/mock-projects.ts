export type ProjectMarketplace = "ozon" | "wb"

export type ProjectStatus = "ready" | "processing"

export type Project = {
  id: string
  title: string
  marketplace: ProjectMarketplace
  status: ProjectStatus
  createdAt: string
  /** CSS gradient used as card preview until real assets are wired */
  previewGradient: string
  accentLabel: string
}

export const MOCK_PROJECTS: Project[] = [
  {
    id: "prj_01",
    title: "Крем для рук «Sage Mist»",
    marketplace: "ozon",
    status: "ready",
    createdAt: "2026-08-02T10:24:00.000Z",
    previewGradient:
      "linear-gradient(160deg, #1b3e2b 0%, #0f1115 48%, #2a2218 100%)",
    accentLabel: "Уход",
  },
  {
    id: "prj_02",
    title: "Масло арганы Cold Press",
    marketplace: "wb",
    status: "ready",
    createdAt: "2026-08-05T14:08:00.000Z",
    previewGradient:
      "linear-gradient(145deg, #2e4a38 0%, #16181e 42%, #3d2a1c 100%)",
    accentLabel: "Масла",
  },
  {
    id: "prj_03",
    title: "Свеча «Cedar & Copper»",
    marketplace: "ozon",
    status: "processing",
    createdAt: "2026-08-07T09:40:00.000Z",
    previewGradient:
      "linear-gradient(155deg, #1a2420 0%, #0f1115 50%, #4a3520 100%)",
    accentLabel: "Home",
  },
  {
    id: "prj_04",
    title: "Сыворотка с ниацинамидом",
    marketplace: "wb",
    status: "ready",
    createdAt: "2026-07-28T16:55:00.000Z",
    previewGradient:
      "linear-gradient(150deg, #163528 0%, #111318 45%, #2c2418 100%)",
    accentLabel: "Face",
  },
  {
    id: "prj_05",
    title: "Набор пробников Botanical",
    marketplace: "ozon",
    status: "processing",
    createdAt: "2026-08-08T08:12:00.000Z",
    previewGradient:
      "linear-gradient(165deg, #1f3328 0%, #0f1115 55%, #3a2e22 100%)",
    accentLabel: "Set",
  },
  {
    id: "prj_06",
    title: "Скраб кофейный «Roast»",
    marketplace: "wb",
    status: "ready",
    createdAt: "2026-07-19T11:30:00.000Z",
    previewGradient:
      "linear-gradient(140deg, #24352c 0%, #16181e 40%, #4a2f1c 100%)",
    accentLabel: "Body",
  },
]
