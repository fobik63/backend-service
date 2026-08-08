import { cn } from "@/lib/utils"

type BrandLogoProps = {
  className?: string
  /** Accessible name; defaults to brand name */
  alt?: string
}

function OzonLogo({ className, alt = "Ozon" }: BrandLogoProps) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- local brand SVG
    <img
      src="/brands/ozon.svg"
      alt={alt}
      width={160}
      height={35}
      draggable={false}
      className={cn("h-8 w-auto select-none sm:h-9", className)}
    />
  )
}

function WildberriesLogo({ className, alt = "Wildberries" }: BrandLogoProps) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- local brand SVG
    <img
      src="/brands/wildberries.svg"
      alt={alt}
      width={200}
      height={30}
      draggable={false}
      className={cn("h-7 w-auto select-none sm:h-8", className)}
    />
  )
}

export { OzonLogo, WildberriesLogo }
export type { BrandLogoProps }
