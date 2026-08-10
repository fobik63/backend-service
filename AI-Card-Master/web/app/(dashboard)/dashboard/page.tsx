import { redirect } from "next/navigation"

/** Legacy path — workspace lives at `/projects`. */
export default function DashboardPage() {
  redirect("/projects")
}
