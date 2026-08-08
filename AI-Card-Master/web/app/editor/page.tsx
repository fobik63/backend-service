import { redirect } from "next/navigation"

import { MOCK_PROJECTS } from "@/lib/constants/mock-projects"

/** Legacy `/editor` entry — open the first mock project. */
export default function EditorIndexPage() {
  const first = MOCK_PROJECTS[0]?.id ?? "demo"
  redirect(`/editor/${first}`)
}
