import axios, { type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { toast } from "sonner";

import {
  getApiErrorMessage,
  isNetworkError,
  NETWORK_ERROR_MESSAGES,
} from "@/lib/api/errors";
import {
  API_BASE_URL,
  DEFAULT_API_BASE_URL,
  resolveApiBaseUrl,
} from "@/lib/constants/api";
import type {
  CanvasStateDTO,
  ParsedProductDTO,
  RelightCustomParams,
  RelightProcessResponse,
  RemoveBgResponse,
  RenderCanvasResult,
  SavedDesignDTO,
  SavedDesignListResponse,
  SaveDesignRequest,
} from "@/types/api";

const LONG_RUNNING_TIMEOUT_MS = 120_000;

/** Guaranteed fallback if env/build leaves baseURL empty. */
const resolvedBaseUrl =
  resolveApiBaseUrl(API_BASE_URL) || DEFAULT_API_BASE_URL;

declare module "axios" {
  export interface AxiosRequestConfig {
    /** When true, the global response interceptor skips toasting. */
    skipErrorToast?: boolean;
  }
}

export const apiClient = axios.create({
  baseURL: resolvedBaseUrl,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30_000,
});

apiClient.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token =
      window.localStorage.getItem("access_token") ||
      document.cookie
        .split("; ")
        .find((row) => row.startsWith("access_token="))
        ?.split("=")
        .slice(1)
        .join("=");
    if (token) {
      try {
        config.headers.Authorization = `Bearer ${decodeURIComponent(token)}`;
      } catch {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (typeof window === "undefined" || !axios.isAxiosError(error)) {
      return Promise.reject(error);
    }

    const config = error.config as InternalAxiosRequestConfig | undefined;
    if (config?.skipErrorToast) {
      return Promise.reject(error);
    }

    if (isNetworkError(error)) {
      toast.error(getApiErrorMessage(error, NETWORK_ERROR_MESSAGES.offline));
      return Promise.reject(error);
    }

    const status = error.response?.status;
    if (status !== undefined && status >= 500) {
      toast.error(getApiErrorMessage(error, NETWORK_ERROR_MESSAGES.server));
    } else if (status === 401) {
      toast.error(NETWORK_ERROR_MESSAGES.unauthorized);
    }

    return Promise.reject(error);
  },
);

/**
 * Composite CanvasStateDTO server-side → PNG/WebP blob + object URL.
 * Caller should `URL.revokeObjectURL(result.url)` when finished.
 */
export async function renderCanvas(
  state: CanvasStateDTO,
): Promise<RenderCanvasResult> {
  const response = await apiClient.post<Blob>("/canvas/render", state, {
    responseType: "blob",
    timeout: LONG_RUNNING_TIMEOUT_MS,
  });

  const blob = await resolveImageBlob(response);
  return {
    blob,
    url: URL.createObjectURL(blob),
  };
}

/**
 * Parametric softbox relighting (`StudioLightDTO` + `image_url`).
 * POST /relighting/custom
 */
export async function processRelighting(
  params: RelightCustomParams,
): Promise<RelightProcessResponse> {
  const { image_url, ...studio_light } = params;

  const { data } = await apiClient.post<RelightProcessResponse>(
    "/relighting/custom",
    {
      image_url,
      studio_light,
    },
    { timeout: LONG_RUNNING_TIMEOUT_MS },
  );

  return data;
}

/** Parse Ozon / Wildberries product page → structured card data. */
export async function parseProduct(url: string): Promise<ParsedProductDTO> {
  const { data } = await apiClient.post<ParsedProductDTO>(
    "/parser/parse",
    { url },
    { timeout: LONG_RUNNING_TIMEOUT_MS },
  );
  return data;
}

/** Natural-language prompt → validated CanvasStateDTO JSON. */
export async function generateByPrompt(
  prompt: string,
  baseCanvas?: CanvasStateDTO,
): Promise<CanvasStateDTO> {
  const { data } = await apiClient.post<CanvasStateDTO>(
    "/templates/prompt-to-json",
    {
      prompt,
      ...(baseCanvas ? { base_canvas: baseCanvas } : {}),
    },
    { timeout: LONG_RUNNING_TIMEOUT_MS },
  );
  return data;
}

export async function listDesigns(): Promise<SavedDesignListResponse> {
  const { data } =
    await apiClient.get<SavedDesignListResponse>("/designs");
  return data;
}

export async function getDesign(
  designId: string,
  signal?: AbortSignal,
): Promise<SavedDesignDTO> {
  const { data } = await apiClient.get<SavedDesignDTO>(
    `/designs/${encodeURIComponent(designId)}`,
    { signal },
  );
  return data;
}

export async function saveDesign(
  payload: SaveDesignRequest,
): Promise<SavedDesignDTO> {
  const { data } = await apiClient.post<SavedDesignDTO>("/designs", payload);
  return data;
}

export async function deleteDesign(designId: string): Promise<void> {
  await apiClient.delete(`/designs/${encodeURIComponent(designId)}`);
}

/**
 * Remove product background (multipart file and/or `image_url`).
 * POST /tools/remove-bg
 */
export async function removeBackground(params: {
  file?: File;
  imageUrl?: string;
  idempotencyKey?: string;
}): Promise<RemoveBgResponse> {
  const form = new FormData();
  if (params.file) {
    form.append("file", params.file);
  }
  if (params.imageUrl) {
    form.append("image_url", params.imageUrl);
  }

  const headers: Record<string, string> = {};
  if (params.idempotencyKey) {
    headers["Idempotency-Key"] = params.idempotencyKey;
  }

  const { data } = await apiClient.post<RemoveBgResponse>(
    "/tools/remove-bg",
    form,
    {
      headers: {
        ...headers,
        "Content-Type": "multipart/form-data",
      },
      timeout: LONG_RUNNING_TIMEOUT_MS,
      skipErrorToast: true,
      transformRequest: [
        (body, reqHeaders) => {
          // Let the runtime set multipart boundary (drop JSON default).
          if (
            typeof FormData !== "undefined" &&
            body instanceof FormData &&
            reqHeaders
          ) {
            delete reqHeaders["Content-Type"];
          }
          return body;
        },
      ],
    },
  );

  return data;
}

async function resolveImageBlob(
  response: AxiosResponse<Blob>,
): Promise<Blob> {
  const contentType = String(response.headers["content-type"] ?? "");

  if (contentType.includes("application/json")) {
    const text = await response.data.text();
    const payload = JSON.parse(text) as {
      url?: string;
      result_url?: string;
      presigned_url?: string;
    };
    const imageUrl =
      payload.url ?? payload.result_url ?? payload.presigned_url ?? null;
    if (!imageUrl) {
      throw new Error("Canvas render response JSON has no image URL.");
    }
    const imageResponse = await fetch(imageUrl);
    if (!imageResponse.ok) {
      throw new Error(
        `Failed to download rendered canvas (${imageResponse.status}).`,
      );
    }
    return imageResponse.blob();
  }

  return response.data;
}
