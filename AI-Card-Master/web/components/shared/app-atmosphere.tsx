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

      {/* Emerald-botanical glow spots along screen edges */}
      <div className="absolute -left-32 top-[15%] size-[28rem] rounded-full bg-[#059669]/10 blur-[120px]" />
      <div className="absolute -right-40 top-[40%] size-[32rem] rounded-full bg-[#1b3e2b]/20 blur-[120px]" />
      <div className="absolute -left-24 bottom-[10%] size-[24rem] rounded-full bg-[#1b3e2b]/20 blur-[120px]" />
      <div className="absolute -right-28 bottom-[25%] size-[22rem] rounded-full bg-[#059669]/10 blur-[120px]" />

      <div className="absolute inset-0 botanical-glow" />
      <div className="absolute inset-0 opacity-[0.04] noise-texture mix-blend-overlay" />
    </div>
  )
}

export { AppAtmosphere }
