import Link from "next/link"

import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export default function NotFound() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4 px-6 text-center text-foreground">
      <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
        404
      </p>
      <h1 className="max-w-md font-heading text-2xl font-semibold tracking-tight">
        Страница не найдена
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        Запрошенный адрес не существует или был перемещён.
      </p>
      <Link
        href="/"
        className={cn(buttonVariants({ size: "default" }))}
      >
        На главную
      </Link>
    </main>
  )
}
