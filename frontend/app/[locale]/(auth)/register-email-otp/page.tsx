'use client';

import { EmailOTPRegisterForm } from '@/components/auth/email-otp-register-form';
import { useRegistrationGuard } from '@/hooks/use-registration-guard';

export default function RegisterEmailOTPPage() {
  const blocked = useRegistrationGuard();

  if (blocked) return null;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <EmailOTPRegisterForm />
    </div>
  );
}
