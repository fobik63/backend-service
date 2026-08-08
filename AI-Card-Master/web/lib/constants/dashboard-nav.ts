import {
  Coins,
  FolderKanban,
  ImagePlus,
  Lightbulb,
  Rotate3d,
  Settings,
  type LucideIcon,
} from "lucide-react"

export type DashboardNavItem = {
  href: string
  label: string
  icon: LucideIcon
}

export const DASHBOARD_NAV: DashboardNavItem[] = [
  {
    href: "/projects",
    label: "Мои проекты",
    icon: FolderKanban,
  },
  {
    href: "/dashboard/create",
    label: "Создать карточку",
    icon: ImagePlus,
  },
  {
    href: "/dashboard/photo-studio",
    label: "Фотостудия (Свет)",
    icon: Lightbulb,
  },
  {
    href: "/dashboard/360",
    label: "360° Генерация",
    icon: Rotate3d,
  },
  {
    href: "/dashboard/billing",
    label: "Тарифы и баланс",
    icon: Coins,
  },
  {
    href: "/dashboard/settings",
    label: "Настройки",
    icon: Settings,
  },
]

/** Breadcrumb labels by path segment. */
export const DASHBOARD_BREADCRUMB_LABELS: Record<string, string> = {
  dashboard: "Кабинет",
  projects: "Мои проекты",
  create: "Создать карточку",
  "photo-studio": "Фотостудия",
  "360": "360° Генерация",
  billing: "Тарифы и баланс",
  settings: "Настройки",
}
