import { apiClient } from "@/lib/api/client"
import {
  COIN_PACKAGES,
  quoteCoinPurchase,
} from "@/lib/billing/coin-pricing"
import { IS_MOCK } from "@/lib/constants/mock"

export type TariffCode = "start" | "pro" | "half_year" | "year"

export type TariffDTO = {
  code: TariffCode | string
  title: string
  duration_days: number
  ai_coins: number
  price_rub: number
  amount_value: string
  subscription_status: string
  description: string
}

export type CreatePaymentResponse = {
  payment_id: string
  yookassa_payment_id: string
  tariff_code: string
  amount_rub: number
  currency: string
  status: string
  confirmation_url: string | null
  description: string | null
}

export async function listTariffs(): Promise<TariffDTO[]> {
  const { data } = await apiClient.get<TariffDTO[]>("/payments/tariffs")
  return data
}

export async function createPayment(
  tariffCode: TariffCode,
): Promise<CreatePaymentResponse> {
  const { data } = await apiClient.post<CreatePaymentResponse>(
    "/payments/create",
    { tariff_code: tariffCode },
    { skipErrorToast: true },
  )
  return data
}

export type CoinPackDTO = {
  amount_coins: number
  unit_price_rub: string
  amount_rub: string
  currency: string
  package_code: string
  is_preset_package: boolean
  description: string
}

export type CreateCoinPaymentResponse = {
  payment_id: string
  yookassa_payment_id: string
  user_id: string
  amount_coins: number
  amount_rub: string
  unit_price_rub: string
  currency: string
  package_code: string
  status: string
  confirmation_url: string | null
  description: string | null
  idempotency_key: string
}

function mockCoinPacks(): CoinPackDTO[] {
  return COIN_PACKAGES.map((amount) => {
    const quote = quoteCoinPurchase(amount)
    return {
      amount_coins: amount,
      unit_price_rub: quote.unitPriceRub.toFixed(4),
      amount_rub: quote.amountRub.toFixed(2),
      currency: "RUB",
      package_code: String(amount),
      is_preset_package: true,
      description: `${amount} ИИ-коинов`,
    }
  })
}

export async function listCoinPacks(): Promise<CoinPackDTO[]> {
  if (IS_MOCK) return mockCoinPacks()
  const { data } = await apiClient.get<CoinPackDTO[]>("/billing/coin-packs", {
    skipErrorToast: true,
  })
  return data
}

export async function createCoinPayment(
  userId: string,
  amountCoins: number,
): Promise<CreateCoinPaymentResponse> {
  if (IS_MOCK) {
    const quote = quoteCoinPurchase(amountCoins)
    await new Promise((resolve) => setTimeout(resolve, 420))
    return {
      payment_id: "mock-coin-payment",
      yookassa_payment_id: "mock-yookassa",
      user_id: userId,
      amount_coins: amountCoins,
      amount_rub: quote.amountRub.toFixed(2),
      unit_price_rub: quote.unitPriceRub.toFixed(4),
      currency: "RUB",
      package_code: quote.isPresetPackage ? String(amountCoins) : "custom",
      status: "pending",
      confirmation_url: "/payments/return?mock=1",
      description: `Mock checkout ${amountCoins} coins`,
      idempotency_key: "mock-idempotency",
    }
  }

  const { data } = await apiClient.post<CreateCoinPaymentResponse>(
    "/billing/create-payment",
    { user_id: userId, amount_coins: amountCoins },
    { skipErrorToast: true },
  )
  return data
}
