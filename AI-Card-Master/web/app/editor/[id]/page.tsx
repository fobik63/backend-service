import { EditorWorkspace } from "@/components/editor"

type EditorPageProps = {
  params: Promise<{ id: string }>
}

export default async function EditorByIdPage({ params }: EditorPageProps) {
  const { id } = await params
  return <EditorWorkspace projectId={id} />
}
