"use client"

import type { ReactNode } from "react"

import { PageTransition } from "@/components/ui/page-transition"

export default function OnboardingTemplate({ children }: { children: ReactNode }) {
  return <PageTransition>{children}</PageTransition>
}
