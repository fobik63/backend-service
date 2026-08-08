"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import {
  dictionaries,
  interpolate,
  persistLocale,
  readStoredLocale,
  resolvePath,
  type Locale,
} from "@/lib/i18n/dictionaries"

type TranslateFn = (
  path: string,
  vars?: Record<string, string | number>
) => string

type I18nContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: TranslateFn
}

const I18nContext = createContext<I18nContextValue | null>(null)

type I18nProviderProps = {
  children: ReactNode
  defaultLocale?: Locale
}

function I18nProvider({
  children,
  defaultLocale = "ru",
}: I18nProviderProps) {
  const [locale, setLocaleState] = useState<Locale>(defaultLocale)

  useEffect(() => {
    const stored = readStoredLocale()
    if (stored) setLocaleState(stored)
  }, [])

  useEffect(() => {
    if (typeof document === "undefined") return
    document.documentElement.lang = locale
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    persistLocale(next)
  }, [])

  const t = useCallback<TranslateFn>(
    (path, vars) => {
      const fromActive = resolvePath(dictionaries[locale], path)
      const fromFallback = resolvePath(dictionaries.ru, path)
      return interpolate(fromActive ?? fromFallback ?? path, vars)
    },
    [locale]
  )

  const value = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t]
  )

  return (
    <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
  )
}

function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) {
    throw new Error("useI18n must be used within I18nProvider")
  }
  return ctx
}

export { I18nProvider, useI18n }
export type { I18nContextValue, Locale, TranslateFn }
