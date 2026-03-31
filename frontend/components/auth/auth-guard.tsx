/**
 * AuthGuard component to protect routes and redirect unauthenticated users
 * Shows loading state while checking authentication
 */

'use client';

import { useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { useAuth } from '@/lib/hooks/use-auth';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

interface AuthGuardProps {
  children: React.ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Don't redirect if still loading
    if (isLoading) return;

    // If not authenticated, redirect to login with return URL
    if (!isAuthenticated) {
      const locale = pathname.split('/')[1] || 'en';
      const returnUrl = encodeURIComponent(pathname);
      router.push(`/${locale}/login?returnUrl=${returnUrl}`);
      return;
    }
  }, [isAuthenticated, isLoading, pathname, router]);

  // Show loading spinner while checking auth
  if (isLoading) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <LoadingSpinner size="lg" />
          <p className="text-sm text-muted-foreground">
            Checking authentication...
          </p>
        </div>
      </div>
    );
  }

  // Show nothing while redirecting unauthenticated users
  if (!isAuthenticated) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <LoadingSpinner size="lg" />
          <p className="text-sm text-muted-foreground">
            Redirecting to login...
          </p>
        </div>
      </div>
    );
  }

  // Render children if authenticated
  return <>{children}</>;
}