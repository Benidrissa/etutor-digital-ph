/**
 * Zustand store for authentication state management
 * Integrates with the existing AuthClient for TOTP MFA authentication
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { authClient, type User } from './auth';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  
  // Actions
  login: (email: string, totpCode: string) => Promise<void>;
  logout: () => Promise<void>;
  initialize: () => void;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticated: false,
      isLoading: true,

      login: async (email: string, totpCode: string) => {
        set({ isLoading: true });
        try {
          const response = await authClient.login({ email, totp_code: totpCode });
          set({
            user: response.user,
            isAuthenticated: true,
            isLoading: false,
          });
        } catch (error) {
          set({ isLoading: false });
          throw error;
        }
      },

      logout: async () => {
        set({ isLoading: true });
        try {
          await authClient.logout();
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
          });
        } catch (error) {
          // Still clear state on logout error
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
          });
          throw error;
        }
      },

      initialize: () => {
        set({ isLoading: true });
        
        // Check if user is authenticated via existing auth client
        const isAuth = authClient.isAuthenticated();
        const currentUser = authClient.getCurrentUser();
        
        set({
          user: currentUser,
          isAuthenticated: isAuth,
          isLoading: false,
        });
      },

      setUser: (user: User | null) => {
        set({
          user,
          isAuthenticated: !!user,
        });
      },

      setLoading: (loading: boolean) => {
        set({ isLoading: loading });
      },
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      // Only persist user data, not loading state
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);