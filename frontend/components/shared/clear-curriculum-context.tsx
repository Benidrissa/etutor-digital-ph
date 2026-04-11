'use client';

import { useEffect } from 'react';
import { clearCurriculumContext } from '@/lib/curriculum-context';

export function ClearCurriculumContext() {
  useEffect(() => {
    clearCurriculumContext();
  }, []);
  return null;
}
