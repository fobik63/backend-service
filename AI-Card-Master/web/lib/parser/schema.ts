import { z } from "zod"

export const parsePlatformSchema = z.enum(["auto", "wb", "ozon"])

/**
 * POST /api/parse body.
 * Accepts `input` (preferred), or legacy `url` / `article` aliases.
 */
export const parseRequestSchema = z
  .object({
    input: z.string().trim().min(1).max(2048).optional(),
    url: z.string().trim().min(1).max(2048).optional(),
    article: z.string().trim().min(1).max(64).optional(),
    platform: parsePlatformSchema.default("auto"),
  })
  .superRefine((value, ctx) => {
    const hasAny = Boolean(value.input || value.url || value.article)
    if (!hasAny) {
      ctx.addIssue({
        code: "custom",
        message: "Provide input, url, or article.",
        path: ["input"],
      })
    }
  })
  .transform((value) => ({
    input: (value.input || value.url || value.article || "").trim(),
    platform: value.platform,
  }))

export type ParseRequestBody = z.infer<typeof parseRequestSchema>

export const parseErrorSchema = z.object({
  error: z.string(),
  code: z.string().optional(),
  details: z.unknown().optional(),
})
