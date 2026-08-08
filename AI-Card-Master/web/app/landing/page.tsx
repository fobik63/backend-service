import {
  CallToActionSection,
  FeaturesSection,
  Footer,
  HeroSection,
  Navbar,
  TestimonialsSection,
} from "@/components/landing"

export default function LandingPage() {
  return (
    <div className="relative min-h-screen overflow-x-hidden bg-loft text-foreground">
      {/* Global Loft + Botanical atmosphere */}
      <div className="pointer-events-none fixed inset-0 -z-10" aria-hidden>
        <div className="absolute inset-0 bg-gradient-to-b from-[#0f1115] via-[#141b17] to-[#0f1115]" />
        <div className="absolute inset-0 botanical-glow" />
        <div className="absolute inset-0 opacity-[0.04] noise-texture" />
      </div>

      <Navbar />
      <main className="relative">
        <HeroSection />
        {/* Seamless blend — no hard section rules */}
        <div className="h-16 bg-gradient-to-b from-transparent via-[#141b17]/80 to-transparent sm:h-24" aria-hidden />
        <FeaturesSection />
        <div className="h-16 bg-gradient-to-b from-transparent via-[#141b17]/80 to-transparent sm:h-24" aria-hidden />
        <TestimonialsSection />
        <div className="h-16 bg-gradient-to-b from-transparent via-[#141b17]/80 to-transparent sm:h-24" aria-hidden />
        <CallToActionSection />
      </main>
      <Footer />
    </div>
  )
}
