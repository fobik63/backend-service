import { notFound } from "next/navigation"

import { EditorWorkspace } from "@/components/editor"
import { MOCK_PROJECTS } from "@/lib/constants/mock-projects"
import type { EditorProductData } from "@/types/editor"

type EditorPageProps = {
  params: Promise<{ id: string }>
}

function resolveProductData(id: string): EditorProductData | null {
  const trimmed = id?.trim()
  if (!trimmed) return null

  const project = MOCK_PROJECTS.find((p) => p.id === trimmed)
  if (project) {
    return {
      id: project.id,
      title: project.title,
      marketplace: project.marketplace,
      status: project.status,
      previewImage: project.previewImage,
      productImage: project.productImage ?? project.previewImage,
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

  // Unknown id still opens a sandbox project shell (demo / deep-link).
  return {
    id: trimmed,
    title: `Проект ${trimmed}`,
    marketplace: null,
    status: null,
    productImage: "/projects/cream-sage-mist-product.png",
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
