/**
 * LAN-ready Next.js dev launcher.
 * Binds to 0.0.0.0 and prints Local + Network URLs before `next dev`.
 */
import { spawn } from "node:child_process"
import os from "node:os"
import process from "node:process"

const port = String(process.env.PORT || "3000")
const hostname = "0.0.0.0"

function isPrivateIPv4(ip) {
  return (
    ip.startsWith("10.") ||
    ip.startsWith("192.168.") ||
    /^172\.(1[6-9]|2\d|3[0-1])\./.test(ip)
  )
}

/** Prefer RFC1918 Wi-Fi/LAN address for the phone Network link. */
function lanIPv4() {
  const nets = os.networkInterfaces()
  const candidates = []

  for (const addrs of Object.values(nets)) {
    for (const addr of addrs ?? []) {
      const family = addr.family
      const isV4 = family === "IPv4" || family === 4
      if (!isV4 || addr.internal) continue
      candidates.push(addr.address)
    }
  }

  return candidates.find(isPrivateIPv4) ?? candidates[0] ?? null
}

const lan = lanIPv4()

console.log("")
console.log("  AI-Card-Master web (LAN-ready)")
console.log(`  - Local:   http://localhost:${port}`)
if (lan) {
  console.log(`  - Network: http://${lan}:${port}`)
} else {
  console.log("  - Network: (no LAN IPv4 detected — check Wi-Fi adapter)")
}
console.log("")

const extraArgs = process.argv.slice(2)
const child = spawn(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["next", "dev", "--hostname", hostname, "--port", port, ...extraArgs],
  {
    stdio: "inherit",
    env: process.env,
    shell: process.platform === "win32",
  },
)

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 0)
})
