import { notFound } from "next/navigation"

import { EditorWorkspace } from "@/components/editor"
import { IS_MOCK } from "@/lib/constants/mock"
import { MOCK_PROJECTS } from "@/lib/constants/mock-projects"
import type { EditorProductData } from "@/types/editor"

type EditorPageProps = {
  params: Promise<{ id: string }>
}

function resolveProductData(id: string): EditorProductData | null {
  const trimmed = id?.trim()
  if (!trimmed) return null

  // Sandbox catalog only when client mock mode is on.
  if (IS_MOCK) {
    const project = MOCK_PROJECTS.find((p) => p.id === trimmed)
    if (project) {
      return {
        id: project.id,
        title: project.title,
        marketplace: project.marketplace,
        status: project.status,
        previewImage: project.previewImage,
        // Cutout only — never use full marketplace preview (badges baked into PNG).
        productImage: project.productImage,
      }
    }
  }

  // Blank new card — no leftover product art from the sandbox shell.
  if (trimmed === "new") {
    return {
      id: "new",
      title: "Новый проект",
      marketplace: null,
      status: null,
    }
  }

  // UUID / deep-link: minimal shell — client hydrates via getDesign (no mock art).
  return {
    id: trimmed,
    title: `Проект ${trimmed}`,
    marketplace: null,
    status: null,
  }
}

export default async function EditorByIdPage({ params }: EditorPageProps) {
  const { id } = await params
  const productData = resolveProductData(id)

  if (!productData) {
    notFound()
  }

  return (
    <EditorWorkspace projectId={productData.id} productData={productData} />
  )
}
