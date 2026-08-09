import { apiClient } from "@/lib/api/client"

export type MarketplacePlatform = "wildberries" | "ozon" | "amazon"

export type CredentialDTO = {
  platform: MarketplacePlatform
  is_configured: boolean
  label: string | null
  updated_at: string | null
}

export async function listExportCredentials(): Promise<CredentialDTO[]> {
  const { data } = await apiClient.get<CredentialDTO[]>("/exports/credentials", {
    skipErrorToast: true,
  })
  return data
}

export async function saveExportCredentials(
  platform: MarketplacePlatform,
  credentials: Record<string, string>,
  label?: string,
): Promise<CredentialDTO> {
  const { data } = await apiClient.put<CredentialDTO>(
    `/exports/credentials/${platform}`,
    {
      credentials,
      ...(label ? { label } : {}),
    },
    { skipErrorToast: true },
  )
  return data
}
