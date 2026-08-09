import { BackgroundGlow } from "@/components/shared/background-glow"

/**
 * Fixed full-viewport graphite atmosphere shared by every route.
 * Deep loft base + subtle ambient glow + fine noise.
 */
function AppAtmosphere() {
  return (
    <div
      className="pointer-events-none fixed inset-0 -z-10 min-h-[100vh] min-h-dvh overflow-hidden"
      aria-hidden
    >
      <div className="absolute inset-0 bg-loft" />
      <div className="absolute inset-0 bg-loft-canvas" />

      <BackgroundGlow />

      <div className="absolute inset-0 opacity-[0.04] noise-texture mix-blend-overlay" />
    </div>
  )
}

export { AppAtmosphere }
