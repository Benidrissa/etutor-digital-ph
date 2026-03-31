import { TOTPRegisterForm } from '@/components/auth/totp-register-form';

export default function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <TOTPRegisterForm />
    </div>
  );
}
