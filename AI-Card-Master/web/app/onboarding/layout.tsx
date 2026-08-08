import type { ReactNode } from "react"

type OnboardingLayoutProps = {
  children: ReactNode
}

export default function OnboardingLayout({ children }: OnboardingLayoutProps) {
  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-10 sm:px-6">
      <div className="relative z-10 w-full max-w-xl">{children}</div>
    </div>
  )
}
