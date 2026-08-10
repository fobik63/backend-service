/**
 * Browser draft persistence for the editor (IndexedDB via idb-keyval).
 * Heavy preview images stay in IDB so we never hit the LocalStorage 5MB cap.
 */

import { createStore, del, get, set } from "idb-keyval"
import { z } from "zod"

import {
  createEditorDocument,
  tryEditorDocumentToState,
} from "@/lib/editor/editor-document"
import {
  DEFAULT_ARTBOARD_FORMAT_ID,
  type ArtboardFormatId,
} from "@/lib/editor/format-presets"
import type {
  ProductColorGrade,
  SoftboxSettings,
} from "@/lib/store/editor-store"
import type { CanvasLayer } from "@/types/canvas"
import type { EditorDocumentDTO } from "@/types/api"

const DRAFT_DB = "ai-card-master-editor"
const DRAFT_STORE = "session-drafts"
const DRAFT_KEY_PREFIX = "draft:"

const draftStore =
  typeof indexedDB !== "undefined"
    ? createStore(DRAFT_DB, DRAFT_STORE)
    : undefined

export type EditorSessionDraft = {
  version: 1
  updatedAt: number
  projectId: string | null
  artboardFormatId: ArtboardFormatId
  canvasWidth: number
  canvasHeight: number
  document: EditorDocumentDTO
  /** Optional Fabric JSON snapshot (custom props) for crash recovery fidelity. */
  fabricJson?: unknown
}

const artboardFormatIdSchema = z.enum([
  "wb-1080",
  "wb-900",
  "wb-1500",
  "ozon-1-1",
  "yandex-3-4",
  "yandex-1-1",
])

const sessionDraftSchema = z
  .object({
    version: z.literal(1),
    updatedAt: z.number().positive(),
    projectId: z.string().max(128).nullable(),
    artboardFormatId: artboardFormatIdSchema,
    canvasWidth: z.number().int().positive().max(8192),
    canvasHeight: z.number().int().positive().max(8192),
    document: z.unknown(),
    fabricJson: z.unknown().optional(),
  })
  .strict()

function draftKey(projectId: string | null | undefined): string {
  const id = projectId?.trim() || "new"
  return `${DRAFT_KEY_PREFIX}${id}`
}

export function buildSessionDraft(params: {
  projectId: string | null
  artboardFormatId: ArtboardFormatId
  canvasWidth: number
  canvasHeight: number
  pages: CanvasLayer[][]
  activePageIndex: number
  productPreviewUrl: string | null
  backgroundPreviewUrl: string | null
  softbox: SoftboxSettings
  colorGrade: ProductColorGrade
  backgroundColorGrade: ProductColorGrade
  fabricJson?: unknown
}): EditorSessionDraft {
  return {
    version: 1,
    updatedAt: Date.now(),
    projectId: params.projectId,
    artboardFormatId: params.artboardFormatId,
    canvasWidth: params.canvasWidth,
    canvasHeight: params.canvasHeight,
    document: createEditorDocument({
      pages: params.pages,
      activePageIndex: params.activePageIndex,
      productPreviewUrl: params.productPreviewUrl,
      backgroundPreviewUrl: params.backgroundPreviewUrl,
      softbox: params.softbox,
      colorGrade: params.colorGrade,
      backgroundColorGrade: params.backgroundColorGrade,
    }),
    fabricJson: params.fabricJson,
  }
}

export async function saveSessionDraft(
  draft: EditorSessionDraft
): Promise<void> {
  if (!draftStore) return
  await set(draftKey(draft.projectId), draft, draftStore)
}

export async function loadSessionDraft(
  projectId: string | null | undefined
): Promise<EditorSessionDraft | null> {
  if (!draftStore) return null
  try {
    const raw = await get(draftKey(projectId), draftStore)
    if (!raw) return null
    const parsed = sessionDraftSchema.safeParse(raw)
    if (!parsed.success) return null
    const state = tryEditorDocumentToState(parsed.data.document)
    if (!state) return null
    return {
      version: 1,
      updatedAt: parsed.data.updatedAt,
      projectId: parsed.data.projectId,
      artboardFormatId: parsed.data.artboardFormatId,
      canvasWidth: parsed.data.canvasWidth,
      canvasHeight: parsed.data.canvasHeight,
      document: parsed.data.document as EditorDocumentDTO,
      fabricJson: parsed.data.fabricJson,
    }
  } catch {
    return null
  }
}

export async function clearSessionDraft(
  projectId: string | null | undefined
): Promise<void> {
  if (!draftStore) return
  try {
    await del(draftKey(projectId), draftStore)
  } catch {
    // ignore
  }
}

export function sessionDraftToProjectState(draft: EditorSessionDraft): {
  projectId: string
  pages: CanvasLayer[][]
  activePageIndex: number
  softbox: SoftboxSettings
  colorGrade: ProductColorGrade
  productPreviewUrl: string | null
  backgroundPreviewUrl: string | null
  packSize: number
  artboardFormatId: ArtboardFormatId
  canvasWidth: number
  canvasHeight: number
} | null {
  const state = tryEditorDocumentToState(draft.document)
  if (!state) return null
  return {
    projectId: draft.projectId ?? "new",
    pages: state.pages,
    activePageIndex: state.activePageIndex,
    softbox: state.softbox,
    colorGrade: state.colorGrade,
    productPreviewUrl: state.productPreviewUrl,
    backgroundPreviewUrl: state.backgroundPreviewUrl,
    packSize: state.pages.length,
    artboardFormatId: draft.artboardFormatId ?? DEFAULT_ARTBOARD_FORMAT_ID,
    canvasWidth: draft.canvasWidth,
    canvasHeight: draft.canvasHeight,
  }
}

/** Debounce helper for autosave subscriptions. */
export function createDebouncedSaver(
  delayMs: number,
  save: () => Promise<void>
): { schedule: () => void; flush: () => Promise<void>; cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null
  let pending: Promise<void> | null = null

  const run = async () => {
    pending = save().finally(() => {
      pending = null
    })
    await pending
  }

  return {
    schedule() {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        timer = null
        void run()
      }, delayMs)
    },
    async flush() {
      if (timer) {
        clearTimeout(timer)
        timer = null
      }
      if (pending) await pending
      await run()
    },
    cancel() {
      if (timer) {
        clearTimeout(timer)
        timer = null
      }
    },
  }
}
