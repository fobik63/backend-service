import type { Metadata } from "next"

import { LegalPageShell } from "@/components/legal/legal-page-shell"

export const metadata: Metadata = {
  title: "Публичная оферта — CARD AI",
  description: "Условия использования сервиса CARD AI",
}

export default function TermsPage() {
  return (
    <LegalPageShell title="Публичная оферта" updatedAt="8 августа 2026 г.">
      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          1. Общие положения
        </h2>
        <p>
          Настоящий документ является официальным предложением (публичной
          офертой) сервиса CARD AI заключить договор на использование
          платформы для создания карточек товаров маркетплейсов. Акцептом
          оферты считается регистрация в сервисе и/или начало использования
          функционала.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          2. Предмет договора
        </h2>
        <p>
          Исполнитель предоставляет Пользователю доступ к веб-приложению CARD
          AI: загрузка изображений, AI-обработка, редактирование и экспорт
          карточек. Состав функций может зависеть от выбранного тарифа и
          баланса монет.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          3. Права и обязанности сторон
        </h2>
        <p>
          Пользователь обязуется предоставлять достоверные данные, не нарушать
          права третьих лиц на изображения и контент, а также соблюдать
          правила маркетплейсов. Исполнитель обеспечивает работоспособность
          сервиса в разумных пределах и вправе обновлять функционал без
          предварительного уведомления, если это не ухудшает существенные
          условия оплаченного периода.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          4. Оплата и возвраты
        </h2>
        <p>
          Платные услуги оказываются после успешной оплаты. Монеты и пакеты
          списываются согласно тарифам, указанным в интерфейсе. Возврат
          неиспользованного остатка рассматривается индивидуально при обращении
          в поддержку, если иное не предусмотрено законодательством.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          5. Ограничение ответственности
        </h2>
        <p>
          Сервис предоставляется «как есть». Исполнитель не гарантирует
          конкретные показатели продаж на маркетплейсах и не несёт
          ответственности за решения модерации Ozon, Wildberries и иных
          площадок. Пользователь самостоятельно проверяет соответствие
          карточек требованиям площадки.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          6. Контакты
        </h2>
        <p>
          По вопросам оферты:{" "}
          <a
            href="mailto:support@cardai.pro"
            className="text-emerald underline-offset-4 hover:underline"
          >
            support@cardai.pro
          </a>
          {" · "}
          Telegram{" "}
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
