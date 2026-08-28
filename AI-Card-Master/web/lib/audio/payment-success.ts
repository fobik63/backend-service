/**
 * Short success chime after YooKassa return.
 * Prefers `/sounds/payment-success.mp3` when present, otherwise Web Audio.
 */

let audioContext: AudioContext | null = null

function getContext(): AudioContext | null {
  if (typeof window === "undefined") return null
  const Ctor =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext
  if (!Ctor) return null
  if (!audioContext) audioContext = new Ctor()
  return audioContext
}

async function playMp3(): Promise<boolean> {
  try {
    const response = await fetch("/sounds/payment-success.mp3", {
      method: "GET",
      cache: "force-cache",
    })
    if (!response.ok) return false
    const blob = await response.blob()
    if (!blob.size || !blob.type.includes("audio")) return false
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    audio.volume = 0.45
    await audio.play()
    audio.addEventListener("ended", () => URL.revokeObjectURL(url), {
      once: true,
    })
    return true
  } catch {
    return false
  }
}

function playWebAudioChime(): void {
  const ctx = getContext()
  if (!ctx) return

  const start = () => {
    const now = ctx.currentTime
    const master = ctx.createGain()
    master.gain.setValueAtTime(0.0001, now)
    master.gain.exponentialRampToValueAtTime(0.18, now + 0.02)
    master.gain.exponentialRampToValueAtTime(0.0001, now + 0.42)
    master.connect(ctx.destination)

    const notes = [523.25, 659.25, 783.99]
    notes.forEach((freq, index) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = "sine"
      osc.frequency.setValueAtTime(freq, now)
      const t = now + index * 0.07
      gain.gain.setValueAtTime(0.0001, t)
      gain.gain.exponentialRampToValueAtTime(0.6, t + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.28)
      osc.connect(gain)
      gain.connect(master)
      osc.start(t)
      osc.stop(t + 0.3)
    })
  }

  if (ctx.state === "suspended") {
    void ctx.resume().then(start).catch(() => {
      /* autoplay policy — caller may retry from a click */
    })
    return
  }
  start()
}

export async function playPaymentSuccessSound(): Promise<void> {
  if (typeof window === "undefined") return
  const played = await playMp3()
  if (!played) playWebAudioChime()
}
