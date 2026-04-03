'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Loader2, AlertCircle } from 'lucide-react';
import { AdminModuleCard, NewModuleCard, type AdminModuleCardData } from '@/components/admin/module-card';
import { SyllabusEditor } from '@/components/admin/syllabus-editor';
import { authClient, AuthError } from '@/lib/auth';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const LEVEL_GROUPS: Record<number, { titleFr: string; titleEn: string }> = {
  1: { titleFr: 'Niveau 1 — Fondements (60h)', titleEn: 'Level 1 — Foundations (60h)' },
  2: { titleFr: 'Niveau 2 — Intermédiaire (90h)', titleEn: 'Level 2 — Intermediate (90h)' },
  3: { titleFr: 'Niveau 3 — Avancé (100h)', titleEn: 'Level 3 — Advanced (100h)' },
  4: { titleFr: 'Niveau 4 — Expert (70h)', titleEn: 'Level 4 — Expert (70h)' },
};

export function SyllabusPageClient() {
  const t = useTranslations('AdminSyllabus');
  const router = useRouter();

  const [modules, setModules] = useState<AdminModuleCardData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingModule, setEditingModule] = useState<AdminModuleCardData | null>(null);

  const fetchModules = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      let token: string;
      try {
        token = await authClient.getValidToken();
      } catch (err) {
        if (err instanceof AuthError && err.status === 401) {
          router.push('/login');
          return;
        }
        throw err;
      }

      const res = await fetch(`${API_BASE}/api/v1/admin/syllabus`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.status === 403) {
        setError(t('errorForbidden'));
        return;
      }
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      setModules(data.modules ?? []);
    } catch {
      setError(t('errorLoading'));
    } finally {
      setIsLoading(false);
    }
  }, [router, t]);

  useEffect(() => {
    fetchModules();
  }, [fetchModules]);

  const handleEdit = (module: AdminModuleCardData) => {
    setEditingModule(module);
    setEditorOpen(true);
  };

  const handleCreate = () => {
    setEditingModule(null);
    setEditorOpen(true);
  };

  const handleEditorClose = () => {
    setEditorOpen(false);
    setEditingModule(null);
  };

  const handleSaved = () => {
    setEditorOpen(false);
    setEditingModule(null);
    fetchModules();
  };

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
        <AlertCircle className="h-10 w-10 text-destructive" />
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button variant="outline" onClick={fetchModules}>
          {t('retry')}
        </Button>
      </div>
    );
  }

  const grouped: Record<number, AdminModuleCardData[]> = { 1: [], 2: [], 3: [], 4: [] };
  for (const mod of modules) {
    const lvl = mod.level as 1 | 2 | 3 | 4;
    if (grouped[lvl]) grouped[lvl].push(mod);
  }

  return (
    <>
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-8">
        {([1, 2, 3, 4] as const).map((level) => (
          <section key={level}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold">
                {t('level')} {level}
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  ({grouped[level].length} {t('modules')})
                </span>
              </h2>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {grouped[level].map((mod) => (
                <AdminModuleCard key={mod.id} module={mod} onEdit={handleEdit} />
              ))}
              {level === 4 && <NewModuleCard onCreate={handleCreate} />}
            </div>
          </section>
        ))}

        <div className="flex justify-center pt-4 pb-8">
          <Button onClick={handleCreate} size="lg" className="gap-2">
            {t('createModule')}
          </Button>
        </div>
      </div>

      {editorOpen && (
        <SyllabusEditor
          editingModule={editingModule}
          onClose={handleEditorClose}
          onSaved={handleSaved}
        />
      )}
    </>
  );
}
