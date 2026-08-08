/**
 * Landing testimonials — mock source until wired to the API/DB.
 * Shape mirrors a future `GET /testimonials` payload for drop-in replacement.
 */
export type TestimonialMarketplace = "ozon" | "wildberries"

export type Testimonial = {
  id: string
  name: string
  niche: string
  marketplace: TestimonialMarketplace
  /** Integer 1–5 */
  rating: number
  text: string
  /** Optional CDN/DB avatar; falls back to initials when empty */
  avatarUrl?: string | null
  avatarInitials: string
}

export const TESTIMONIALS: Testimonial[] = [
  {
    id: "t1",
    name: "Анна Ковалёва",
    niche: "Продавец обуви на Ozon",
    marketplace: "ozon",
    rating: 5,
    text: "Вырезка без ореолов и свет как в студии — карточки стали заметнее в выдаче уже за первую неделю.",
    avatarUrl: null,
    avatarInitials: "АК",
  },
  {
    id: "t2",
    name: "Дмитрий Орлов",
    niche: "Дом и сад на Wildberries",
    marketplace: "wildberries",
    rating: 5,
    text: "Раньше инфографику собирали вручную часами. Теперь плашки и скидки выходят аккуратно за минуты.",
    avatarUrl: null,
    avatarInitials: "ДО",
  },
  {
    id: "t3",
    name: "Елена Смирнова",
    niche: "Косметика на Ozon",
    marketplace: "ozon",
    rating: 5,
    text: "360° обзор добавили к хитам — покупатели реже возвращают, а CTR по карточке вырос заметно.",
    avatarUrl: null,
    avatarInitials: "ЕС",
  },
  {
    id: "t4",
    name: "Игорь Петров",
    niche: "Электроника на Wildberries",
    marketplace: "wildberries",
    rating: 5,
    text: "Виртуальный софтбокс спас серию с плохими исходниками. Свет ровный, тени мягкие, бренд выглядит дорого.",
    avatarUrl: null,
    avatarInitials: "ИП",
  },
  {
    id: "t5",
    name: "Мария Белова",
    niche: "Детские товары на Ozon",
    marketplace: "ozon",
    rating: 5,
    text: "Загрузила фото с телефона — получила чистые карточки под требования маркетплейса без ретушёра.",
    avatarUrl: null,
    avatarInitials: "МБ",
  },
  {
    id: "t6",
    name: "Сергей Николаев",
    niche: "Спортивное питание на Wildberries",
    marketplace: "wildberries",
    rating: 5,
    text: "Единый стиль на все SKU. Команда наконец перестала спорить о шрифтах и отступах на плашках.",
    avatarUrl: null,
    avatarInitials: "СН",
  },
  {
    id: "t7",
    name: "Ольга Васильева",
    niche: "Текстиль для дома на Ozon",
    marketplace: "ozon",
    rating: 5,
    text: "AI-вырезка держит сложные ткани и складки. Раньше такие кадры уходили на фриланс за отдельные деньги.",
    avatarUrl: null,
    avatarInitials: "ОВ",
  },
  {
    id: "t8",
    name: "Артём Кузнецов",
    niche: "Автоаксессуары на Wildberries",
    marketplace: "wildberries",
    rating: 5,
    text: "Собрали витрину за вечер вместо недели. Особенно зашёл быстрый рендер скидок под акции маркетплейса.",
    avatarUrl: null,
    avatarInitials: "АК",
  },
]
