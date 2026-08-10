import axios, { type AxiosError } from "axios";

import { ANTIBOT_ERROR_CODE } from "@/lib/parser/antibot";

/** User-facing Russian messages for common network / HTTP failures. */
export const NETWORK_ERROR_MESSAGES = {
  offline: "Нет соединения с сервером",
  timeout: "Превышено время ожидания ответа",
  server: "Ошибка сервера. Попробуйте позже",
  unauthorized: "Сессия истекла. Войдите снова",
  forbidden: "Недостаточно прав для этого действия",
  notFound: "Ресурс не найден",
  generic: "Не удалось выполнить запрос",
} as const;

type ApiErrorBody = {
  detail?: string | { msg?: string }[];
  message?: string;
  /** Flat parser / domain errors, e.g. `{ "error": "Товар не найден…" }`. */
  error?: string;
};

function detailFromBody(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const body = data as ApiErrorBody;
  // Parser antibot contract: `{ error: "antibot_detected", message: "…" }`.
  if (
    typeof body.error === "string" &&
    body.error.trim() === ANTIBOT_ERROR_CODE &&
    typeof body.message === "string" &&
    body.message.trim()
  ) {
    return body.message.trim();
  }
  if (typeof body.error === "string" && body.error.trim()) {
    return body.error.trim();
  }
  if (typeof body.message === "string" && body.message.trim()) {
    return body.message.trim();
  }
  if (typeof body.detail === "string" && body.detail.trim()) {
    return body.detail.trim();
  }
  if (Array.isArray(body.detail) && body.detail[0]?.msg) {
    return body.detail[0].msg;
  }
  return null;
}

/** Map Axios / unknown errors to a short RU message for toasts. */
export function getApiErrorMessage(
  error: unknown,
  fallback: string = NETWORK_ERROR_MESSAGES.generic,
): string {
  if (!axios.isAxiosError(error)) {
    if (error instanceof Error && error.message.trim()) {
      return error.message;
    }
    return fallback;
  }

  const axiosError = error as AxiosError;
  if (axiosError.code === "ECONNABORTED") {
    return NETWORK_ERROR_MESSAGES.timeout;
  }
  if (!axiosError.response) {
    return NETWORK_ERROR_MESSAGES.offline;
  }

  const status = axiosError.response.status;
  const fromBody = detailFromBody(axiosError.response.data);
  if (fromBody) return fromBody;

  if (status === 401) return NETWORK_ERROR_MESSAGES.unauthorized;
  if (status === 403) return NETWORK_ERROR_MESSAGES.forbidden;
  if (status === 404) return NETWORK_ERROR_MESSAGES.notFound;
  if (status >= 500) return NETWORK_ERROR_MESSAGES.server;

  return fallback;
}

export function isNetworkError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  return !error.response || error.code === "ECONNABORTED";
}

/** True when POST /api/parse returned Cloudflare / marketplace antibot block. */
export function isAntibotDetectedError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  const data = error.response?.data;
  if (!data || typeof data !== "object") return false;
  return (data as ApiErrorBody).error === ANTIBOT_ERROR_CODE;
}
