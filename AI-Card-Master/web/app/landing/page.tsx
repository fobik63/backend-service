import { FeaturesSection, HeroSection, Navbar } from "@/components/landing"

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-loft text-foreground">
      <Navbar />
      <main>
        <HeroSection />
        <FeaturesSection />
      </main>
    </div>
  )
}
