import type { ReactNode } from "react"

import { AppShell } from "@/components/layout/app-shell"

type DashboardLayoutProps = {
  children: ReactNode
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return <AppShell variant="workspace">{children}</AppShell>
}
