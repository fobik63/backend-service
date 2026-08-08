import { z } from "zod"

export const personalDataSchema = z.object({
  displayName: z
    .string()
    .trim()
    .min(1, "Укажите имя")
    .max(80, "Имя слишком длинное"),
  email: z
    .string()
    .trim()
    .min(1, "Укажите email")
    .email("Некорректный email"),
  telegram: z
    .string()
    .trim()
    .max(64, "Слишком длинный username")
    .refine(
      (value) => value === "" || /^@?[a-zA-Z0-9_]{5,32}$/.test(value),
      "Некорректный Telegram username"
    ),
})

export const integrationsSchema = z.object({
  ozonApiKey: z.string().trim().max(512, "Ключ слишком длинный"),
  ozonClientId: z.string().trim().max(128, "Client ID слишком длинный"),
  wildberriesApiKey: z.string().trim().max(512, "Ключ слишком длинный"),
})

export const changePasswordSchema = z
  .object({
    currentPassword: z
      .string()
      .min(1, "Укажите текущий пароль")
      .min(8, "Пароль не менее 8 символов"),
    newPassword: z
      .string()
      .min(1, "Укажите новый пароль")
      .min(8, "Пароль не менее 8 символов")
      .max(128, "Пароль слишком длинный"),
    confirmPassword: z.string().min(1, "Подтвердите пароль"),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: "Пароли не совпадают",
    path: ["confirmPassword"],
  })
  .refine((data) => data.currentPassword !== data.newPassword, {
    message: "Новый пароль должен отличаться от текущего",
    path: ["newPassword"],
  })

export type PersonalDataValues = z.infer<typeof personalDataSchema>
export type IntegrationsValues = z.infer<typeof integrationsSchema>
export type ChangePasswordValues = z.infer<typeof changePasswordSchema>
