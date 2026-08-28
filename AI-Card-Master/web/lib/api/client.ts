import axios, { type InternalAxiosRequestConfig } from "axios";
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
import { IS_MOCK } from "@/lib/constants/mock";
import type {
  CanvasStateDTO,
  GenerationCreateResponse,
  GenerationStatusResponse,
  RemoveBgResponse,
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
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30_000,
});

apiClient.interceptors.request.use((config) => {
  // Re-resolve on each request so phone/LAN opens rewrite localhost → PC IP.
  config.baseURL =
    resolveApiBaseUrl(API_BASE_URL) || DEFAULT_API_BASE_URL;

  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
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

/** Natural-language prompt → validated CanvasStateDTO JSON. */
export async function generateByPrompt(
  prompt: string,
  baseCanvas?: CanvasStateDTO,
): Promise<CanvasStateDTO> {
  if (IS_MOCK) {
    const {
      delay,
      getMockGenerateLayers,
      MOCK_GENERATE_DELAY_MS,
      MOCK_PRODUCT_IMAGE,
    } = await import("@/lib/constants/mock")
    const { layersToCanvasState } = await import(
      "@/lib/editor/editor-document"
    )
    await delay(MOCK_GENERATE_DELAY_MS)
    void prompt
    void baseCanvas
    return layersToCanvasState(getMockGenerateLayers(), MOCK_PRODUCT_IMAGE)
  }

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
  if (IS_MOCK) {
    const { MOCK_PROJECTS } = await import("@/lib/constants/mock-projects")
    const items: SavedDesignDTO[] = MOCK_PROJECTS.map((project) => ({
      id: project.id,
      title: project.title,
      preview_url: project.previewImage,
      canvas: {
        width: 1080,
        height: 1440,
        background_color: "#151719",
        layers: [],
      },
      editor_document: project.editorDocument ?? null,
      updated_at: project.createdAt,
    }))
    return { items, total: items.length }
  }

  const { data } =
    await apiClient.get<SavedDesignListResponse>("/designs");
  return data;
}

/** In-memory mock designs for save/get within one browser session. */
const mockDesignMemory = new Map<string, SavedDesignDTO>()

export async function getDesign(
  designId: string,
  signal?: AbortSignal,
): Promise<SavedDesignDTO> {
  if (IS_MOCK) {
    if (signal?.aborted) {
      throw new DOMException("Aborted", "AbortError")
    }
    const { delay, MOCK_CARD_IMAGE, MOCK_PRODUCT_IMAGE, getMockGenerateLayers } =
      await import("@/lib/constants/mock")
    const { MOCK_PROJECTS } = await import("@/lib/constants/mock-projects")
    const { layersToCanvasState, createEditorDocument } = await import(
      "@/lib/editor/editor-document"
    )
    await delay(180)
    if (signal?.aborted) {
      throw new DOMException("Aborted", "AbortError")
    }

    const cached = mockDesignMemory.get(designId)
    if (cached) return structuredClone(cached)

    const project = MOCK_PROJECTS.find((p) => p.id === designId)
    const layers = getMockGenerateLayers()
    const productUrl =
      project?.productImage ?? project?.previewImage ?? MOCK_PRODUCT_IMAGE
    const backgroundUrl = project?.previewImage ?? MOCK_CARD_IMAGE
    const canvas = layersToCanvasState(layers, productUrl, backgroundUrl)
    const softbox = {
      enabled: true,
      lightAngle: 45,
      lightElevation: 55,
      colorTempK: 5500,
      intensity: 100,
      softboxDiffusion: 65,
      shadowOpacity: 70,
      shadowBlur: 22,
      aoForce: 55,
      autoShadowTint: false,
    }
    const editor_document = createEditorDocument({
      pages: [layers],
      activePageIndex: 0,
      productPreviewUrl: productUrl,
      backgroundPreviewUrl: backgroundUrl,
      softbox,
    })
    return {
      id: designId,
      title: project?.title ?? `Mock design ${designId}`,
      preview_url: productUrl,
      canvas,
      editor_document,
      updated_at: project?.createdAt ?? new Date().toISOString(),
    }
  }

  const { data } = await apiClient.get<SavedDesignDTO>(
    `/designs/${encodeURIComponent(designId)}`,
    { signal },
  );
  return data;
}

export async function saveDesign(
  payload: SaveDesignRequest,
): Promise<SavedDesignDTO> {
  if (IS_MOCK) {
    const { delay } = await import("@/lib/constants/mock")
    await delay(220)
    const id =
      payload.id && /^[0-9a-f-]{36}$/i.test(payload.id)
        ? payload.id
        : crypto.randomUUID()
    const saved: SavedDesignDTO = {
      id,
      title: payload.title,
      template_id: payload.template_id ?? null,
      preview_url: payload.preview_url ?? null,
      canvas: payload.canvas,
      editor_document: payload.editor_document ?? null,
      updated_at: new Date().toISOString(),
    }
    mockDesignMemory.set(id, structuredClone(saved))
    return saved
  }

  const { data } = await apiClient.post<SavedDesignDTO>("/designs", payload);
  return data;
}

export async function deleteDesign(designId: string): Promise<void> {
  if (IS_MOCK) {
    void designId
    return
  }
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
  if (IS_MOCK) {
    const { delay, MOCK_PRODUCT_IMAGE } = await import("@/lib/constants/mock")
    await delay(900)
    void params.idempotencyKey
    const source =
      params.imageUrl?.trim() ||
      (params.file ? URL.createObjectURL(params.file) : MOCK_PRODUCT_IMAGE)
    return {
      success: true,
      cdn_url: source.startsWith("blob:") ? source : MOCK_PRODUCT_IMAGE,
      object_key: "mock/remove-bg.png",
      coins_charged: 0,
      new_balance: 999,
      width: 1134,
      height: 2638,
      content_type: "image/png",
      cost_coins: 0,
    }
  }

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

export type CreateGenerationWithMaskParams = {
  subject: Blob
  mask: Blob
  stylePrompt?: string
  productCategory?: string | null
  editorCoverOnly?: boolean
  preserveSubject?: boolean
  applyTextOverlays?: boolean
  idempotencyKey?: string
}

/** POST /generations with Original Subject + Mask (editor background plate). */
export async function createGenerationWithMask(
  params: CreateGenerationWithMaskParams,
): Promise<GenerationCreateResponse> {
  if (IS_MOCK) {
    const { delay } = await import("@/lib/constants/mock")
    await delay(400)
    void params
    return {
      task_id: "mock-generation-task",
      status: "queued",
      status_url: "/api/v1/generations/mock-generation-task",
      idempotent_replay: false,
    }
  }

  const form = new FormData()
  form.append("file", params.subject, "subject.png")
  form.append("mask_image", params.mask, "mask.png")
  form.append("editor_cover_only", String(params.editorCoverOnly ?? true))
  form.append("preserve_subject", String(params.preserveSubject ?? true))
  form.append("apply_text_overlays", String(params.applyTextOverlays ?? false))
  if (params.stylePrompt?.trim()) {
    form.append("style_prompt", params.stylePrompt.trim())
  }
  if (params.productCategory?.trim()) {
    form.append("product_category", params.productCategory.trim())
  }

  const headers: Record<string, string> = {}
  if (params.idempotencyKey) {
    headers["Idempotency-Key"] = params.idempotencyKey
  }

  const { data } = await apiClient.post<GenerationCreateResponse>(
    "/generations",
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
          if (
            typeof FormData !== "undefined" &&
            body instanceof FormData &&
            reqHeaders
          ) {
            delete reqHeaders["Content-Type"]
          }
          return body
        },
      ],
    },
  )
  return data
}

/** GET /generations/{taskId} */
export async function getGenerationStatus(
  taskId: string,
  signal?: AbortSignal,
): Promise<GenerationStatusResponse> {
  if (IS_MOCK) {
    const { delay, MOCK_CARD_IMAGE } = await import("@/lib/constants/mock")
    await delay(300)
    if (signal?.aborted) {
      throw new DOMException("Aborted", "AbortError")
    }
    return {
      task_id: taskId,
      status: "completed",
      progress: 100,
      slides: [
        {
          slide_key: "editor_bg",
          position: 1,
          status: "completed",
          progress: 100,
          result_url: MOCK_CARD_IMAGE,
        },
      ],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
    }
  }

  const { data } = await apiClient.get<GenerationStatusResponse>(
    `/generations/${encodeURIComponent(taskId)}`,
    { signal, skipErrorToast: true },
  )
  return data
}

const GENERATION_POLL_MS = 2_000
const GENERATION_POLL_TIMEOUT_MS = 180_000

/** Poll until the editor background slide (or any completed slide) has a URL. */
export async function pollGenerationBackgroundUrl(
  taskId: string,
  options?: { signal?: AbortSignal; timeoutMs?: number },
): Promise<string> {
  const timeoutMs = options?.timeoutMs ?? GENERATION_POLL_TIMEOUT_MS
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    if (options?.signal?.aborted) {
      throw new DOMException("Aborted", "AbortError")
    }
    const status = await getGenerationStatus(taskId, options?.signal)
    if (status.status === "failed") {
      const message =
        status.error?.message ||
        status.slides.find((slide) => slide.error)?.error?.message ||
        "Generation failed."
      throw new Error(message)
    }
    const editorSlide =
      status.slides.find((slide) => slide.slide_key === "editor_bg") ||
      status.slides.find((slide) => slide.slide_key === "cover") ||
      status.slides[0]
    if (
      editorSlide?.result_url &&
      (editorSlide.status === "completed" || status.status === "completed")
    ) {
      return editorSlide.result_url
    }
    await new Promise((resolve) => setTimeout(resolve, GENERATION_POLL_MS))
  }
  throw new Error("Generation timed out while waiting for the background plate.")
}
