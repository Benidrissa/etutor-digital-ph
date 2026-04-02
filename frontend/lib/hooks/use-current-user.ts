'use client';

import { useState, useEffect } from 'react';
import type { User } from '@/lib/auth';

export function useCurrentUser(): User | null {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    const load = () => {
      try {
        const raw = localStorage.getItem('user');
        setUser(raw ? (JSON.parse(raw) as User) : null);
      } catch {
        setUser(null);
      }
    };

    load();

    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'user') load();
    };

    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  return user;
}
