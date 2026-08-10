import { redirect } from "next/navigation"

/** Legacy URL — landing now lives at `/`. */
export default function LandingRedirectPage() {
  redirect("/")
}
