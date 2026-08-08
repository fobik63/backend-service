import { create } from "zustand";

/** Marketplace choice collected on onboarding step 1. */
export type OnboardingMarketplace = "ozon" | "wildberries" | "both";

/** Product category choice collected on onboarding step 2. */
export type OnboardingCategory =
  | "footwear_clothing"
  | "electronics"
  | "cosmetics"
  | "home_garden"
  | "auto"
  | "kids";

type OnboardingState = {
  marketplace: OnboardingMarketplace | null;
  categories: OnboardingCategory[];
  setMarketplace: (marketplace: OnboardingMarketplace) => void;
  toggleCategory: (category: OnboardingCategory) => void;
  setCategories: (categories: OnboardingCategory[]) => void;
  resetOnboarding: () => void;
};

export const useOnboardingStore = create<OnboardingState>((set) => ({
  marketplace: null,
  categories: [],
  setMarketplace: (marketplace) => set({ marketplace }),
  toggleCategory: (category) =>
    set((state) => ({
      categories: state.categories.includes(category)
        ? state.categories.filter((c) => c !== category)
        : [...state.categories, category],
    })),
  setCategories: (categories) => set({ categories }),
  resetOnboarding: () => set({ marketplace: null, categories: [] }),
}));
