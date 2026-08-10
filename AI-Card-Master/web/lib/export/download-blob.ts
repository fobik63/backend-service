import { saveAs } from "file-saver"

/** Trigger a browser file download from a Blob (FileSaver.js). */
function downloadBlob(blob: Blob, filename: string): void {
  saveAs(blob, filename)
}

const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a] as const

/** Minimum size for a non-empty marketplace card PNG (transparent 1080×1440 is ~tens of KB). */
const MIN_PNG_BYTES = 2_048

function dataUrlToBlob(dataUrl: string): Blob {
  if (!dataUrl || !dataUrl.startsWith("data:")) {
    throw new Error("Invalid DataURL: expected data: scheme")
  }
  const comma = dataUrl.indexOf(",")
  if (comma < 0) {
    throw new Error("Invalid DataURL: missing payload")
  }
  const header = dataUrl.slice(0, comma)
  const data = dataUrl.slice(comma + 1)
  if (!data) {
    throw new Error("Invalid DataURL: empty payload")
  }
  const isBase64 = /;base64/i.test(header)
  const mime = header.match(/data:([^;,]+)/)?.[1] ?? "application/octet-stream"
  if (!isBase64) {
    return new Blob([decodeURIComponent(data)], { type: mime })
  }
  const binary = atob(data)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new Blob([bytes], { type: mime })
}

function isPngBytes(bytes: Uint8Array): boolean {
  if (bytes.byteLength < PNG_MAGIC.length) return false
  return PNG_MAGIC.every((b, i) => bytes[i] === b)
}

/**
 * Ensure a Blob is a real non-empty PNG and return its raw bytes for JSZip.
 * Rejects 0-byte / corrupt / non-PNG payloads that would produce broken archives.
 */
async function assertValidPngBlob(blob: Blob | null | undefined): Promise<Uint8Array> {
  if (!blob || blob.size <= 0) {
    throw new Error("PNG capture returned an empty Blob")
  }
  const bytes = new Uint8Array(await blob.arrayBuffer())
  if (bytes.byteLength < MIN_PNG_BYTES) {
    throw new Error(`PNG capture too small (${bytes.byteLength} bytes)`)
  }
  if (!isPngBytes(bytes)) {
    throw new Error("PNG capture is not a valid PNG file")
  }
  return bytes
}

/** Resolve relative/public paths to absolute same-origin URLs. */
function resolveAssetUrl(url: string): string {
  if (
    url.startsWith("data:") ||
    url.startsWith("blob:") ||
    /^https?:\/\//i.test(url)
  ) {
    return url
  }
  if (typeof window === "undefined") return url
  return new URL(url, window.location.origin).href
}

/**
 * Fetch an image URL into a base64 DataURL so html-to-image embeds pixels
 * instead of depending on a second network round-trip / CORS.
 */
async function imageUrlToDataUrl(url: string): Promise<string> {
  if (url.startsWith("data:image/")) {
    // Validate embedded payload is non-empty.
    dataUrlToBlob(url)
    return url
  }

  const absolute = resolveAssetUrl(url)

  // blob: URLs must be read directly — fetch() can fail depending on origin.
  if (absolute.startsWith("blob:")) {
    const response = await fetch(absolute)
    if (!response.ok) {
      throw new Error(`Failed to read blob image: ${absolute}`)
    }
    const blob = await response.blob()
    if (blob.size <= 0) {
      throw new Error("Blob image is empty (0 bytes)")
    }
    return await blobToDataUrl(blob)
  }

  const response = await fetch(absolute, { cache: "force-cache" })
  if (!response.ok) {
    throw new Error(`Failed to load image (${response.status}): ${absolute}`)
  }
  const blob = await response.blob()
  if (blob.size <= 0) {
    throw new Error(`Image URL returned 0 bytes: ${absolute}`)
  }

  return await blobToDataUrl(blob)
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== "string" || !result.startsWith("data:")) {
        reject(new Error("FileReader did not produce a DataURL"))
        return
      }
      resolve(result)
    }
    reader.onerror = () =>
      reject(reader.error ?? new Error("FileReader failed"))
    reader.readAsDataURL(blob)
  })
}

export {
  downloadBlob,
  dataUrlToBlob,
  assertValidPngBlob,
  imageUrlToDataUrl,
  resolveAssetUrl,
  isPngBytes,
}
