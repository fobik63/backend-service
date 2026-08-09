import { redirect } from "next/navigation"

/**
 * Tariffs live in a portal Dialog (TopUpDialog via AppHeader).
 * Keep the route for bookmarks/deep links — bounce to workspace without
 * replacing the modal entry point.
 */
export default function PricingPage() {
  redirect("/projects")
}
