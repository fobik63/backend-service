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

export const otpEmailSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Укажите email")
    .email("Некорректный email"),
})

export const otpCodeSchema = z.object({
  code: z
    .string()
    .trim()
    .min(1, "Укажите код")
    .regex(/^\d{6}$/, "Код — 6 цифр"),
})

/** Combined schema kept for verify payload typing. */
export const otpAuthSchema = otpEmailSchema.merge(otpCodeSchema)

export type AuthCredentialsValues = z.infer<typeof authCredentialsSchema>
export type OtpEmailValues = z.infer<typeof otpEmailSchema>
export type OtpCodeValues = z.infer<typeof otpCodeSchema>
export type OtpAuthValues = z.infer<typeof otpAuthSchema>
export type AuthMode = "login" | "register" | "otp"
