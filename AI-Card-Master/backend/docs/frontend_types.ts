/**
 * Auto-generated TypeScript types for AI-Card-Master API v0.1.0.
 * DO NOT EDIT MANUALLY — regenerate via:
 *   python -m scripts.export_ts_types
 */

/* eslint-disable */
/* tslint:disable */

export type UUID = string;

/** Canonical strategies for the three main-card variants. */
export type AbCreativeStrategy = "pain_hook" | "social_proof" | "offer_urgency";

export interface AbEnqueueResponse {
  experiment_id: string;
  status: AbExperimentStatus;
  status_url: string;
  celery_task_id?: string | null;
  idempotent_replay?: boolean;
  strategies: Array<AbCreativeStrategy>;
  duration_days: number;
  preview_titles?: Array<string>;
}

export interface AbExperimentResponse {
  experiment_id: string;
  status: AbExperimentStatus;
  status_url: string;
  marketplace: string;
  niche_key: string;
  sku: string;
  model_name: string;
  celery_task_id?: string | null;
  measurement_started_at?: string | null;
  measurement_ends_at?: string | null;
  winner_variant_id?: string | null;
  resolution_result?: {
    [key: string]: unknown;
  } | null;
  hypotheses?: Array<{
    [key: string]: unknown;
  }> | null;
  error_message?: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  variants?: Array<AbVariantResponse>;
  idempotent_replay?: boolean;
}

/** Lifecycle of an automated A/B experiment. */
export type AbExperimentStatus = "queued" | "generating" | "publishing" | "measuring" | "resolving" | "completed" | "failed";

/** Seller product context used to generate three card hypotheses. */
export interface AbProductBrief {
  sku: string;
  title: string;
  niche_key: string;
  marketplace: string;
  category?: string | null;
  key_benefits?: Array<string>;
  pain_points?: Array<string>;
  current_main_image_url?: string | null;
  current_offer?: string | null;
  brand_voice?: string | null;
  /** Marketplace product id (WB nmId / Ozon product_id). */
  nm_id?: string | null;
  /** Existing ads campaign to attach creatives to. */
  campaign_id?: string | null;
}

export interface AbResolveRequest {
  force?: boolean;
}

/** Tunable thresholds for automated A/B experiments. */
export interface AbTestConfig {
  duration_days?: number;
  variant_count?: number;
  min_impressions_for_decision?: number;
  /** Absolute CTR gap (percentage points) to break near-ties. */
  min_ctr_gap_pct?: number;
  auto_delete_losers?: boolean;
  auto_promote_winner?: boolean;
}

export interface AbTestCreateRequest {
  product: AbProductBrief;
  config?: AbTestConfig | null;
}

/** One AI-generated main-card creative hypothesis. */
export interface AbVariantHypothesis {
  strategy: AbCreativeStrategy;
  title: string;
  main_image_brief: string;
  offer_hook: string;
  headline: string;
  rationale: string;
  prompt_for_generator: string;
  confidence?: number;
}

export interface AbVariantResponse {
  id: string;
  position: number;
  strategy: AbCreativeStrategy;
  status: AbVariantStatus;
  title?: string | null;
  headline?: string | null;
  offer_hook?: string | null;
  main_image_brief?: string | null;
  rationale?: string | null;
  ads_creative_id?: string | null;
  ads_campaign_id?: string | null;
  impressions: number;
  clicks: number;
  ctr_pct: number;
  spend?: number | null;
  metrics_sampled_at?: string | null;
  error_message?: string | null;
}

/** Lifecycle of one creative hypothesis inside an experiment. */
export type AbVariantStatus = "pending" | "generated" | "published" | "measuring" | "winner" | "loser" | "deleted" | "failed";

/** Invite a manager by email or user id (exactly one required). */
export interface AddManagerRequest {
  manager_email?: string | null;
  manager_user_id?: string | null;
}

/** HTTP 202 payload: durable task_id for polling. */
export interface AnalyzeLinksEnqueueResponse {
  task_id: string;
  status: CompetitorAuditJobStatus;
  status_url: string;
  celery_task_id?: string | null;
  idempotent_replay?: boolean;
  links_count: number;
}

/** Poll response for competitor deep-scrape + Claude deep-analysis job. */
export interface AnalyzeLinksJobResponse {
  task_id: string;
  status: CompetitorAuditJobStatus;
  status_url: string;
  links: Array<string>;
  celery_task_id?: string | null;
  result?: {
    [key: string]: unknown;
  } | null;
  /** Claude deep analysis: competitor_weaknesses, conversion_triggers, actionable_blueprint per card; cross_check (OCR↔description, verdict «Аномалия» on contradictions) + advice_reliability_pct 0–100%; insufficient_data when evidence is too thin to invent weaknesses. */
  analysis?: {
    [key: string]: unknown;
  } | null;
  model_name?: string | null;
  input_tokens?: number;
  output_tokens?: number;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

/** Manual competitor audit: 1–3 WB/Ozon product URLs. */
export interface AnalyzeLinksRequest {
  /** Wildberries / Ozon product links (max 3). */
  links: Array<string>;
}

/** Referral code submitted by a newly invited user. */
export interface ApplyReferralRequest {
  referral_code: string;
}

/** Result of linking the current user to an inviter. */
export interface ApplyReferralResponse {
  applied: boolean;
  referrer_user_id: string;
}

export interface AuthSessionResponse {
  user: AuthUserResponse;
  tokens: TokenResponse;
}

export interface AuthUserResponse {
  id: string;
  email: string;
  ai_coins: number;
  subscription_status: string;
  is_admin: boolean;
  created_at?: string | null;
}

/** Marketplace badge / sticker layer (discount, rating, top sales). */
export interface BadgeLayerDTO {
  id: string;
  name: string;
  visible?: boolean;
  locked?: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Rotation in degrees (clockwise positive). */
  rotation?: number;
  opacity?: number;
  z_index?: number;
  layer_type?: string;
  badge_type: "discount" | "rating" | "top_sales";
  text: string;
  bg_color: string;
  text_color: string;
}

/** Current user's AI-coin balance and daily retention bonus state. */
export interface BalanceResponse {
  ai_coins: number;
  daily_bonus_available: boolean;
  daily_bonus_streak: number;
  daily_bonus_coins: number;
  last_daily_bonus_claimed_at: string | null;
  next_daily_bonus_available_at: string;
}

export interface Body_create_brand_lora_api_v1_brand_loras_post {
  brand_name: string;
  /** 20–30 JPEG/PNG/WebP brand reference photos */
  files: Array<string>;
  notes?: string | null;
}

export interface Body_create_bulk_generation_api_v1_bulk_generations_post {
  /** ZIP with 1–20 product images */
  file: string;
  product_category?: string | null;
  engine_mode?: string;
  post_processing_mode?: string;
  apply_text_overlays?: boolean;
  /** Comma-separated: telegram,push */
  notify_channels?: string | null;
}

export interface Body_create_claude_analysis_api_v1_claude_analyses_post {
  /** Competitor card images (1–5 JPEG/PNG/WebP) */
  images: Array<string>;
  /** JSON CompetitorTextContext including image_contexts (one entry per uploaded image), plus title/description/characteristics/reviews/prices/marketplace/product_category */
  context_json: string;
}

export interface Body_create_generation_api_v1_generations_post {
  /** JPEG, PNG, or WebP product photo */
  file: string;
  product_category?: string | null;
  engine_mode?: GenerationEngineMode;
  post_processing_mode?: GenerationPostProcessingMode;
  apply_text_overlays?: boolean;
  overlay_texts?: string | null;
}

export interface Body_create_smart_variant_sync_api_v1_smart_variants_post {
  /** Source product photo (JPEG/PNG/WebP) */
  file: string;
  /** Target colors: JSON array [{"name":"Black","hex":"#111111"},{"name":"Red","hex":"#C41E3A"}] or comma-separated names/hex (Black,#C41E3A,navy). */
  colors: string;
  product_category?: string | null;
  engine_mode?: string;
  post_processing_mode?: string;
  apply_text_overlays?: boolean;
  /** Comma-separated: telegram,push */
  notify_channels?: string | null;
}

export interface Body_enqueue_competitor_analysis_api_v1_claude_reasoning_analyze_post {
  /** Competitor card images (1–5 JPEG/PNG/WebP) */
  images: Array<string>;
  /** JSON CompetitorTextContext: title, description, characteristics, reviews_positive, reviews_negative, prices, marketplace, product_category */
  text_context?: string | null;
}

export interface Body_upload_font_api_v1_fonts_upload_post {
  /** TrueType (.ttf) or OpenType (.otf) font */
  file: string;
}

export interface Body_upload_image_api_v1_images_upload_post {
  /** Product image file */
  file: string;
}

export interface BrandDNAActiveRequest {
  is_active: boolean;
}

export interface BrandDNARefreshResponse {
  queued: boolean;
  user_id: string;
}

export interface BrandDNAResponse {
  id: string;
  status: BrandDNAStatus;
  is_active: boolean;
  midjourney_context?: string | null;
  claude_context?: string | null;
  dominant_styles?: Array<string>;
  palette_keywords?: Array<string>;
  lighting_mood?: Array<string>;
  composition_keywords?: Array<string>;
  category_hints?: Array<string>;
  sample_count: number;
  source_job_ids?: Array<string>;
  version: number;
  last_analyzed_at?: string | null;
  created_at: string;
  updated_at: string;
}

/** Lifecycle of a seller BrandDNA profile. */
export type BrandDNAStatus = "empty" | "ready" | "stale" | "analyzing";

export interface BrandLoraCreateResponse {
  profile_id: string;
  status: BrandLoraStatus;
  status_url: string;
  trigger_word: string;
  reference_count: number;
  coins_charged: number;
}

export interface BrandLoraListResponse {
  items: Array<BrandLoraResponse>;
  training_cost_coins: number;
  min_references: number;
  max_references: number;
}

export interface BrandLoraReferenceResponse {
  id: string;
  position: number;
  object_key: string;
  mime_type: string;
  size_bytes: number;
}

export interface BrandLoraResponse {
  profile_id: string;
  name: string;
  trigger_word: string;
  status: BrandLoraStatus;
  is_active: boolean;
  brand_style_prompt?: string | null;
  lora_weights_url?: string | null;
  lora_scale: number;
  reference_count: number;
  training_progress: number;
  coins_charged: number;
  notes?: string | null;
  error_message?: string | null;
  status_url: string;
  created_at: string;
  updated_at: string;
  trained_at?: string | null;
  references?: Array<BrandLoraReferenceResponse>;
}

/** Lifecycle of a brand style training profile. */
export type BrandLoraStatus = "draft" | "queued" | "training" | "ready" | "failed" | "archived";

/** Marketplaces supported by the sales / stocks / orders bridge. */
export type BridgePlatform = "wildberries" | "ozon";

export interface BulkBatchCreateResponse {
  batch_id: string;
  status: BulkBatchStatus;
  status_url: string;
  /** Product images detected in the ZIP before background unpack. */
  total_items_hint: number;
  idempotent_replay?: boolean;
}

export interface BulkBatchResponse {
  batch_id: string;
  status: BulkBatchStatus;
  product_category: string | null;
  progress: number;
  total_items: number;
  completed_items: number;
  failed_items: number;
  skipped_items: number;
  notify_telegram: boolean;
  notify_push: boolean;
  telegram_notified: boolean;
  push_notified: boolean;
  status_url: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  items?: Array<BulkItemResponse>;
  idempotent_replay?: boolean;
}

/** Lifecycle of a multi-product generation batch. */
export type BulkBatchStatus = "queued" | "unpacking" | "running" | "completed" | "partial" | "failed";

export interface BulkItemResponse {
  id: string;
  position: number;
  product_key: string;
  source_path: string;
  status: BulkItemStatus;
  generation_job_id?: string | null;
  status_url?: string | null;
  error_message?: string | null;
}

/** Lifecycle of one product inside a bulk batch. */
export type BulkItemStatus = "pending" | "queued" | "running" | "completed" | "failed" | "skipped";

/** Root canvas document: dimensions, background, and ordered layers. */
export interface CanvasStateDTO {
  width?: number;
  height?: number;
  background_color?: string;
  background_image_url?: string | null;
  layers?: Array<ImageLayerDTO | TextLayerDTO | BadgeLayerDTO | ShapeLayerDTO>;
}

/** Cohort assigned before any Claude Vision spend. */
export type CardCohortLabel = "brand_dominant" | "rising_star" | "neutral" | "insufficient_data";

/** Result of claiming a pending win-back offer. */
export interface ClaimOfferResponse {
  offer: WinbackOfferResponse;
  coins_granted: number;
  ai_coins: number | null;
}

/** Card after survivor-bias / Rising Star classification. */
export interface ClassifiedNicheCard {
  sku: string;
  title?: string | null;
  rank?: number | null;
  review_count: number;
  review_velocity_per_day: number;
  sales_growth_ratio?: number | null;
  estimated_units_sold?: number | null;
  cohort: CardCohortLabel;
  exclude_from_trigger_math: boolean;
  rising_score: number;
  reason: string;
  image_object_keys?: Array<string>;
  product_category?: string | null;
}

export interface ClaudeAnalysisCreateResponse {
  analysis_id: string;
  status: ClaudeReasoningJobStatus;
  status_url: string;
  progress: number;
  idempotent_replay?: boolean;
}

export interface ClaudeAnalysisStatusResponse {
  analysis_id: string;
  status: ClaudeReasoningJobStatus;
  status_url: string;
  progress: number;
  model_name: string;
  result?: {
    [key: string]: unknown;
  } | null;
  vision_result?: {
    [key: string]: unknown;
  } | null;
  error_message?: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface ClaudeReasoningEnqueueResponse {
  task_id: string;
  status: ClaudeReasoningJobStatus;
  status_url: string;
  celery_task_id?: string | null;
  idempotent_replay?: boolean;
}

export interface ClaudeReasoningJobResponse {
  task_id: string;
  status: ClaudeReasoningJobStatus;
  status_url: string;
  model_name: string;
  celery_task_id?: string | null;
  vision_result?: {
    [key: string]: unknown;
  } | null;
  reasoning_result?: {
    [key: string]: unknown;
  } | null;
  result?: {
    [key: string]: unknown;
  } | null;
  error_message?: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

/** Lifecycle of an async Claude reasoning job. */
export type ClaudeReasoningJobStatus = "queued" | "vision_running" | "reasoning_running" | "completed" | "failed";

/** Lifecycle of an async competitor-link audit (scrape → Claude deep analysis). */
export type CompetitorAuditJobStatus = "queued" | "scraping" | "analyzing" | "completed" | "failed";

/** Start a YooKassa checkout for one commercial tariff. */
export interface CreatePaymentRequest {
  /** start | pro | half_year | year */
  tariff_code: TariffCode;
}

/** Checkout payload returned to the frontend. */
export interface CreatePaymentResponse {
  payment_id: string;
  yookassa_payment_id: string;
  tariff_code: string;
  amount_rub: number;
  currency: string;
  status: string;
  confirmation_url: string | null;
  description: string | null;
}

/** Optional display name when creating a Pro workspace. */
export interface CreateWorkspaceRequest {
  name?: string | null;
}

export interface CredentialResponse {
  platform: MarketplacePlatform;
  is_configured: boolean;
  label?: string | null;
  updated_at?: string | null;
}

/** Result of claiming today's free retention bonus. */
export interface DailyBonusClaimResponse {
  claimed: boolean;
  coins_granted: number;
  ai_coins: number;
  daily_bonus_streak: number;
  last_daily_bonus_claimed_at: string | null;
  next_daily_bonus_available_at: string;
}

export interface DashboardResponse {
  period: MarketplaceDataPeriod;
  date_from: string;
  date_to: string;
  platforms: Array<PlatformSliceResponse>;
  totals: TotalsResponse;
}

/** All deep dependencies answered (DB, Redis, S3, FFmpeg, Celery). */
export interface DeepHealthOkResponse {
  status?: string;
  checks?: {
    [key: string]: boolean;
  };
}

/** Deep health failure with per-dependency flags. */
export interface DeepHealthUnhealthyResponse {
  status?: string;
  failed_service: string;
  checks?: {
    [key: string]: boolean;
  };
}

/** Password-confirmed GDPR erasure request. */
export interface DeleteAccountRequest {
  password: string;
  /** Must be exactly "DELETE MY ACCOUNT". */
  confirmation: string;
}

/** Confirmation that the account and personal data were erased. */
export interface DeleteAccountResponse {
  deleted?: boolean;
  user_id: string;
  email: string;
  storage_objects_deleted: number;
  storage_objects_failed: number;
  detail?: string;
}

/** Optional render overrides for HD export. */
export interface DesignRenderRequest {
  output_format?: "png" | "webp";
}

/** Presigned S3 download for a high-resolution rendered card. */
export interface DesignRenderResponse {
  design_id: string;
  object_key: string;
  presigned_url: string;
  width: number;
  height: number;
  mime_type: "image/png" | "image/webp";
  size_bytes: number;
  expires_in_seconds: number;
}

/** One-click export of a completed generation into a marketplace draft. */
export interface ExportDraftRequest {
  generation_job_id: string;
  vendor_code: string;
  extras?: {
    [key: string]: unknown;
  };
  dry_run?: boolean;
}

export interface ExportFixSuggestionResponse {
  title: string;
  description: string;
  characteristics: Array<string>;
  category_hint?: string;
  suggested_subject_id?: number | null;
  suggested_description_category_id?: number | null;
  suggested_type_id?: number | null;
  suggested_product_type?: string;
  fix_summary: string;
  removed_phrases?: Array<string>;
  model_name?: string;
  confidence?: number;
}

export interface ExportResultResponse {
  id: string;
  platform: MarketplacePlatform;
  generation_job_id: string;
  status: string;
  vendor_code: string;
  external_task_id?: string | null;
  external_offer_id?: string | null;
  message: string;
  validation: ValidationReportResponse;
  created_at: string;
}

/** Fail-Safe validator-sandbox result with optional Claude auto-fix. */
export interface FailSafeSandboxResponse {
  platform: MarketplacePlatform;
  is_valid: boolean;
  title_length: number;
  description_length: number;
  photo_count: number;
  issues: Array<ValidationIssueResponse>;
  forbidden_hits?: number;
  category_errors?: number;
  suggested_fix?: ExportFixSuggestionResponse | null;
  claude_fix_attempted?: boolean;
  claude_input_tokens?: number;
  claude_output_tokens?: number;
}

/** One differing dimension between user card and niche leader. */
export interface FeatureDelta {
  action_type: StrategyActionType;
  step_order: number;
  feature_label: string;
  user_value?: string | null;
  leader_value?: string | null;
  attributed_ctr_lift_pct: number;
  rationale: string;
  priority: RecommendationPriority;
  gap_score: number;
}

export interface FontCatalogResponse {
  fallback_family: string;
  system_families: Array<string>;
  known_families: Array<string>;
}

/** How urgent / large the detected market gap is. */
export type GapSeverity = "low" | "medium" | "high" | "critical";

export interface GenerateThreeDResponse {
  task_id: string;
  status?: string;
  status_url: string;
  celery_task_id?: string | null;
  cost_coins: number;
  idempotent_replay?: boolean;
}

export interface GenerationCreateResponse {
  task_id: string;
  status: GenerationJobStatus;
  status_url: string;
  idempotent_replay?: boolean;
}

/** Client-selected image engine profile. */
export type GenerationEngineMode = "standard" | "premium";

export interface GenerationErrorResponse {
  code: string;
  message: string;
  retryable: boolean;
}

export interface GenerationHistoryItemResponse {
  task_id: string;
  status: GenerationJobStatus;
  progress: number;
  product_category?: string | null;
  slide_count?: number;
  thumbnail_url?: string | null;
  thumbnail_mime_type?: string | null;
  thumbnail_size_bytes?: number | null;
  archive_status: "available" | "expired" | "pending" | "unavailable" | "deleted";
  archive_url?: string | null;
  archive_expires_at?: string | null;
  provider_used?: string | null;
  warning?: string | null;
  created_at: string;
  completed_at?: string | null;
}

/** Lifecycle states exposed to clients and persisted in PostgreSQL. */
export type GenerationJobStatus = "queued" | "submitting" | "waiting_webhook" | "processing" | "completed" | "failed";

/** Client-selected post-processing tier. */
export type GenerationPostProcessingMode = "fast" | "hd_face_fix";

export interface GenerationSlideResponse {
  slide_key: string;
  position: number;
  status: SlideStatus;
  progress: number;
  provider_used?: string | null;
  result_url?: string | null;
  warning?: string | null;
  error?: GenerationErrorResponse | null;
}

export interface GenerationStatusResponse {
  task_id: string;
  status: GenerationJobStatus;
  progress: number;
  provider_used?: string | null;
  warning?: string | null;
  archive_url?: string | null;
  marketplace_text?: MarketplaceTextResponse | null;
  slides: Array<GenerationSlideResponse>;
  error?: GenerationErrorResponse | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface GpuRentalSessionResponse {
  session_id: string;
  status: string;
  provider_name: string;
  instance_type: string;
  coins_per_minute: number;
  hourly_rate_coins: number;
  started_at?: string | null;
  stopped_at?: string | null;
  total_cost_coins: number;
}

export interface GpuRentalStartRequest {
  instance_type?: string | null;
}

export interface GpuRentalStopRequest {
  session_id: string;
}

export interface HTTPValidationError {
  detail?: Array<ValidationError>;
}

/** Response schema for health checks. */
export interface HealthResponse {
  /** Health status */
  status: string;
  /** Additional diagnostic detail */
  detail: string;
}

/** Raster / product image layer with optional crop window. */
export interface ImageLayerDTO {
  id: string;
  name: string;
  visible?: boolean;
  locked?: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Rotation in degrees (clockwise positive). */
  rotation?: number;
  opacity?: number;
  z_index?: number;
  layer_type?: string;
  url: string;
  scale_x?: number;
  scale_y?: number;
  crop_x?: number | null;
  crop_y?: number | null;
  crop_w?: number | null;
  crop_h?: number | null;
}

/** Marketplace metric an insight claims to influence. */
export type InsightMetric = "ctr" | "conversion" | "attention" | "trust";

/** Recommendation urgency for the frontend. */
export type InsightPriority = "high" | "medium" | "low";

/** One actionable step in the killer playbook. */
export interface KillerRecommendation {
  step_number: number;
  action_type: StrategyActionType;
  title: string;
  instruction: string;
  rationale: string;
  attributed_ctr_lift_pct: number;
  priority: RecommendationPriority;
  user_current?: string | null;
  leader_reference?: string | null;
  expected_impact: string;
  advice_reliability_pct?: number;
}

/** Rendered legal page payload for web / mobile clients. */
export interface LegalDocumentResponse {
  slug: string;
  title: string;
  version_date: string;
  content_type?: string;
  content: string;
  operator_name: string;
  support_email: string;
  privacy_email: string;
}

/** Bind the user's Telegram chat id for trigger messages. */
export interface LinkTelegramRequest {
  /** Telegram user/chat id */
  telegram_id: number;
}

/** Confirmation that Telegram was linked. */
export interface LinkTelegramResponse {
  linked: boolean;
  telegram_id: number;
}

/** Minimal process-alive payload. */
export interface LivenessResponse {
  /** Always 'ok' when the process answers */
  status?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

/** Relative reporting window for the personal cabinet dashboard. */
export type MarketplaceDataPeriod = "day" | "week" | "month";

/** Supported one-click export destinations. */
export type MarketplacePlatform = "wildberries" | "ozon" | "amazon";

export interface MarketplaceTextResponse {
  title: string;
  description: string;
  characteristics: Array<string>;
}

/** JSON contract for clothing virtual try-on on an AI model. */
export interface ModelModeRequest {
  /** Private S3 object key of the uploaded clothing source image. */
  source_image_object_key: string;
  /** AI model height in centimeters. */
  height_cm: number;
  body_type: "slim" | "regular" | "athletic" | "plus_size";
  ethnicity: "european" | "asian" | "middle_eastern" | "african" | "latino" | "mixed";
  engine_mode?: GenerationEngineMode;
  post_processing_mode?: GenerationPostProcessingMode;
  background?: string | null;
  pose?: string | null;
}

/** Niche-level popularity slice. */
export interface NicheBreakdownResponse {
  niche_key: string;
  niche_title: string;
  selection_count: number;
  share_percent: number;
  top_style?: string | null;
}

/** One marketplace card with review + stock-parser dynamics. */
export interface NicheCardSignal {
  sku: string;
  title?: string | null;
  rank?: number | null;
  review_count: number;
  review_count_delta?: number;
  observation_days?: number;
  avg_daily_sales_baseline?: number | null;
  avg_daily_sales_recent?: number | null;
  stock_quantity_start?: number | null;
  stock_quantity_end?: number | null;
  image_object_keys?: Array<string>;
  product_category?: string | null;
}

/** Deterministic pre-Vision filter result for a niche top-N scan. */
export interface NicheFilterReport {
  niche_key: string;
  marketplace: string;
  scanned_count: number;
  config: VisualAuditFilterConfig;
  brand_dominant?: Array<ClassifiedNicheCard>;
  rising_stars?: Array<ClassifiedNicheCard>;
  neutrals?: Array<ClassifiedNicheCard>;
  insufficient?: Array<ClassifiedNicheCard>;
  vision_queue?: Array<ClassifiedNicheCard>;
  filter_notes?: Array<string>;
}

/** Detected demand/supply imbalance for a design style. */
export interface NicheGapOpportunity {
  design_style: string;
  niche_key: string;
  primary_query: string;
  related_queries?: Array<string>;
  baseline_volume: number;
  recent_volume: number;
  growth_ratio: number;
  top_card_count: number;
  best_rank?: number | null;
  gap_score: number;
  severity: GapSeverity;
  notification_message: string;
  reason: string;
}

export interface OracleEnqueueResponse {
  task_id: string;
  status: OracleJobStatus;
  status_url: string;
  celery_task_id?: string | null;
  idempotent_replay?: boolean;
  opportunity_preview_count: number;
  notification_preview?: Array<string>;
}

/** Tunable thresholds for demand-vs-supply niche detection. */
export interface OracleGapConfig {
  min_query_growth_ratio?: number;
  min_recent_query_volume?: number;
  max_top_cards_for_gap?: number;
  min_gap_score?: number;
  max_alerts?: number;
  top_rank_ceiling?: number;
}

export interface OracleJobResponse {
  task_id: string;
  status: OracleJobStatus;
  status_url: string;
  niche_key: string;
  marketplace: string;
  model_name: string;
  celery_task_id?: string | null;
  scan_report?: {
    [key: string]: unknown;
  } | null;
  prediction_result?: {
    [key: string]: unknown;
  } | null;
  notifications?: Array<string> | null;
  error_message?: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

/** Lifecycle of an async Oracle prediction job. */
export type OracleJobStatus = "queued" | "scanning" | "enriching" | "completed" | "failed";

export interface OracleNotificationItem {
  job_id: string;
  niche_key: string;
  marketplace: string;
  message: string;
  created_at: string;
}

export interface OracleNotificationsResponse {
  items: Array<OracleNotificationItem>;
  total: number;
}

export interface OraclePredictRequest {
  niche_key: string;
  marketplace: string;
  search_queries: Array<SearchQuerySignal>;
  supply_cards?: Array<SupplyCardSignal>;
  gap_config?: OracleGapConfig | null;
}

/** Deterministic pre-Claude gap scan result. */
export interface OracleScanReport {
  marketplace: string;
  niche_key: string;
  config: OracleGapConfig;
  scanned_queries: number;
  scanned_supply_cards: number;
  demand_clusters?: Array<StyleDemandCluster>;
  supply_snapshots?: Array<StyleSupplySnapshot>;
  opportunities?: Array<NicheGapOpportunity>;
  scan_notes?: Array<string>;
}

export interface OrdersMetricsResponse {
  count: number;
  cancelled_count: number;
}

export interface PainAnalysisBody {
  product_name: string;
  product_specs?: string;
  platform: string;
  raw_negative_reviews: Array<string>;
}

export interface PainAnalysisEnqueueResponse {
  task_id: string;
  status: PainAnalysisJobStatus;
  status_url: string;
  celery_task_id?: string | null;
  idempotent_replay?: boolean;
  junk_preview_count: number;
  pain_preview_count: number;
  pain_preview?: Array<string>;
}

export interface PainAnalysisJobResponse {
  task_id: string;
  status: PainAnalysisJobStatus;
  status_url: string;
  product_name: string;
  platform: string;
  model_name: string;
  celery_task_id?: string | null;
  filter_preview?: {
    [key: string]: unknown;
  } | null;
  analysis_result?: {
    [key: string]: unknown;
  } | null;
  error_message?: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

/** Lifecycle of an async pain-analysis job. */
export type PainAnalysisJobStatus = "queued" | "filtering" | "analyzing" | "completed" | "failed";

/** Strict JSON output matching plan §71 schema. */
export interface PainAnalysisResult {
  filtered_out_junk?: Array<string>;
  real_product_pains: Array<string>;
  infographic_badges: Array<string>;
  seo_title: string;
  seo_description: string;
  model_name?: string;
  insufficient_data?: boolean;
}

export interface PhotoLimitsResponse {
  min_count: number;
  max_count: number;
  min_width: number;
  min_height: number;
  max_bytes: number;
  allowed_formats: Array<string>;
  aspect_ratio?: number | null;
  require_portrait: boolean;
}

export interface PlatformSliceResponse {
  platform: BridgePlatform;
  connected: boolean;
  sales: SalesMetricsResponse;
  stocks: StocksMetricsResponse;
  orders: OrdersMetricsResponse;
  error?: string | null;
}

export interface PushNotificationResponse {
  id: string;
  title: string;
  body: string;
  data: {
    [key: string]: string;
  };
  read_at: string | null;
  created_at: string;
}

/** All critical dependencies answered. */
export interface ReadinessOkResponse {
  /** Ready to accept traffic */
  status?: string;
}

/** Dependency readiness without exposing credentials or internal URLs. */
export interface ReadinessResponse {
  status: string;
  dependencies: {
    [key: string]: boolean;
  };
}

/** At least one dependency failed; ``failed_service`` names the first one. */
export interface ReadinessUnhealthyResponse {
  /** Not ready for traffic */
  status?: string;
  /** First failing dependency: postgres | redis | celery */
  failed_service: string;
}

/** How urgently the seller should apply a killer step. */
export type RecommendationPriority = "critical" | "high" | "medium" | "low";

/** Current user's referral code and earned bonus counters. */
export interface ReferralStatsResponse {
  referral_code: string;
  invited_count: number;
  paid_invited_count: number;
  earned_free_credits: number;
  bonus_credits_per_friend: number;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
}

/** JSON-friendly studio settings; coerces into strict ``RenderSettingsDTO``. */
export interface RenderSettingsBody {
  aspect_ratio?: "1:1" | "3:4";
  width?: number | null;
  height?: number | null;
  long_side?: number | null;
  lighting_preset?: string;
  background_mode?: string;
  background_rgb?: Array<unknown>;
  elevation_degrees?: number;
  fill_ratio?: number;
  fov_degrees?: number;
  shadow_catcher?: {
    [key: string]: unknown;
  } | null;
}

export interface RequirementsResponse {
  platform: MarketplacePlatform;
  display_name: string;
  text: TextLimitsResponse;
  photo: PhotoLimitsResponse;
  notes: Array<string>;
}

/** Response schema for the root endpoint. */
export interface RootResponse {
  /** Service name */
  service: string;
  /** Service version */
  version: string;
  /** Human-friendly welcome message */
  message: string;
  /** Swagger UI path */
  docs_url?: string;
}

export interface SalesMetricsResponse {
  count: number;
  revenue: number;
  currency: string;
}

/** Store encrypted seller API credentials for one marketplace. */
export interface SaveCredentialsRequest {
  credentials: {
    [key: string]: string;
  };
  label?: string | null;
}

/** Create or update a user canvas project.

When ``id`` is set, the design is updated (must belong to the caller).
Otherwise a new design row is inserted. */
export interface SaveDesignRequest {
  /** Existing design id for upsert; omit to create. */
  id?: string | null;
  title: string;
  /** Optional source preset this design was forked from. */
  template_id?: string | null;
  preview_url?: string | null;
  canvas: CanvasStateDTO;
}

/** User-owned design project returned by list/save endpoints. */
export interface SavedDesignDTO {
  id: string;
  title: string;
  template_id?: string | null;
  canvas: CanvasStateDTO;
  preview_url?: string | null;
  updated_at: string;
}

/** All projects for the authenticated user. */
export interface SavedDesignListResponse {
  items: Array<SavedDesignDTO>;
  total: number;
}

/** One marketplace search query with demand dynamics. */
export interface SearchQuerySignal {
  query_text: string;
  design_style: string;
  niche_key: string;
  baseline_volume: number;
  recent_volume: number;
  observation_days?: number;
  related_queries?: Array<string>;
}

/** Primitive shape layer (rectangle or circle). */
export interface ShapeLayerDTO {
  id: string;
  name: string;
  visible?: boolean;
  locked?: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Rotation in degrees (clockwise positive). */
  rotation?: number;
  opacity?: number;
  z_index?: number;
  layer_type?: string;
  shape_type: "rect" | "circle";
  fill_color: string;
  stroke_color?: string | null;
  stroke_width?: number;
}

/** Share one of the caller's generation jobs with the team. */
export interface ShareGenerationRequest {
  generation_job_id: string;
}

export interface SharedGenerationResponse {
  share_id: string;
  workspace_id: string;
  generation_job_id: string;
  shared_by_user_id: string;
  shared_by_email: string;
  status: string;
  product_category?: string | null;
  thumbnail_url?: string | null;
  thumbnail_mime_type?: string | null;
  archive_url?: string | null;
  slide_result_urls: Array<string>;
  shared_at: string;
  job_created_at: string;
}

/** Lifecycle of one slide inside a five-slide generation. */
export type SlideStatus = "queued" | "submitting" | "waiting_webhook" | "processing" | "completed" | "failed";

export interface StocksMetricsResponse {
  sku_count: number;
  total_quantity: number;
}

/** Ordered killer actions: background first → title last. */
export type StrategyActionType = "replace_background" | "restructure_first_slide" | "add_infographic" | "adjust_contrast_accents" | "rewrite_offer" | "update_price_badge" | "change_title";

/** Seller or niche-leader card snapshot used for killer comparison. */
export interface StrategyCardSnapshot {
  sku: string;
  title: string;
  niche_key: string;
  background_style?: string | null;
  first_slide_pain_hook?: string | null;
  infographic_structure?: string | null;
  contrast_accents?: string | null;
  offer_text?: string | null;
  price_badge?: string | null;
  ctr_pct: number;
  conversion_rate_pct?: number | null;
  review_count?: number;
  rank?: number | null;
  image_urls?: Array<string>;
}

/** Tunable thresholds for user-vs-leader comparison. */
export interface StrategyCompareConfig {
  min_ctr_lift_pct?: number;
  min_absolute_ctr_gap?: number;
  max_recommendations?: number;
  require_leader_ctr_advantage?: boolean;
}

/** Deterministic pre-Claude comparison result. */
export interface StrategyCompareReport {
  marketplace: string;
  niche_key: string;
  config: StrategyCompareConfig;
  user_sku: string;
  leader_sku: string;
  user_ctr_pct: number;
  leader_ctr_pct: number;
  total_ctr_lift_pct: number;
  deltas?: Array<FeatureDelta>;
  recommendations?: Array<KillerRecommendation>;
  compare_notes?: Array<string>;
}

export interface StrategyEnqueueResponse {
  task_id: string;
  status: StrategyJobStatus;
  status_url: string;
  celery_task_id?: string | null;
  idempotent_replay?: boolean;
  recommendation_preview_count: number;
  total_ctr_lift_pct: number;
  rationale_preview?: Array<string>;
}

export interface StrategyJobResponse {
  task_id: string;
  status: StrategyJobStatus;
  status_url: string;
  niche_key: string;
  marketplace: string;
  model_name: string;
  celery_task_id?: string | null;
  compare_report?: {
    [key: string]: unknown;
  } | null;
  plan_result?: {
    [key: string]: unknown;
  } | null;
  error_message?: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

/** Lifecycle of an async AI Strategy job. */
export type StrategyJobStatus = "queued" | "comparing" | "planning" | "completed" | "failed";

export interface StrategyPlanRequest {
  niche_key: string;
  marketplace: string;
  user_card: StrategyCardSnapshot;
  leader_card: StrategyCardSnapshot;
  compare_config?: StrategyCompareConfig | null;
}

/** AI insight attached to a popular style preset. */
export interface StyleAiInsightResponse {
  code: string;
  /** Human-readable insight, e.g. "Этот фон повышает CTR на 15%" */
  message: string;
  metric: InsightMetric;
  estimated_lift_percent: number;
  confidence: number;
  rationale: string;
}

/** Actionable AI recommendation for the product UI. */
export interface StyleAiRecommendationResponse {
  code: string;
  priority: InsightPriority;
  message: string;
  niche_key: string;
  selected_style: string;
  slide_key: string;
  metric: InsightMetric;
  estimated_lift_percent: number;
}

/** Aggregated demand for one design style inside a niche. */
export interface StyleDemandCluster {
  design_style: string;
  niche_key: string;
  query_count: number;
  baseline_volume: number;
  recent_volume: number;
  growth_ratio: number;
  primary_query: string;
  related_queries?: Array<string>;
}

/** JSON analytics payload for internal style-preset tracking.

Example shape::

    {
      "generated_at": "2026-08-06T18:00:00Z",
      "period_days": 30,
      "total_selections": 1500,
      "unique_presets": 15,
      "top_presets": [
        {
          "rank": 1,
          "niche_key": "perfume",
          "niche_title": "Парфюмерия",
          "slide_key": "cover",
          "selected_style": "studio hero bottle",
          "selection_count": 320,
          "share_percent": 21.3,
          "ai_insight": {
            "code": "ctr_lift_cover",
            "message": "Этот фон повышает CTR на 15%",
            "metric": "ctr",
            "estimated_lift_percent": 15.0,
            "confidence": 0.84,
            "rationale": "..."
          }
        }
      ],
      "by_niche": [...],
      "ai_recommendations": [...]
    } */
export interface StylePresetAnalyticsResponse {
  generated_at: string;
  period_days: number;
  total_selections: number;
  unique_presets: number;
  top_presets: Array<TopStylePresetResponse>;
  by_niche: Array<NicheBreakdownResponse>;
  ai_recommendations: Array<StyleAiRecommendationResponse>;
}

/** How many top cards currently serve a design style. */
export interface StyleSupplySnapshot {
  design_style: string;
  niche_key: string;
  top_card_count: number;
  best_rank?: number | null;
  skus?: Array<string>;
}

/** One top-card listing that currently covers (or fails to cover) demand. */
export interface SupplyCardSignal {
  sku: string;
  title?: string | null;
  rank: number;
  design_style: string;
  niche_key: string;
  review_count?: number;
  matched_query?: string | null;
}

/** Stable machine codes for the commercial tariff grid. */
export type TariffCode = "start" | "pro" | "half_year" | "year";

/** Public tariff card for the frontend pricing page. */
export interface TariffResponse {
  code: string;
  title: string;
  duration_days: number;
  ai_coins: number;
  price_rub: number;
  amount_value: string;
  subscription_status: string;
  description: string;
}

/** Full preset including validated canvas document. */
export interface TemplateDetailDTO {
  id: string;
  title: string;
  category: string;
  is_preset?: boolean;
  author_id?: string | null;
  canvas: CanvasStateDTO;
  preview_url?: string | null;
  downloads_count: number;
  created_at: string;
  updated_at: string;
}

/** Paginated public preset catalog. */
export interface TemplateListResponse {
  items: Array<TemplateSummaryDTO>;
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

/** Lightweight preset row for catalog listings. */
export interface TemplateSummaryDTO {
  id: string;
  title: string;
  category: string;
  preview_url?: string | null;
  downloads_count: number;
  created_at: string;
}

/** Typography layer for titles, offers, and body copy. */
export interface TextLayerDTO {
  id: string;
  name: string;
  visible?: boolean;
  locked?: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Rotation in degrees (clockwise positive). */
  rotation?: number;
  opacity?: number;
  z_index?: number;
  layer_type?: string;
  text: string;
  font_family: string;
  font_size: number;
  font_weight: string;
  color_hex: string;
  alignment?: "left" | "center" | "right";
  line_height?: number;
  letter_spacing?: number;
  shadow_color?: string | null;
  shadow_blur?: number;
}

export interface TextLimitsResponse {
  title_min: number;
  title_max: number;
  description_min: number;
  description_max: number;
  characteristics_min: number;
  characteristics_max: number;
  characteristic_max_length: number;
}

export interface ThreeDAssetItemResponse {
  id: string;
  task_id: string;
  file_glb_url?: string | null;
  file_usdz_url?: string | null;
  file_obj_url?: string | null;
  preview_png_url?: string | null;
  thumbnail_url?: string | null;
  polycount_actual?: number | null;
  file_size_bytes?: number | null;
}

export interface ThreeDAssetsListResponse {
  items: Array<ThreeDAssetItemResponse>;
  total: number;
  limit: number;
  offset: number;
}

export interface ThreeDTaskResponse {
  id: string;
  status: string;
  input_type: string;
  prompt?: string | null;
  source_image_url?: string | null;
  provider_name?: string | null;
  provider_job_id?: string | null;
  cost_coins: number;
  progress_percent: number;
  stage?: string | null;
  stage_label?: string | null;
  output_format?: string | null;
  celery_task_id?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ThreeDVideoTaskResponse {
  video_task_id: string;
  task_3d_id: string;
  status: string;
  resolution: string;
  fps: number;
  duration_seconds: number;
  rotation_direction: string;
  elevation_angle: number;
  background_type: string;
  cost_coins: number;
  progress_percent: number;
  stage?: string | null;
  stage_label?: string | null;
  celery_task_id?: string | null;
  error_detail?: string | null;
  execution_time_ms?: number | null;
  file_mp4_url?: string | null;
  file_webp_url?: string | null;
  file_gif_url?: string | null;
  width?: number | null;
  height?: number | null;
  file_size_bytes?: number | null;
  coins_held?: boolean;
  coins_captured?: boolean;
  coins_refunded?: boolean;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type?: string;
}

/** One ranked style preset with selection stats and AI insight. */
export interface TopStylePresetResponse {
  rank: number;
  niche_key: string;
  niche_title: string;
  slide_key: string;
  selected_style: string;
  selection_count: number;
  share_percent: number;
  ai_insight: StyleAiInsightResponse;
}

export interface TotalsResponse {
  sales: SalesMetricsResponse;
  stocks: StocksMetricsResponse;
  orders: OrdersMetricsResponse;
  connected_platforms: number;
}

/** Response schema for a successful custom font upload. */
export interface UploadFontResponse {
  /** Operation success flag */
  success?: boolean;
  /** custom_fonts row id */
  id: string;
  font_name: string;
  font_family: string;
  file_path_ttf: string;
  /** Optional S3 URI (s3://bucket/key) when cloud upload succeeded */
  file_path_woff2?: string | null;
  is_system?: boolean;
  /** Primary persistence backend used for this upload */
  storage: "s3" | "local";
  size_bytes: number;
}

/** Response schema for successful image upload. */
export interface UploadImageResponse {
  /** Operation success flag */
  success: boolean;
  /** Server-side unique file identifier */
  file_id: string;
  /** Original client filename */
  original_filename: string;
  /** Stored filename on the server */
  stored_filename: string;
  /** Detected MIME type */
  content_type: string;
  /** Stored file size in bytes */
  size_bytes: number;
  /** Absolute storage path */
  location: string;
  /** Relative API path for referencing the uploaded asset */
  public_path: string;
}

/** Fail-Safe sandbox request (plan §59). */
export interface ValidateExportRequest {
  generation_job_id: string;
  platform: MarketplacePlatform;
  extras?: {
    [key: string]: unknown;
  };
  require_category_ids?: boolean;
  suggest_fix?: boolean;
}

export interface ValidationError {
  loc: Array<string | number>;
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export interface ValidationIssueResponse {
  code: string;
  message: string;
  severity: ValidationSeverity;
  field?: string | null;
}

export interface ValidationReportResponse {
  platform: MarketplacePlatform;
  is_valid: boolean;
  title_length: number;
  description_length: number;
  photo_count: number;
  issues: Array<ValidationIssueResponse>;
  forbidden_hits?: number;
  category_errors?: number;
}

/** Severity of an automatic pre-export check. */
export type ValidationSeverity = "error" | "warning";

export interface VariantItemResponse {
  id: string;
  position: number;
  color_name: string;
  color_hex?: string | null;
  color_slug: string;
  status: VariantItemStatus;
  generation_job_id?: string | null;
  status_url?: string | null;
  error_message?: string | null;
}

/** Lifecycle of one color variant inside a sync job. */
export type VariantItemStatus = "pending" | "recoloring" | "queued" | "running" | "completed" | "failed" | "skipped";

export interface VariantSyncCreateResponse {
  sync_id: string;
  status: VariantSyncStatus;
  status_url: string;
  total_colors: number;
  idempotent_replay?: boolean;
}

export interface VariantSyncResponse {
  sync_id: string;
  status: VariantSyncStatus;
  product_category: string | null;
  progress: number;
  total_items: number;
  completed_items: number;
  failed_items: number;
  skipped_items: number;
  notify_telegram: boolean;
  notify_push: boolean;
  telegram_notified: boolean;
  push_notified: boolean;
  status_url: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  items?: Array<VariantItemResponse>;
  idempotent_replay?: boolean;
}

/** Lifecycle of a multi-color variant sync job. */
export type VariantSyncStatus = "queued" | "recoloring" | "running" | "completed" | "partial" | "failed";

/** Token returned by Turnstile / reCAPTCHA widget on the frontend. */
export interface VerifyCaptchaRequest {
  token: string;
  /** Optional override; defaults to CAPTCHA_PROVIDER / auto. */
  provider?: "turnstile" | "recaptcha" | null;
  /** FingerprintJS visitorId (also accepted via X-Visitor-Id). */
  visitorId?: string | null;
}

/** Confirmation that the temporary CAPTCHA block was lifted. */
export interface VerifyCaptchaResponse {
  success?: boolean;
  cleared?: boolean;
  provider: string;
}

export interface VideoRenderAcceptedResponse {
  video_task_id: string;
  status?: string;
  status_url: string;
  ws_url: string;
  celery_task_id?: string | null;
  cost_coins: number;
  idempotent_replay?: boolean;
}

/** Enqueue body: source mesh task + studio ``RenderSettingsDTO``. */
export interface VideoRenderRequest {
  task_3d_id: string;
  render_settings: RenderSettingsBody;
  fps?: number;
  duration_seconds?: number;
  rotation_direction?: "clockwise" | "counter_clockwise";
}

export interface VisualAuditEnqueueResponse {
  task_id: string;
  status: VisualAuditJobStatus;
  status_url: string;
  celery_task_id?: string | null;
  idempotent_replay?: boolean;
  rising_star_preview_count: number;
  brand_dominant_excluded_count: number;
}

/** Tunable thresholds for Brand Dominant / Rising Star selection. */
export interface VisualAuditFilterConfig {
  top_n?: number;
  brand_dominant_soft_reviews?: number;
  brand_dominant_hard_reviews?: number;
  rising_min_reviews?: number;
  rising_max_reviews?: number;
  min_sales_growth_ratio?: number;
  min_review_velocity_per_day?: number;
  max_rising_stars_for_vision?: number;
}

export interface VisualAuditJobResponse {
  task_id: string;
  status: VisualAuditJobStatus;
  status_url: string;
  niche_key: string;
  marketplace: string;
  model_name: string;
  celery_task_id?: string | null;
  filter_report?: {
    [key: string]: unknown;
  } | null;
  vision_dissections?: Array<{
    [key: string]: unknown;
  }> | null;
  generator_config?: {
    [key: string]: unknown;
  } | null;
  error_message?: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

/** Lifecycle of an async niche visual-audit job. */
export type VisualAuditJobStatus = "queued" | "filtering" | "vision_running" | "aggregating" | "completed" | "failed";

export interface VisualAuditPreviewRequest {
  niche_key: string;
  marketplace: string;
  cards: Array<NicheCardSignal>;
  filter_config?: VisualAuditFilterConfig | null;
}

/** YooKassa expects a quick 200 acknowledgement. */
export interface WebhookAckResponse {
  success?: boolean;
  detail: string;
  already_processed?: boolean;
}

/** One-shot retention offer shown on cancel / inactivity. */
export interface WinbackOfferResponse {
  id: string;
  trigger: string;
  offer_type: string;
  status: string;
  title: string;
  message: string;
  free_generations: number | null;
  discount_percent: number | null;
  expires_at: string;
  claimed_at: string | null;
  created_at: string;
}

export interface WorkspaceMemberResponse {
  user_id: string;
  email: string;
  role: WorkspaceRole;
  joined_at: string;
}

export interface WorkspaceResponse {
  id: string;
  owner_user_id: string;
  name: string;
  max_managers: number;
  manager_count: number;
  members: Array<WorkspaceMemberResponse>;
  created_at: string;
}

/** Membership role inside a Pro workspace team. */
export type WorkspaceRole = "owner" | "manager";

export interface app__api__three_d__WebhookAck {
  success?: boolean;
  accepted?: boolean;
  already_processed?: boolean;
  task_id?: string | null;
  status?: string | null;
}

export interface app__api__webhooks__midjourney__WebhookAck {
  success?: boolean;
  accepted?: boolean;
  already_processed?: boolean;
}

/** OpenAPI path → HTTP method → operationId (when present). */
export interface ApiRouteMap {
  "/": {
    get: "root__get";
  };
  "/api/v1/3d/assets": {
    get: "list_three_d_assets_api_v1_3d_assets_get";
  };
  "/api/v1/3d/generate": {
    post: "generate_three_d_api_v1_3d_generate_post";
  };
  "/api/v1/3d/gpu-rental/start": {
    post: "start_gpu_rental_api_v1_3d_gpu_rental_start_post";
  };
  "/api/v1/3d/gpu-rental/stop": {
    post: "stop_gpu_rental_api_v1_3d_gpu_rental_stop_post";
  };
  "/api/v1/3d/tasks/{task_id}": {
    get: "get_three_d_task_api_v1_3d_tasks__task_id__get";
  };
  "/api/v1/3d/video/render": {
    post: "render_three_d_video_api_v1_3d_video_render_post";
  };
  "/api/v1/3d/video/{video_task_id}": {
    get: "get_three_d_video_task_api_v1_3d_video__video_task_id__get";
  };
  "/api/v1/3d/webhook/{provider_name}": {
    post: "receive_three_d_webhook_api_v1_3d_webhook__provider_name__post";
  };
  "/api/v1/ab-tests": {
    get: "list_ab_experiments_api_v1_ab_tests_get";
    post: "enqueue_ab_experiment_api_v1_ab_tests_post";
  };
  "/api/v1/ab-tests/preview": {
    post: "preview_ab_hypotheses_api_v1_ab_tests_preview_post";
  };
  "/api/v1/ab-tests/{experiment_id}": {
    get: "get_ab_experiment_api_v1_ab_tests__experiment_id__get";
  };
  "/api/v1/ab-tests/{experiment_id}/refresh-metrics": {
    post: "refresh_ab_metrics_api_v1_ab_tests__experiment_id__refresh_metrics_post";
  };
  "/api/v1/ab-tests/{experiment_id}/resolve": {
    post: "resolve_ab_experiment_api_v1_ab_tests__experiment_id__resolve_post";
  };
  "/api/v1/account": {
    delete: "delete_my_account_api_v1_account_delete";
  };
  "/api/v1/ai-strategy/plan": {
    post: "enqueue_strategy_plan_api_v1_ai_strategy_plan_post";
  };
  "/api/v1/ai-strategy/preview": {
    post: "preview_strategy_compare_api_v1_ai_strategy_preview_post";
  };
  "/api/v1/ai-strategy/{task_id}": {
    get: "get_strategy_job_api_v1_ai_strategy__task_id__get";
  };
  "/api/v1/analytics/analyze-links": {
    post: "analyze_competitor_links_api_v1_analytics_analyze_links_post";
  };
  "/api/v1/analytics/analyze-links/{task_id}": {
    get: "get_analyze_links_job_api_v1_analytics_analyze_links__task_id__get";
  };
  "/api/v1/analytics/style-presets": {
    get: "get_style_preset_analytics_api_v1_analytics_style_presets_get";
  };
  "/api/v1/auth/login": {
    post: "login_api_v1_auth_login_post";
  };
  "/api/v1/auth/me": {
    get: "me_api_v1_auth_me_get";
  };
  "/api/v1/auth/refresh": {
    post: "refresh_api_v1_auth_refresh_post";
  };
  "/api/v1/auth/register": {
    post: "register_api_v1_auth_register_post";
  };
  "/api/v1/brand-dna": {
    get: "get_brand_dna_api_v1_brand_dna_get";
  };
  "/api/v1/brand-dna/activate": {
    post: "set_brand_dna_active_api_v1_brand_dna_activate_post";
  };
  "/api/v1/brand-dna/refresh": {
    post: "refresh_brand_dna_api_v1_brand_dna_refresh_post";
  };
  "/api/v1/brand-loras": {
    get: "list_brand_loras_api_v1_brand_loras_get";
    post: "create_brand_lora_api_v1_brand_loras_post";
  };
  "/api/v1/brand-loras/{profile_id}": {
    delete: "archive_brand_lora_api_v1_brand_loras__profile_id__delete";
    get: "get_brand_lora_api_v1_brand_loras__profile_id__get";
  };
  "/api/v1/brand-loras/{profile_id}/activate": {
    post: "activate_brand_lora_api_v1_brand_loras__profile_id__activate_post";
  };
  "/api/v1/brand-loras/{profile_id}/deactivate": {
    post: "deactivate_brand_lora_api_v1_brand_loras__profile_id__deactivate_post";
  };
  "/api/v1/bulk-generations": {
    post: "create_bulk_generation_api_v1_bulk_generations_post";
  };
  "/api/v1/bulk-generations/notifications": {
    get: "list_push_notifications_api_v1_bulk_generations_notifications_get";
  };
  "/api/v1/bulk-generations/{batch_id}": {
    get: "get_bulk_generation_api_v1_bulk_generations__batch_id__get";
  };
  "/api/v1/claude-analyses": {
    post: "create_claude_analysis_api_v1_claude_analyses_post";
  };
  "/api/v1/claude-analyses/{analysis_id}": {
    get: "get_claude_analysis_api_v1_claude_analyses__analysis_id__get";
  };
  "/api/v1/claude/reasoning/analyze": {
    post: "enqueue_competitor_analysis_api_v1_claude_reasoning_analyze_post";
  };
  "/api/v1/claude/reasoning/{task_id}": {
    get: "get_reasoning_job_api_v1_claude_reasoning__task_id__get";
  };
  "/api/v1/claude/visual-audit/analyze": {
    post: "enqueue_visual_audit_api_v1_claude_visual_audit_analyze_post";
  };
  "/api/v1/claude/visual-audit/preview-filter": {
    post: "preview_visual_audit_filter_api_v1_claude_visual_audit_preview_filter_post";
  };
  "/api/v1/claude/visual-audit/{task_id}": {
    get: "get_visual_audit_job_api_v1_claude_visual_audit__task_id__get";
  };
  "/api/v1/designs": {
    get: "list_designs_api_v1_designs_get";
    post: "save_design_api_v1_designs_post";
  };
  "/api/v1/designs/{design_id}/render": {
    post: "render_design_api_v1_designs__design_id__render_post";
  };
  "/api/v1/exports/credentials": {
    get: "list_export_credentials_api_v1_exports_credentials_get";
  };
  "/api/v1/exports/credentials/{platform}": {
    delete: "delete_export_credentials_api_v1_exports_credentials__platform__delete";
    put: "save_export_credentials_api_v1_exports_credentials__platform__put";
  };
  "/api/v1/exports/requirements/{platform}": {
    get: "get_export_requirements_api_v1_exports_requirements__platform__get";
  };
  "/api/v1/exports/validate": {
    post: "validate_export_card_api_v1_exports_validate_post";
  };
  "/api/v1/exports/{platform}": {
    post: "export_generation_to_draft_api_v1_exports__platform__post";
  };
  "/api/v1/fonts": {
    get: "list_fonts_api_v1_fonts_get";
  };
  "/api/v1/fonts/upload": {
    post: "upload_font_api_v1_fonts_upload_post";
  };
  "/api/v1/generation-texts/{task_id}": {
    get: "get_generation_marketplace_text_api_v1_generation_texts__task_id__get";
  };
  "/api/v1/generations": {
    post: "create_generation_api_v1_generations_post";
  };
  "/api/v1/generations/history": {
    get: "list_generation_history_api_v1_generations_history_get";
  };
  "/api/v1/generations/model": {
    post: "create_model_generation_api_v1_generations_model_post";
  };
  "/api/v1/generations/{task_id}": {
    get: "get_generation_status_api_v1_generations__task_id__get";
  };
  "/api/v1/images/upload": {
    post: "upload_image_api_v1_images_upload_post";
  };
  "/api/v1/legal/privacy": {
    get: "read_privacy_policy_api_v1_legal_privacy_get";
  };
  "/api/v1/legal/terms": {
    get: "read_terms_of_service_api_v1_legal_terms_get";
  };
  "/api/v1/marketplace-bridge/dashboard": {
    get: "get_marketplace_dashboard_api_v1_marketplace_bridge_dashboard_get";
  };
  "/api/v1/marketplace-bridge/platforms/{platform}": {
    get: "get_platform_bridge_metrics_api_v1_marketplace_bridge_platforms__platform__get";
  };
  "/api/v1/oracle/notifications": {
    get: "list_oracle_notifications_api_v1_oracle_notifications_get";
  };
  "/api/v1/oracle/predict": {
    post: "enqueue_oracle_prediction_api_v1_oracle_predict_post";
  };
  "/api/v1/oracle/preview": {
    post: "preview_oracle_scan_api_v1_oracle_preview_post";
  };
  "/api/v1/oracle/{task_id}": {
    get: "get_oracle_job_api_v1_oracle__task_id__get";
  };
  "/api/v1/pain-analysis/analyze": {
    post: "enqueue_pain_analysis_api_v1_pain_analysis_analyze_post";
  };
  "/api/v1/pain-analysis/preview": {
    post: "preview_pain_analysis_api_v1_pain_analysis_preview_post";
  };
  "/api/v1/pain-analysis/{job_id}": {
    get: "get_pain_analysis_job_api_v1_pain_analysis__job_id__get";
  };
  "/api/v1/payments/balance": {
    get: "get_balance_api_v1_payments_balance_get";
  };
  "/api/v1/payments/create": {
    post: "create_payment_api_v1_payments_create_post";
  };
  "/api/v1/payments/daily-bonus/claim": {
    post: "claim_daily_bonus_api_v1_payments_daily_bonus_claim_post";
  };
  "/api/v1/payments/tariffs": {
    get: "list_tariffs_api_v1_payments_tariffs_get";
  };
  "/api/v1/payments/webhook": {
    post: "yookassa_webhook_api_v1_payments_webhook_post";
  };
  "/api/v1/referrals/apply": {
    post: "apply_referral_code_api_v1_referrals_apply_post";
  };
  "/api/v1/referrals/stats": {
    get: "get_referral_stats_api_v1_referrals_stats_get";
  };
  "/api/v1/smart-variants": {
    post: "create_smart_variant_sync_api_v1_smart_variants_post";
  };
  "/api/v1/smart-variants/{sync_id}": {
    get: "get_smart_variant_sync_api_v1_smart_variants__sync_id__get";
  };
  "/api/v1/templates": {
    get: "list_templates_api_v1_templates_get";
  };
  "/api/v1/templates/{template_id}": {
    get: "get_template_api_v1_templates__template_id__get";
  };
  "/api/v1/verify-captcha": {
    post: "verify_captcha_api_v1_verify_captcha_post";
  };
  "/api/v1/webhooks/midjourney/{provider_name}": {
    post: "receive_midjourney_webhook_api_v1_webhooks_midjourney__provider_name__post";
  };
  "/api/v1/winback/cancel-intent": {
    post: "register_cancel_intent_api_v1_winback_cancel_intent_post";
  };
  "/api/v1/winback/offer": {
    get: "get_current_offer_api_v1_winback_offer_get";
  };
  "/api/v1/winback/offer/{offer_id}/claim": {
    post: "claim_offer_api_v1_winback_offer__offer_id__claim_post";
  };
  "/api/v1/winback/telegram": {
    post: "link_telegram_api_v1_winback_telegram_post";
  };
  "/api/v1/workspaces": {
    post: "create_or_get_workspace_api_v1_workspaces_post";
  };
  "/api/v1/workspaces/managers": {
    post: "add_workspace_manager_api_v1_workspaces_managers_post";
  };
  "/api/v1/workspaces/managers/{manager_user_id}": {
    delete: "remove_workspace_manager_api_v1_workspaces_managers__manager_user_id__delete";
  };
  "/api/v1/workspaces/me": {
    get: "get_my_workspace_api_v1_workspaces_me_get";
  };
  "/api/v1/workspaces/shares": {
    get: "list_shared_generations_api_v1_workspaces_shares_get";
    post: "share_generation_with_team_api_v1_workspaces_shares_post";
  };
  "/api/v1/workspaces/shares/{share_id}": {
    delete: "unshare_generation_api_v1_workspaces_shares__share_id__delete";
  };
  "/health": {
    get: "health_health_get";
  };
  "/health/live": {
    get: "liveness_health_live_get";
  };
  "/health/ready": {
    get: "readiness_health_ready_get";
  };
  "/healthz": {
    get: "healthz_healthz_get";
  };
  "/healthz/deep": {
    get: "healthz_deep_healthz_deep_get";
  };
  "/readyz": {
    get: "readyz_readyz_get";
  };
}
