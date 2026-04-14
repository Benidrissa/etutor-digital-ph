'use client';

import { TOTPRegisterForm } from '@/components/auth/totp-register-form';
import { useRegistrationGuard } from '@/hooks/use-registration-guard';

export default function RegisterTOTPPage() {
  const blocked = useRegistrationGuard();

  if (blocked) return null;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <TOTPRegisterForm />
    </div>
  );
}
