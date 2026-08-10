/**
 * Isolate the original product subject and derive an inpainting mask from alpha.
 * White = product (preserve), black = background (generate).
 */

export type SubjectMaskPayload = {
  subject: Blob
  mask: Blob
  width: number
  height: number
  hasTransparency: boolean
}

const ALPHA_PRODUCT_THRESHOLD = 12

function loadImageElement(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = "anonymous"
    image.onload = () => resolve(image)
    image.onerror = () =>
      reject(new Error("Failed to load product image for subject mask."))
    image.src = url
  })
}

function canvasToPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("Failed to encode subject/mask PNG."))
        return
      }
      resolve(blob)
    }, "image/png")
  })
}

/** True when the PNG has a usable alpha cutout (not fully opaque). */
export function imageHasTransparency(
  imageData: ImageData,
  threshold = ALPHA_PRODUCT_THRESHOLD,
): boolean {
  const { data } = imageData
  let transparent = 0
  let opaque = 0
  for (let i = 3; i < data.length; i += 4) {
    if (data[i]! < threshold) transparent += 1
    else opaque += 1
  }
  if (opaque === 0) return false
  return transparent / (transparent + opaque) >= 0.01
}

/**
 * Build Original Subject PNG + Mask PNG from a product preview URL (cutout preferred).
 */
export async function buildSubjectAndMaskFromUrl(
  productPreviewUrl: string,
): Promise<SubjectMaskPayload> {
  const image = await loadImageElement(productPreviewUrl)
  const width = Math.max(1, image.naturalWidth || image.width)
  const height = Math.max(1, image.naturalHeight || image.height)

  const subjectCanvas = document.createElement("canvas")
  subjectCanvas.width = width
  subjectCanvas.height = height
  const subjectCtx = subjectCanvas.getContext("2d", { willReadFrequently: true })
  if (!subjectCtx) {
    throw new Error("Canvas 2D context unavailable for subject isolation.")
  }
  subjectCtx.clearRect(0, 0, width, height)
  subjectCtx.drawImage(image, 0, 0, width, height)
  const imageData = subjectCtx.getImageData(0, 0, width, height)
  const hasTransparency = imageHasTransparency(imageData)

  const maskCanvas = document.createElement("canvas")
  maskCanvas.width = width
  maskCanvas.height = height
  const maskCtx = maskCanvas.getContext("2d")
  if (!maskCtx) {
    throw new Error("Canvas 2D context unavailable for mask export.")
  }
  const maskData = maskCtx.createImageData(width, height)
  const src = imageData.data
  const dst = maskData.data
  for (let i = 0; i < src.length; i += 4) {
    const keep = src[i + 3]! >= ALPHA_PRODUCT_THRESHOLD ? 255 : 0
    dst[i] = keep
    dst[i + 1] = keep
    dst[i + 2] = keep
    dst[i + 3] = 255
  }
  maskCtx.putImageData(maskData, 0, 0)

  const [subject, mask] = await Promise.all([
    canvasToPngBlob(subjectCanvas),
    canvasToPngBlob(maskCanvas),
  ])

  return { subject, mask, width, height, hasTransparency }
}
