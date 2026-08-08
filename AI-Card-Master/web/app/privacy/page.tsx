import type { Metadata } from "next"

import { LegalPageShell } from "@/components/legal/legal-page-shell"

export const metadata: Metadata = {
  title: "Политика конфиденциальности — CARD AI",
  description: "Как CARD AI обрабатывает персональные данные",
}

export default function PrivacyPage() {
  return (
    <LegalPageShell
      title="Политика конфиденциальности"
      updatedAt="8 августа 2026 г."
    >
      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          1. Какие данные мы собираем
        </h2>
        <p>
          При регистрации и использовании CARD AI могут обрабатываться email,
          данные профиля (в т.ч. из Telegram Login), технические логи,
          загруженные изображения и метаданные проектов, необходимые для
          работы сервиса и поддержки.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          2. Цели обработки
        </h2>
        <p>
          Данные используются для предоставления доступа к платформе,
          аутентификации, биллинга, улучшения качества AI-обработки,
          предотвращения злоупотреблений и связи с пользователем по запросам
          поддержки.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          3. Хранение и передача
        </h2>
        <p>
          Данные хранятся на защищённых серверах в объёме, необходимом для
          оказания услуг. Передача третьим лицам возможна только при наличии
          законного основания: платёжным провайдерам, инфраструктурным
          подрядчикам или по требованию уполномоченных органов.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          4. Cookies и локальное хранилище
        </h2>
        <p>
          Сервис может использовать cookies и localStorage для сессии,
          предпочтений интерфейса и аналитики работоспособности. Вы можете
          ограничить cookies в настройках браузера — часть функций при этом
          станет недоступна.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          5. Права пользователя
        </h2>
        <p>
          Вы можете запросить уточнение, экспорт или удаление персональных
          данных, связанных с аккаунтом, направив обращение в поддержку. Мы
          ответим в разумный срок, если иное не требуется по закону.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          6. Контакты по персональным данным
        </h2>
        <p>
          Email:{" "}
          <a
            href="mailto:support@cardai.pro"
            className="text-emerald underline-offset-4 hover:underline"
          >
            support@cardai.pro
          </a>
          . Telegram:{" "}
          <a
            href="https://t.me/cardai_support"
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald underline-offset-4 hover:underline"
          >
            @cardai_support
          </a>
          .
        </p>
      </section>
    </LegalPageShell>
  )
}
