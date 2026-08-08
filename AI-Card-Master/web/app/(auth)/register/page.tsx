"use client"

import { AuthForm } from "@/components/auth/auth-form"

export default function RegisterPage() {
  return <AuthForm initialMode="register" hideHomeLink />
}
