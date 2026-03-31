/**
 * Authentication hook that provides auth operations and state
 * Integrates with Zustand auth store and auth client
 */

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '../store';
import { authClient } from '../auth';

export function useAuth() {
  const {
    user,
    isAuthenticated,
    isLoading,
    login,
    logout,
    initialize,
    setUser,
    setLoading,
  } = useAuthStore();

  const router = useRouter();

  // Initialize auth state on first mount
  useEffect(() => {
    initialize();
  }, [initialize]);

  const requireAuth = () => {
    if (!isAuthenticated && !isLoading) {
      const currentPath = window.location.pathname;
      const locale = currentPath.split('/')[1] || 'en';
      
      // Construct return URL
      const returnUrl = encodeURIComponent(currentPath);
      router.push(`/${locale}/login?returnUrl=${returnUrl}`);
      return false;
    }
    return true;
  };

  const handleLogin = async (email: string, totpCode: string) => {
    try {
      await login(email, totpCode);
      return true;
    } catch (error) {
      throw error;
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
      const currentPath = window.location.pathname;
      const locale = currentPath.split('/')[1] || 'en';
      router.push(`/${locale}/login`);
    } catch (error) {
      // Still redirect on logout error
      const currentPath = window.location.pathname;
      const locale = currentPath.split('/')[1] || 'en';
      router.push(`/${locale}/login`);
      throw error;
    }
  };

  return {
    user,
    isAuthenticated,
    isLoading,
    login: handleLogin,
    logout: handleLogout,
    requireAuth,
    setUser,
    setLoading,
    authClient, // Expose auth client for advanced usage
  };
}