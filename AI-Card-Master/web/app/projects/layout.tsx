import type { ReactNode } from "react"

import { AppShell } from "@/components/layout/app-shell"

type ProjectsLayoutProps = {
  children: ReactNode
}

/** Workspace chrome for `/projects` (moved out of `(dashboard)` route group). */
export default function ProjectsLayout({ children }: ProjectsLayoutProps) {
  return <AppShell variant="workspace">{children}</AppShell>
}
