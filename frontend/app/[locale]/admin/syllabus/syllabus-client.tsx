'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Loader2, AlertCircle, ChevronDown, ChevronRight, BookOpen } from 'lucide-react';
import { AdminModuleCard, NewModuleCard, type AdminModuleCardData } from '@/components/admin/module-card';
import { SyllabusEditor } from '@/components/admin/syllabus-editor';
import { authClient, AuthError } from '@/lib/auth';
import { API_BASE } from '@/lib/api';

interface CourseGroup {
  course_id: string | null;
  course_title: string;
  course_slug: string | null;
  modules: AdminModuleCardData[];
}

export function SyllabusPageClient() {
  const t = useTranslations('AdminSyllabus');
  const locale = useLocale() as 'fr' | 'en';
  const router = useRouter();

  const [modules, setModules] = useState<AdminModuleCardData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingModule, setEditingModule] = useState<AdminModuleCardData | null>(null);
  const [collapsedCourses, setCollapsedCourses] = useState<Set<string>>(new Set());

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

  const courseGroups: CourseGroup[] = useMemo(() => {
    const grouped = new Map<string, CourseGroup>();

    for (const mod of modules) {
      const key = mod.course_id ?? '__unlinked__';
      if (!grouped.has(key)) {
        const title = mod.course_id
          ? (locale === 'fr' ? mod.course_title_fr : mod.course_title_en) || mod.course_title_fr || t('untitledCourse')
          : t('unlinkedModules');
        grouped.set(key, {
          course_id: mod.course_id ?? null,
          course_title: title,
          course_slug: mod.course_slug ?? null,
          modules: [],
        });
      }
      grouped.get(key)!.modules.push(mod);
    }

    // Sort: courses with modules first, unlinked last
    const entries = Array.from(grouped.values());
    return entries.sort((a, b) => {
      if (!a.course_id) return 1;
      if (!b.course_id) return -1;
      return a.course_title.localeCompare(b.course_title);
    });
  }, [modules, locale, t]);

  const toggleCourse = (key: string) => {
    setCollapsedCourses((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

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

  return (
    <>
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
        {courseGroups.map((group) => {
          const key = group.course_id ?? '__unlinked__';
          const isCollapsed = collapsedCourses.has(key);
          const totalHours = group.modules.reduce((sum, m) => sum + m.estimated_hours, 0);
          const totalUnits = group.modules.reduce((sum, m) => sum + m.unit_count, 0);

          return (
            <section key={key} className="border rounded-lg bg-card">
              <button
                type="button"
                onClick={() => toggleCourse(key)}
                className="w-full flex items-center gap-3 p-4 hover:bg-muted/50 transition-colors text-left"
              >
                {isCollapsed ? (
                  <ChevronRight className="h-5 w-5 text-muted-foreground shrink-0" />
                ) : (
                  <ChevronDown className="h-5 w-5 text-muted-foreground shrink-0" />
                )}
                <BookOpen className="h-5 w-5 text-primary shrink-0" />
                <div className="flex-1 min-w-0">
                  <h2 className="text-base font-semibold truncate">
                    {group.course_title}
                  </h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {group.modules.length} {t('modules')} &middot; {totalUnits} {t('units')} &middot; {totalHours}h
                  </p>
                </div>
              </button>

              {!isCollapsed && (
                <div className="px-4 pb-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                    {group.modules.map((mod) => (
                      <AdminModuleCard key={mod.id} module={mod} onEdit={handleEdit} />
                    ))}
                  </div>
                </div>
              )}
            </section>
          );
        })}

        {courseGroups.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <BookOpen className="h-12 w-12 text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">{t('noModules')}</p>
          </div>
        )}

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
