"use client"

/**
 * Editor paint surface — Fabric.js interactive canvas with a 3-layer stack:
 * 1) Background (AI scene / softbox)
 * 2) Product cutout (PNG, drag / scale / rotate)
 * 3) Infographics (text + chips: drag / scale / rotate / click-to-edit / fonts)
 * Export: PNG 1080×1440 via fabric-export.
 */
export { EditorFabricCanvas as EditorCanvas } from "@/components/editor/fabric-canvas"
