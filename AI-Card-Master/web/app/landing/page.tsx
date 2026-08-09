import {
  CallToActionSection,
  FeaturesSection,
  FaqSection,
  Footer,
  HeroSection,
  Navbar,
  PricingSection,
  TestimonialsSection,
} from "@/components/landing"

export default function LandingPage() {
  return (
    <div className="relative min-h-dvh overflow-x-hidden text-foreground">
      <Navbar />
      <main className="relative flex flex-col">
        <HeroSection />
        <FeaturesSection />
        <PricingSection />
        <TestimonialsSection />
        <FaqSection />
        <CallToActionSection />
      </main>
      <Footer />
    </div>
  )
}
