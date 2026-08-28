export {
  apiClient,
  createGenerationWithMask,
  deleteDesign,
  generateByPrompt,
  getDesign,
  getGenerationStatus,
  listDesigns,
  pollGenerationBackgroundUrl,
  removeBackground,
  saveDesign,
} from "./client";
export {
  changePassword,
  fetchCurrentUser,
  loginWithPassword,
  loginWithTelegram,
  logoutSession,
  registerWithPassword,
  sendOtp,
  verifyOtp,
} from "./auth";
export type { AuthSessionResponse, OtpRequestResponse } from "./auth";
export {
  createCoinPayment,
  createPayment,
  listCoinPacks,
  listTariffs,
} from "./billing";
export type {
  CoinPackDTO,
  CreateCoinPaymentResponse,
  CreatePaymentResponse,
  TariffCode,
  TariffDTO,
} from "./billing";
export {
  listExportCredentials,
  saveExportCredentials,
} from "./exports";
export type { CredentialDTO, MarketplacePlatform } from "./exports";
export {
  categoryFromCharacteristics,
  fetchProductByArticle,
  generateSeoDescription,
  listSellerProducts,
  publishToOzon,
  publishToWildberries,
} from "./marketplace";
export type {
  FetchProductResponse,
  PublishStatusDTO,
  SellerProductDTO,
  SeoGenerateRequest,
  SeoGenerateResponse,
  SeoTargetPlatform,
} from "./marketplace";
export {
  analyzeCompetitorPains,
  collectCompetitorReviews,
  enqueueEyeOfGodSpy,
  getEyeOfGodSpyJob,
  pollEyeOfGodSpyJob,
  searchCompetitors,
} from "./analytics";
export type {
  BuyerPain,
  CompetitorPainsAnalysisResponse,
  CompetitorsSearchResponse,
  CompetitorReviewsCollectionResponse,
  EyeOfGodCompetitorSummary,
  EyeOfGodDashboard,
  EyeOfGodDiscoveryHit,
  EyeOfGodEnqueueRequest,
  EyeOfGodEnqueueResponse,
  EyeOfGodFrequencyItem,
  EyeOfGodJobResponse,
  EyeOfGodJobStatus,
  EyeOfGodPlatform,
  InfographicOffer,
  NicheCompetitorCard,
} from "./analytics";
export {
  getApiErrorMessage,
  isAntibotDetectedError,
  isNetworkError,
  NETWORK_ERROR_MESSAGES,
} from "./errors";
