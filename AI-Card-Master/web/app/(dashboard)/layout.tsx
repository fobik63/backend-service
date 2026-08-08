import type { ReactNode } from "react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"

type DashboardLayoutProps = {
  children: ReactNode
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return <DashboardShell>{children}</DashboardShell>
}
