import { describe, expect, it } from "vitest"

import {
  DEFAULT_API_BASE_URL,
  resolveApiBaseUrl,
  rewriteLoopbackApiHost,
} from "@/lib/constants/api"

describe("resolveApiBaseUrl", () => {
  it("normalizes bare host to /api/v1", () => {
    expect(resolveApiBaseUrl("http://localhost:8000", "localhost")).toBe(
      "http://localhost:8000/api/v1",
    )
  })

  it("keeps explicit /api/v1", () => {
    expect(
      resolveApiBaseUrl("http://127.0.0.1:8000/api/v1", "127.0.0.1"),
    ).toBe("http://127.0.0.1:8000/api/v1")
  })
})

describe("rewriteLoopbackApiHost", () => {
  it("rewrites localhost API host to LAN page hostname", () => {
    expect(
      rewriteLoopbackApiHost(DEFAULT_API_BASE_URL, "192.168.1.13"),
    ).toBe("http://192.168.1.13:8000/api/v1")
  })

  it("does not rewrite when page is also loopback", () => {
    expect(rewriteLoopbackApiHost(DEFAULT_API_BASE_URL, "localhost")).toBe(
      DEFAULT_API_BASE_URL,
    )
  })

  it("does not rewrite non-loopback API hosts", () => {
    expect(
      rewriteLoopbackApiHost("http://api.example.com/api/v1", "192.168.1.13"),
    ).toBe("http://api.example.com/api/v1")
  })
})
