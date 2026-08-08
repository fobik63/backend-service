import type { Project } from "@/lib/constants/mock-projects"

/** Minimal product/card payload required before Canvas + PromptBar mount. */
export type EditorProductData = {
  id: string
  title: string
  marketplace: Project["marketplace"] | null
  status: Project["status"] | null
  previewImage?: string | null
}
