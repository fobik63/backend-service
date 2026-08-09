import type { ReactNode } from "react"

import { AppShell } from "@/components/layout/app-shell"

type EditorLayoutProps = {
  children: ReactNode
}

export default function EditorLayout({ children }: EditorLayoutProps) {
  return <AppShell variant="editor">{children}</AppShell>
}
