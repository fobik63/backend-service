import { z } from "zod"

export const authCredentialsSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Укажите email")
    .email("Некорректный email"),
  password: z
    .string()
    .min(1, "Укажите пароль")
    .min(8, "Пароль не менее 8 символов")
    .max(128, "Пароль слишком длинный"),
})

export const otpAuthSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Укажите email")
    .email("Некорректный email"),
  code: z
    .string()
    .trim()
    .min(1, "Укажите код")
    .regex(/^\d{4,8}$/, "Код — 4–8 цифр"),
})

export type AuthCredentialsValues = z.infer<typeof authCredentialsSchema>
export type OtpAuthValues = z.infer<typeof otpAuthSchema>
export type AuthMode = "login" | "register" | "otp"
