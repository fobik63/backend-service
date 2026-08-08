export type SubscriptionStatus = "free" | "pro" | "enterprise";

export type User = {
  id: string;
  email: string;
  displayName: string | null;
  avatarUrl: string | null;
  subscriptionStatus: SubscriptionStatus;
  createdAt: string;
};
