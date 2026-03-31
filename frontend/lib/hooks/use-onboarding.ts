'use client';

import { useState } from 'react';
import { apiFetch } from '@/lib/api';

interface OnboardingData {
  preferred_language: string;
  country: string;
  professional_role: string;
  current_level: number;
}

interface UserProfile {
  id: string;
  email: string;
  name: string;
  preferred_language: string;
  country: string | null;
  professional_role: string | null;
  current_level: number;
  streak_days: number;
  last_active: string;
  created_at: string;
}

export function useOnboarding() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const completeOnboarding = async (data: OnboardingData): Promise<UserProfile> => {
    setIsLoading(true);
    setError(null);

    try {
      const userProfile = await apiFetch<UserProfile>('/api/v1/users/me/onboarding', {
        method: 'POST',
        body: JSON.stringify(data),
      });
      return userProfile;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred';
      setError(errorMessage);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  return {
    completeOnboarding,
    isLoading,
    error,
  };
}