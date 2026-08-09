import { redirect } from "next/navigation"

/** `/editor` entry — open a clean unsaved project. */
export default function EditorIndexPage() {
  redirect("/editor/new")
}
