export type MarketplaceId = "wildberries" | "ozon" | "yandex_market";

export type MarketplaceProfile = {
  id: MarketplaceId;
  name: string;
  cardWidth: number;
  cardHeight: number;
  maxImages: number;
};

export type MarketplaceExportPayload = {
  marketplaceId: MarketplaceId;
  generationId: string;
  imageUrls: string[];
};
