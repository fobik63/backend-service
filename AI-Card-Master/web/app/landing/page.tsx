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
    <div className="min-h-screen bg-loft text-foreground">
      <Navbar />
      <main>
        <HeroSection />
        <FeaturesSection />
        <TestimonialsSection />
        <CallToActionSection />
      </main>
      <Footer />
    </div>
  )
}
