import type { Metadata } from "next";
import {
  Inter,
  Manrope,
  Montserrat,
  Onest,
  Oswald,
  Roboto,
  Russo_One,
  Space_Grotesk,
  Unbounded,
} from "next/font/google";

import { AppProviders } from "@/components/providers/app-providers";
import { AppAtmosphere } from "@/components/shared/app-atmosphere";

import "./globals.css";

const manrope = Manrope({
  subsets: ["latin", "cyrillic"],
  variable: "--font-manrope",
  display: "swap",
});

/** Marketplace editor fonts (WB/Ozon Cyrillic). */
const inter = Inter({
  subsets: ["latin", "cyrillic"],
  variable: "--font-inter",
  display: "swap",
});

const montserrat = Montserrat({
  subsets: ["latin", "cyrillic"],
  variable: "--font-montserrat",
  display: "swap",
});

const unbounded = Unbounded({
  subsets: ["latin", "cyrillic"],
  variable: "--font-unbounded",
  display: "swap",
});

/**
 * Cera Pro is proprietary — Onest is the Cyrillic geometric stand-in
 * registered under `--font-cera-pro` for the editor picker label "Cera Pro".
 * Drop licensed files later via next/font/local without changing call sites.
 */
const ceraPro = Onest({
  subsets: ["latin", "cyrillic"],
  variable: "--font-cera-pro",
  display: "swap",
});

const oswald = Oswald({
  subsets: ["latin", "cyrillic"],
  variable: "--font-oswald",
  display: "swap",
});

const russoOne = Russo_One({
  weight: "400",
  subsets: ["latin", "cyrillic"],
  variable: "--font-russo-one",
  display: "swap",
});

/** Kept for older saved documents that still reference these families. */
const roboto = Roboto({
  subsets: ["latin", "cyrillic"],
  variable: "--font-roboto",
  weight: ["400", "500", "700"],
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Card Master",
  description: "AI-powered product card generation for marketplaces",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru" className="dark" suppressHydrationWarning>
      <body
        className={`${manrope.variable} ${inter.variable} ${montserrat.variable} ${unbounded.variable} ${ceraPro.variable} ${oswald.variable} ${russoOne.variable} ${roboto.variable} ${spaceGrotesk.variable} relative min-h-dvh bg-transparent font-sans antialiased text-foreground`}
      >
        <AppAtmosphere />
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
