"use client"

import { KeyRound, Shield, UserRound } from "lucide-react"

import { IntegrationsTab } from "@/components/dashboard/settings/integrations-tab"
import { PersonalDataTab } from "@/components/dashboard/settings/personal-data-tab"
import { SecurityTab } from "@/components/dashboard/settings/security-tab"
import { GlassCard } from "@/components/ui/glass-card"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"

function ProfileSettings() {
  return (
    <section className="mx-auto w-full max-w-3xl space-y-6">
      <header className="space-y-1.5">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">
          Настройки профиля
        </h1>
        <p className="text-sm text-muted-foreground">
          Личные данные, интеграции с маркетплейсами и безопасность аккаунта
        </p>
      </header>

      <Tabs defaultValue="personal" className="gap-4">
        <TabsList
          variant="line"
          className="h-auto w-full flex-wrap justify-start gap-0 border-b border-white/10 pb-0"
        >
          <TabsTrigger
            value="personal"
            className="gap-1.5 px-3 py-2.5 data-active:text-foreground"
          >
            <UserRound className="size-4" aria-hidden />
            Личные данные
          </TabsTrigger>
          <TabsTrigger
            value="integrations"
            className="gap-1.5 px-3 py-2.5 data-active:text-foreground"
          >
            <KeyRound className="size-4" aria-hidden />
            Магазины и Интеграции
          </TabsTrigger>
          <TabsTrigger
            value="security"
            className="gap-1.5 px-3 py-2.5 data-active:text-foreground"
          >
            <Shield className="size-4" aria-hidden />
            Безопасность
          </TabsTrigger>
        </TabsList>

        <GlassCard hoverLift={false} padding="lg" className="border-white/10">
          <TabsContent value="personal" className="mt-0 outline-none">
            <PersonalDataTab />
          </TabsContent>
          <TabsContent value="integrations" className="mt-0 outline-none">
            <IntegrationsTab />
          </TabsContent>
          <TabsContent value="security" className="mt-0 outline-none">
            <SecurityTab />
          </TabsContent>
        </GlassCard>
      </Tabs>
    </section>
  )
}

export { ProfileSettings }
