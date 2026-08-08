import { BackgroundGlow } from "@/components/shared/background-glow"

/**
 * Fixed full-viewport Dark Loft atmosphere shared by every route.
 * Lives in the root layout so /, /editor, /login, /terms, etc. share one look.
 */
function AppAtmosphere() {
  return (
    <div
      className="pointer-events-none fixed inset-0 -z-10 min-h-[100vh] min-h-dvh overflow-hidden"
      aria-hidden
    >
      <div className="absolute inset-0 bg-[#0d0f12]" />
      <div className="absolute inset-0 bg-loft-canvas" />

      {/* Unified emerald abstract side glows (mirrored L/R) */}
      <BackgroundGlow />

      <div className="absolute inset-0 opacity-[0.04] noise-texture mix-blend-overlay" />
    </div>
  )
}

export { AppAtmosphere }
