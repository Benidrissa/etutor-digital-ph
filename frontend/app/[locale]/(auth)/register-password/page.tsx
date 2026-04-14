'use client';

import { PasswordRegisterForm } from '@/components/auth/password-register-form';
import { useRegistrationGuard } from '@/hooks/use-registration-guard';

export default function RegisterPasswordPage() {
  const blocked = useRegistrationGuard();

  if (blocked) return null;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <PasswordRegisterForm />
    </div>
  );
}
