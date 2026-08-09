import { apiClient } from "@/lib/api/client"

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

export type BalanceDTO = {
  ai_coins: number
  daily_bonus_available: boolean
  daily_bonus_streak: number
  daily_bonus_coins: number
  last_daily_bonus_claimed_at: string | null
  next_daily_bonus_available_at: string
}

export async function listTariffs(): Promise<TariffDTO[]> {
  const { data } = await apiClient.get<TariffDTO[]>("/payments/tariffs")
  return data
}

export async function getBalance(): Promise<BalanceDTO> {
  const { data } = await apiClient.get<BalanceDTO>("/payments/balance")
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
