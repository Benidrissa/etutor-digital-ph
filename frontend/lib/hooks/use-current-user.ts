'use client';

import { useState, useEffect } from 'react';
import type { User } from '@/lib/auth';

export interface CurrentUserState {
  user: User | null;
  isHydrated: boolean;
}

export function useCurrentUser(): CurrentUserState {
  const [state, setState] = useState<CurrentUserState>({ user: null, isHydrated: false });

  useEffect(() => {
    const load = () => {
      try {
        const raw = localStorage.getItem('user');
        setState({ user: raw ? (JSON.parse(raw) as User) : null, isHydrated: true });
      } catch {
        setState({ user: null, isHydrated: true });
      }
    };

    load();

    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'user') load();
    };

    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  return state;
}
