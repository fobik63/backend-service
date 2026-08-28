"use client"

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import { BuyCoinsDialog } from "@/components/dashboard/buy-coins-dialog"
import { TopUpDialog } from "@/components/dashboard/top-up-dialog"

type BuyCoinsContextValue = {
  openBuyCoins: () => void
}

const BuyCoinsContext = createContext<BuyCoinsContextValue | null>(null)

function BuyCoinsProvider({ children }: { children: ReactNode }) {
  const [buyOpen, setBuyOpen] = useState(false)
  const [tariffOpen, setTariffOpen] = useState(false)

  const openBuyCoins = useCallback(() => setBuyOpen(true), [])

  const value = useMemo(() => ({ openBuyCoins }), [openBuyCoins])

  return (
    <BuyCoinsContext.Provider value={value}>
      {children}
      <BuyCoinsDialog
        open={buyOpen}
        onOpenChange={setBuyOpen}
        onOpenTariffs={() => setTariffOpen(true)}
      />
      <TopUpDialog open={tariffOpen} onOpenChange={setTariffOpen} />
    </BuyCoinsContext.Provider>
  )
}

function useBuyCoins() {
  const ctx = useContext(BuyCoinsContext)
  if (!ctx) {
    throw new Error("useBuyCoins must be used within BuyCoinsProvider")
  }
  return ctx
}

export { BuyCoinsProvider, useBuyCoins }
