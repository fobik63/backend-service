export type AnalyticsMetricKey =
  | "generations"
  | "exports"
  | "active_users"
  | "conversion_rate";

export type AnalyticsPoint = {
  date: string;
  value: number;
};

export type AnalyticsSeries = {
  key: AnalyticsMetricKey;
  label: string;
  points: AnalyticsPoint[];
};
