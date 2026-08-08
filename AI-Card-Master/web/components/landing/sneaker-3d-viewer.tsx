"use client"

import { Center, ContactShadows, Environment, OrbitControls, useGLTF } from "@react-three/drei"
import { Canvas } from "@react-three/fiber"
import { Suspense, useEffect, useMemo, useState } from "react"
import {
  DoubleSide,
  SRGBColorSpace,
  type Group,
  type Material,
  type Mesh,
  type MeshStandardMaterial,
  type Texture,
} from "three"
import type { GLTF } from "three/examples/jsm/loaders/GLTFLoader.js"
import { Rotate3d } from "lucide-react"

import { cn } from "@/lib/utils"

/** Full PBR shoe with baseColor / normal / ORM maps + KHR material variants. */
const SHOE_MODEL_URL = "/landing/models/shoe.glb"
/** Vivid street-style albedo (alternatives: "midnight" | "beach"). */
const SHOE_COLOR_VARIANT = "street"

type Sneaker3DViewerProps = {
  className?: string
  /** Compact card mode vs full modal. */
  variant?: "card" | "modal"
  autoRotate?: boolean
  enableZoom?: boolean
  showHint?: boolean
}

type GltfWithParser = GLTF & {
  parser: {
    json: {
      extensions?: {
        KHR_materials_variants?: {
          variants: Array<{ name: string }>
        }
      }
    }
    getDependency: (type: string, index: number) => Promise<Material>
  }
}

function enhanceMaterial(material: Material) {
  const mat = material as MeshStandardMaterial
  mat.side = DoubleSide
  mat.shadowSide = DoubleSide
  mat.depthWrite = true
  mat.transparent = false
  mat.opacity = 1

  // Preserve authored PBR maps; ensure color textures decode correctly.
  const colorMaps: Array<Texture | null | undefined> = [mat.map, mat.emissiveMap]
  for (const map of colorMaps) {
    if (map) {
      map.colorSpace = SRGBColorSpace
      map.needsUpdate = true
    }
  }

  // Keep albedo dominant — avoid chrome-like gray from high metalness.
  if (mat.map) {
    mat.metalness = Math.min(mat.metalness ?? 0.2, 0.35)
    mat.roughness = Math.max(mat.roughness ?? 0.55, 0.4)
  }

  mat.needsUpdate = true
}

async function applyColorVariant(root: Group, gltf: GltfWithParser, variantName: string) {
  const variants = gltf.parser.json.extensions?.KHR_materials_variants?.variants
  if (!variants?.length) return

  const variantIndex = variants.findIndex((v: { name: string }) => v.name === variantName)
  if (variantIndex < 0) return

  const tasks: Promise<void>[] = []

  root.traverse((child) => {
    const mesh = child as Mesh & {
      userData: {
        gltfExtensions?: {
          KHR_materials_variants?: {
            mappings: Array<{ material: number; variants: number[] }>
          }
        }
      }
    }
    if (!mesh.isMesh) return

    const mappings = mesh.userData.gltfExtensions?.KHR_materials_variants?.mappings
    if (!mappings?.length) return

    const mapping = mappings.find((m) => m.variants.includes(variantIndex))
    if (!mapping) return

    tasks.push(
      gltf.parser.getDependency("material", mapping.material).then((material) => {
        const next = material.clone()
        enhanceMaterial(next)
        mesh.material = next
      })
    )
  })

  await Promise.all(tasks)
}

function SneakerModel({ scale = 1 }: { scale?: number }) {
  const gltf = useGLTF(SHOE_MODEL_URL) as unknown as GltfWithParser

  const model = useMemo(() => {
    const next = gltf.scene.clone(true) as Group

    next.traverse((child) => {
      const mesh = child as Mesh
      if (!mesh.isMesh) return
      mesh.castShadow = true
      mesh.receiveShadow = true
      // Avoid pop-in when looking into the collar / mesh openings.
      mesh.frustumCulled = false

      if (Array.isArray(mesh.material)) {
        mesh.material = mesh.material.map((m) => {
          const cloned = m.clone()
          enhanceMaterial(cloned)
          return cloned
        })
      } else if (mesh.material) {
        mesh.material = mesh.material.clone()
        enhanceMaterial(mesh.material)
      }
    })

    return next
  }, [gltf])

  useEffect(() => {
    let cancelled = false
    void applyColorVariant(model, gltf, SHOE_COLOR_VARIANT).then(() => {
      if (cancelled) return
    })
    return () => {
      cancelled = true
    }
  }, [gltf, model])

  return (
    <primitive
      object={model}
      scale={scale}
      rotation={[0.12, Math.PI * 1.05, 0.04]}
      position={[0, 0.02, 0]}
    />
  )
}

function ViewerScene({
  variant,
  autoRotate,
  enableZoom,
}: {
  variant: "card" | "modal"
  autoRotate: boolean
  enableZoom: boolean
}) {
  const isCard = variant === "card"

  return (
    <>
      <color attach="background" args={["#1a1612"]} />

      {/* Soft key + fill lighting for readable PBR color */}
      <ambientLight intensity={0.45} color="#fff6eb" />
      <directionalLight
        position={[3.2, 5.2, 2.8]}
        intensity={1.15}
        color="#ffffff"
        castShadow
        shadow-mapSize={[1024, 1024]}
        shadow-bias={-0.0002}
      />
      <directionalLight position={[-2.8, 2.2, -1.8]} intensity={0.4} color="#d4b896" />
      <directionalLight position={[0.5, 1.2, -3]} intensity={0.28} color="#a8c4ff" />

      <Suspense fallback={null}>
        <Center>
          <SneakerModel scale={isCard ? 1.05 : 1.25} />
        </Center>
        <Environment preset="studio" environmentIntensity={0.85} />
        <ContactShadows
          position={[0, -0.42, 0]}
          opacity={0.55}
          scale={isCard ? 5 : 7}
          blur={2.4}
          far={2.5}
        />
      </Suspense>

      <OrbitControls
        makeDefault
        autoRotate={autoRotate}
        autoRotateSpeed={isCard ? 1.6 : 1.15}
        enablePan={false}
        enableZoom={enableZoom}
        zoomSpeed={0.85}
        rotateSpeed={0.9}
        minDistance={isCard ? 1.35 : 1.15}
        maxDistance={isCard ? 3.4 : 4.2}
        minPolarAngle={Math.PI / 5}
        maxPolarAngle={Math.PI / 1.65}
        target={[0, 0.05, 0]}
      />
    </>
  )
}

function Sneaker3DViewer({
  className,
  variant = "card",
  autoRotate = true,
  enableZoom = true,
  showHint = true,
}: Sneaker3DViewerProps) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  return (
    <div
      className={cn(
        "relative h-full w-full overflow-hidden bg-[#1a1612]",
        className
      )}
      role="img"
      aria-label="Интерактивная 3D-модель кроссовка: вращайте, приближайте и рассматривайте со всех сторон"
    >
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden
        style={{
          background:
            "radial-gradient(ellipse 70% 55% at 50% 42%, rgba(138,115,85,0.45) 0%, rgba(42,33,24,0.2) 55%, transparent 75%)",
        }}
      />

      {mounted ? (
        <Canvas
          className="touch-none"
          dpr={[1, 1.75]}
          camera={{
            position: variant === "card" ? [0.15, 0.55, 2.35] : [0.2, 0.65, 2.55],
            fov: variant === "card" ? 38 : 36,
            // Tight near plane avoids clipping the sole/mesh when zooming into openings;
            // far stays generous for Environment + shadows.
            near: 0.01,
            far: 100,
          }}
          gl={{
            antialias: true,
            alpha: true,
            powerPreference: "high-performance",
            logarithmicDepthBuffer: true,
          }}
          shadows
        >
          <ViewerScene
            variant={variant}
            autoRotate={autoRotate}
            enableZoom={enableZoom}
          />
        </Canvas>
      ) : (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="size-10 animate-pulse rounded-full border border-copper/40 bg-copper/10" />
        </div>
      )}

      {showHint ? (
        <div className="pointer-events-none absolute right-2 bottom-2 z-10 flex items-center gap-1 rounded-md border border-white/10 bg-loft/70 px-2 py-1 font-heading text-[10px] text-emerald backdrop-blur-md">
          <Rotate3d className="size-3" aria-hidden />
          360° · drag · zoom
        </div>
      ) : null}
    </div>
  )
}

useGLTF.preload(SHOE_MODEL_URL)

export { Sneaker3DViewer }
