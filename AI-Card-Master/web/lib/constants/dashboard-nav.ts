import {
  Coins,
  FolderKanban,
  ImagePlus,
  Settings,
  type LucideIcon,
} from "lucide-react"

export type DashboardNavId =
  | "projects"
  | "editor"
  | "pricing"
  | "settings"

export type DashboardNavItem = {
  href: string
  id: DashboardNavId
  /** Fallback RU label — prefer i18n `nav.{id}` at render time. */
  label: string
  icon: LucideIcon
}

export const DASHBOARD_NAV: DashboardNavItem[] = [
  {
    href: "/projects",
    id: "projects",
    label: "Мои проекты",
    icon: FolderKanban,
  },
  {
    href: "/editor",
    id: "editor",
    label: "Создать карточку",
    icon: ImagePlus,
  },
  {
    href: "/pricing",
    id: "pricing",
    label: "Тарифы и баланс",
    icon: Coins,
  },
  {
    href: "/settings",
    id: "settings",
    label: "Настройки",
    icon: Settings,
  },
]

/** Breadcrumb i18n key by path segment (`nav.*`). */
export const DASHBOARD_BREADCRUMB_KEYS: Record<string, string> = {
  dashboard: "nav.dashboard",
  projects: "nav.projects",
  editor: "nav.editor",
  create: "nav.editor",
  pricing: "nav.pricing",
  billing: "nav.pricing",
  settings: "nav.settings",
}

/** @deprecated Prefer DASHBOARD_BREADCRUMB_KEYS + useI18n */
export const DASHBOARD_BREADCRUMB_LABELS: Record<string, string> = {
  dashboard: "Кабинет",
  projects: "Мои проекты",
  editor: "Создать карточку",
  create: "Создать карточку",
  pricing: "Тарифы и баланс",
  billing: "Тарифы и баланс",
  settings: "Настройки",
}
