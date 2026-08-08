import type { ReactNode } from "react";

type DashboardLayoutProps = {
  children: ReactNode;
};

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border px-6 py-4">
        <h1 className="font-heading text-lg font-semibold tracking-tight">
          AI Card Master
        </h1>
      </header>
      <main className="px-6 py-8">{children}</main>
    </div>
  );
}
