import type { Metadata } from "next";
import {
  Inter,
  Manrope,
  Montserrat,
  Roboto,
  Space_Grotesk,
} from "next/font/google";

import { AppProviders } from "@/components/providers/app-providers";
import { AppAtmosphere } from "@/components/shared/app-atmosphere";

import "./globals.css";

const manrope = Manrope({
  subsets: ["latin", "cyrillic"],
  variable: "--font-manrope",
  display: "swap",
});

/** Kept for on-canvas text layers (editor font picker). */
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
        className={`${manrope.variable} ${inter.variable} ${montserrat.variable} ${roboto.variable} ${spaceGrotesk.variable} relative min-h-dvh bg-transparent font-sans antialiased text-foreground`}
      >
        <AppAtmosphere />
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
