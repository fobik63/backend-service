"use client"

import { useRef, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"

type ConfirmDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  cancelLabel: string
  confirmLabel: string
  onCancel?: () => void
  onConfirm: () => void
  confirmVariant?: "default" | "destructive"
  className?: string
}

function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  cancelLabel,
  confirmLabel,
  onCancel,
  onConfirm,
  confirmVariant = "destructive",
  className,
}: ConfirmDialogProps) {
  const confirmedRef = useRef(false)

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !confirmedRef.current) {
          onCancel?.()
        }
        confirmedRef.current = false
        onOpenChange(next)
      }}
    >
      <DialogPortal>
        <DialogOverlay className="bg-black/60 backdrop-blur-md supports-backdrop-filter:backdrop-blur-md" />
        <DialogPrimitive.Popup
          data-slot="dialog-content"
          className={cn(
            "fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-0 overflow-hidden rounded-2xl border border-white/12 bg-zinc-950/85 p-0 text-sm text-foreground shadow-[0_24px_80px_rgba(0,0,0,0.55)] outline-none backdrop-blur-md sm:max-w-md",
            "duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
            className
          )}
        >
          <DialogHeader className="gap-2 px-5 pt-5 pb-4 sm:px-6">
            <DialogTitle className="font-heading text-base font-semibold tracking-tight">
              {title}
            </DialogTitle>
            {description ? (
              <DialogDescription className="text-sm leading-relaxed text-muted-foreground">
                {description}
              </DialogDescription>
            ) : null}
          </DialogHeader>

          <DialogFooter className="-mx-0 -mb-0 flex-col-reverse gap-2 rounded-none border-t border-white/10 bg-white/[0.03] p-4 sm:flex-row sm:justify-end sm:px-5 sm:py-4">
            <Button
              type="button"
              variant="outline"
              className="border-white/12 bg-white/[0.04] hover:bg-white/[0.08]"
              onClick={() => {
                onCancel?.()
                confirmedRef.current = true
                onOpenChange(false)
              }}
            >
              {cancelLabel}
            </Button>
            <Button
              type="button"
              variant={confirmVariant}
              onClick={() => {
                confirmedRef.current = true
                onConfirm()
                onOpenChange(false)
              }}
            >
              {confirmLabel}
            </Button>
          </DialogFooter>
        </DialogPrimitive.Popup>
      </DialogPortal>
    </Dialog>
  )
}

export { ConfirmDialog }
export type { ConfirmDialogProps }
