"use client"

import { AuthForm } from "@/components/auth/auth-form"

export default function OtpPage() {
  return <AuthForm initialMode="otp" otpFirst hideHomeLink />
}
