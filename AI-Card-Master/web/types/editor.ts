import type { Project } from "@/lib/constants/mock-projects"

/** Minimal product/card payload required before Canvas + PromptBar mount. */
export type EditorProductData = {
  id: string
  title: string
  marketplace: Project["marketplace"] | null
  status: Project["status"] | null
  /** Card thumbnail / marketing composite (projects list). */
  previewImage?: string | null
  /** Isolated transparent product PNG for the canvas layer. */
  productImage?: string | null
}
