export type CanvasLayerType = "image" | "text" | "shape" | "background";

export type CanvasLayer = {
  id: string;
  type: CanvasLayerType;
  name: string;
  visible: boolean;
  locked: boolean;
  opacity: number;
  zIndex: number;
};

export type CanvasDocument = {
  id: string;
  width: number;
  height: number;
  layers: CanvasLayer[];
  updatedAt: string;
};
