export type Locale = "ru" | "en"

type DictLeaf = string
type DictNode = { [key: string]: DictLeaf | DictNode }

export const dictionaries = {
  ru: {
    common: {
      language: "Язык",
      openMenu: "Открыть меню",
      closeMenu: "Закрыть меню",
      profile: "Профиль",
      settings: "Настройки",
      logout: "Выйти",
      notifications: "Уведомления",
      noNotifications: "Новых уведомлений нет",
      save: "Сохранить",
      saving: "Сохранение…",
      edit: "Редактировать",
      delete: "Удалить",
      ready: "Готово",
      processing: "В процессе",
    },
    nav: {
      projects: "Мои проекты",
      editor: "Создать карточку",
      pricing: "Тарифы и баланс",
      settings: "Настройки",
      dashboard: "Кабинет",
      ariaSidebar: "Навигация личного кабинета",
      breadcrumbs: "Хлебные крошки",
      coins: "Монеты",
      topUp: "Пополнить",
    },
    topBar: {
      languageSwitch: "Переключатель языка",
      profileMenu: "Меню профиля",
      russian: "Русский",
      english: "English",
    },
    projects: {
      title: "Мои проекты",
      subtitle:
        "Карточки товаров для Ozon и Wildberries — поиск, фильтры и быстрые действия",
      created: "Создан",
      downloadZip: "Скачать ZIP",
      deleted: "Проект удалён",
      loadError: "Не удалось загрузить проекты",
      showLocal: "Показать локальные данные",
      archiveReady: "Архив «{title}» скачан",
    },
    editor: {
      save: "Сохранить",
      saving: "Сохранение…",
      saved: "Проект сохранен",
      saveError: "Не удалось сохранить проект",
      backToProjects: "К проектам",
      returnToProjects: "Вернуться к проектам",
      productUnavailable: "Данные товара недоступны",
      initializing: "Инициализация редактора…",
      tools: "Параметры",
      toolsHint: "Точные настройки текста, света и генерации",
      tabProduct: "Товар и AI-Свет",
      tabInfographic: "Инфографика",
      tabText: "Текст и Пресеты",
      promptPlaceholder:
        "Опишите желаемый дизайн... (например: «Сделай заголовок синим шрифтом Inter, цену 12900 в красный бэйдж и перемести товар вправо»)",
      generate: "Сгенерировать",
      generating: "Генерация…",
      generateSuccess: "Карточка сгенерирована",
      generateError: "Не удалось сгенерировать карточку",
      promptRequired: "Введите описание дизайна",
      promptAria: "AI-промпт",
      promptBarAria: "AI-промпт и экспорт",
      promptSection: "AI Промпт и Экспорт",
      downloadPng: "Скачать Ultra-HD PNG",
      download: "Скачать текущую",
      downloadCurrentSuccess: "Скачана страница {n} ({format})",
      downloadCurrentError: "Не удалось скачать текущую страницу",
      exportFormat: "Формат экспорта",
      exportPng: "PNG 1080×1440",
      exportPngDesc: "Ultra-HD для маркетплейсов",
      exportWebp: "WebP",
      exportWebpDesc: "Лёгкий веб-формат",
      exportZip: "ZIP с исходниками",
      exportZipDesc: "Слои и ассеты проекта",
      canvas: "Холст",
      canvasArea: "Область предпросмотра",
      zoom: "Масштаб",
      pages: "Страницы сета",
      pagesAria: "Переключение страниц сета",
      pageN: "Страница {n}: {title}",
      pageNShort: "Стр. {n}",
      text: "Текст",
      textSelectHint: "Выберите текст на холсте",
      font: "Шрифт",
      fontSize: "Размер",
      softbox: "Софтбокс",
      softboxFull: "Софтбокс / Источник света",
      intensity: "Интенсивность",
      colorTemp: "Температура",
      colorTempWarm: "Тёплый",
      colorTempCold: "Холодный",
      colorTempNeutral: "Нейтральный",
      angle: "Угол",
      angleRight: "0° справа",
      angleLeft: "180° слева",
      elevation: "Высота",
      diffusion: "Размытие света",
      shadow: "Тень",
      textShadow: "Тень текста",
      shadowBlur: "Размытие",
      shadowColor: "Цвет тени",
      offsetX: "Смещение X",
      offsetY: "Смещение Y",
      blur: "Размытие",
      opacity: "Прозрачность",
      badge: "Плашка",
      badgeSelectHint: "Выберите плашку на холсте",
      badgeText: "Текст",
      badgeTextPlaceholder: "Текст плашки",
      badgeBgColor: "Цвет фона",
      badgeTextColor: "Цвет текста",
      badgeIcon: "Иконка",
      badgeGlassHint: "Glassmorphism: backdrop-blur поверх карточки",
      packGeneration: "Генерация сета",
      color: "Цвет",
      stroke: "Обводка",
      strokeWidth: "Толщина обводки",
      strokeColor: "Цвет обводки",
      featureChips: "Плашки преимуществ",
    },
    export: {
      downloadZip: "Скачать ZIP",
      zipShort: "ZIP",
      preparing: "Готовим архив…",
      packSize: "Количество фото",
      packPhotos: "{count} фото",
      packOption: "{count} фото в пакете",
      packCustom: "Своё",
      packCustomPlaceholder: "Число",
      success: "Скачан ZIP-пакет ({count} фото)",
      error: "Не удалось сформировать ZIP-архив",
    },
  },
  en: {
    common: {
      language: "Language",
      openMenu: "Open menu",
      closeMenu: "Close menu",
      profile: "Profile",
      settings: "Settings",
      logout: "Log out",
      notifications: "Notifications",
      noNotifications: "No new notifications",
      save: "Save",
      saving: "Saving…",
      edit: "Edit",
      delete: "Delete",
      ready: "Ready",
      processing: "Processing",
    },
    nav: {
      projects: "My projects",
      editor: "Create card",
      pricing: "Plans & balance",
      settings: "Settings",
      dashboard: "Dashboard",
      ariaSidebar: "Dashboard navigation",
      breadcrumbs: "Breadcrumbs",
      coins: "Coins",
      topUp: "Top up",
    },
    topBar: {
      languageSwitch: "Language switcher",
      profileMenu: "Profile menu",
      russian: "Русский",
      english: "English",
    },
    projects: {
      title: "My projects",
      subtitle:
        "Product cards for Ozon and Wildberries — search, filters, and quick actions",
      created: "Created",
      downloadZip: "Download ZIP",
      deleted: "Project deleted",
      loadError: "Failed to load projects",
      showLocal: "Show local data",
      archiveReady: "Archive “{title}” downloaded",
    },
    editor: {
      save: "Save",
      saving: "Saving…",
      saved: "Project saved",
      saveError: "Failed to save project",
      backToProjects: "Back to projects",
      returnToProjects: "Return to projects",
      productUnavailable: "Product data unavailable",
      initializing: "Initializing editor…",
      tools: "Parameters",
      toolsHint: "Precise text, light, and generation controls",
      tabProduct: "Product & AI Light",
      tabInfographic: "Infographic",
      tabText: "Text & Presets",
      promptPlaceholder:
        "Describe the desired design... (e.g. “Make the title blue in Inter, price 12900 in a red badge, move the product right”)",
      generate: "Generate",
      generating: "Generating…",
      generateSuccess: "Card generated",
      generateError: "Failed to generate card",
      promptRequired: "Enter a design description",
      promptAria: "AI prompt",
      promptBarAria: "AI prompt and export",
      promptSection: "AI Prompt & Export",
      downloadPng: "Download Ultra-HD PNG",
      download: "Download current",
      downloadCurrentSuccess: "Downloaded page {n} ({format})",
      downloadCurrentError: "Failed to download the current page",
      exportFormat: "Export format",
      exportPng: "PNG 1080×1440",
      exportPngDesc: "Ultra-HD for marketplaces",
      exportWebp: "WebP",
      exportWebpDesc: "Lightweight web format",
      exportZip: "ZIP with sources",
      exportZipDesc: "Project layers and assets",
      canvas: "Canvas",
      canvasArea: "Preview area",
      zoom: "Zoom",
      pages: "Pack pages",
      pagesAria: "Switch pack pages",
      pageN: "Page {n}: {title}",
      pageNShort: "Page {n}",
      text: "Text",
      textSelectHint: "Select text on the canvas",
      font: "Font",
      fontSize: "Size",
      softbox: "Softbox",
      softboxFull: "Softbox / Light Source",
      intensity: "Intensity",
      colorTemp: "Color Temperature",
      colorTempWarm: "Warm",
      colorTempCold: "Cold",
      colorTempNeutral: "Neutral",
      angle: "Angle",
      angleRight: "0° right",
      angleLeft: "180° left",
      elevation: "Elevation",
      diffusion: "Diffusion",
      shadow: "Shadow",
      textShadow: "Text Shadow",
      shadowBlur: "Blur",
      shadowColor: "Shadow Color",
      offsetX: "Offset X",
      offsetY: "Offset Y",
      blur: "Blur",
      opacity: "Opacity",
      badge: "Badge",
      badgeSelectHint: "Select a badge on the canvas",
      badgeText: "Text",
      badgeTextPlaceholder: "Badge text",
      badgeBgColor: "Background color",
      badgeTextColor: "Text color",
      badgeIcon: "Icon",
      badgeGlassHint: "Glassmorphism: backdrop-blur over the card",
      packGeneration: "Pack generation",
      color: "Color",
      stroke: "Stroke",
      strokeWidth: "Stroke width",
      strokeColor: "Stroke color",
      featureChips: "Feature Chips",
    },
    export: {
      downloadZip: "Download ZIP",
      zipShort: "ZIP",
      preparing: "Preparing archive…",
      packSize: "Photo count",
      packPhotos: "{count} photos",
      packOption: "{count} photos in pack",
      packCustom: "Custom",
      packCustomPlaceholder: "Count",
      success: "ZIP pack downloaded ({count} photos)",
      error: "Failed to build ZIP archive",
    },
  },
} as const satisfies Record<Locale, DictNode>

export type Dictionary = (typeof dictionaries)[Locale]

const LOCALE_STORAGE_KEY = "ai-card-master.locale"

function isLocale(value: unknown): value is Locale {
  return value === "ru" || value === "en"
}

function readStoredLocale(): Locale | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(LOCALE_STORAGE_KEY)
    return isLocale(raw) ? raw : null
  } catch {
    return null
  }
}

function persistLocale(locale: Locale): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    // ignore quota / private mode
  }
}

function resolvePath(dict: DictNode, path: string): string | undefined {
  const parts = path.split(".")
  let cursor: DictLeaf | DictNode | undefined = dict
  for (const part of parts) {
    if (!cursor || typeof cursor === "string") return undefined
    cursor = cursor[part]
  }
  return typeof cursor === "string" ? cursor : undefined
}

function interpolate(
  template: string,
  vars?: Record<string, string | number>
): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    vars[key] !== undefined ? String(vars[key]) : `{${key}}`
  )
}

export {
  LOCALE_STORAGE_KEY,
  interpolate,
  persistLocale,
  readStoredLocale,
  resolvePath,
}
