export {
  apiClient,
  deleteDesign,
  generateByPrompt,
  getDesign,
  listDesigns,
  parseProduct,
  processRelighting,
  removeBackground,
  renderCanvas,
  saveDesign,
} from "./client";
export {
  changePassword,
  fetchCurrentUser,
  loginWithPassword,
  loginWithTelegram,
  registerWithPassword,
  sendOtp,
  verifyOtp,
} from "./auth";
export type { AuthSessionResponse, OtpRequestResponse } from "./auth";
export {
  createPayment,
  getBalance,
  listTariffs,
} from "./billing";
export type {
  BalanceDTO,
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
  getApiErrorMessage,
  isNetworkError,
  NETWORK_ERROR_MESSAGES,
} from "./errors";
