"use client"

import type { ReactNode } from "react"

import { PageTransition } from "@/components/ui/page-transition"

export default function DashboardTemplate({ children }: { children: ReactNode }) {
  return <PageTransition>{children}</PageTransition>
}
