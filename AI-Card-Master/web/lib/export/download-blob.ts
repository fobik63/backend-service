/** Trigger a browser file download from a Blob. */
function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  anchor.rel = "noopener"
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Delay revoke so Chromium finishes the download handshake.
  window.setTimeout(() => URL.revokeObjectURL(url), 2_000)
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [header, data] = dataUrl.split(",")
  const isBase64 = /;base64$/i.test(header ?? "")
  const mime = header?.match(/data:([^;]+)/)?.[1] ?? "application/octet-stream"
  if (!isBase64) {
    return new Blob([decodeURIComponent(data ?? "")], { type: mime })
  }
  const binary = atob(data ?? "")
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new Blob([bytes], { type: mime })
}

export { downloadBlob, dataUrlToBlob }
