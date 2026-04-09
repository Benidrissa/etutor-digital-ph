'use client';

import { useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, Globe, Archive, BookOpen, Loader2, Check, X, Lock, Unlock, Users, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import {
  getAdminCurricula,
  getAdminCurriculum,
  createAdminCurriculum,
  updateAdminCurriculum,
  publishAdminCurriculum,
  archiveAdminCurriculum,
  deleteAdminCurriculum,
  assignCurriculumCourses,
  setCurriculumVisibility,
  getCurriculumAccess,
  grantCurriculumAccess,
  revokeCurriculumAccess,
  getAdminGroups,
  type CurriculumAdminResponse,
  type CurriculumAdminDetailResponse,
  type CurriculumAccessEntry,
  type UserGroupResponse,
  apiFetch,
} from '@/lib/api';

interface AdminCourseBasic {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  status: string;
}

function StatusBadge({ status }: { status: string }) {
  const t = useTranslations('Admin.curricula.statusBadge');
  const variants: Record<string, string> = {
    draft: 'bg-stone-100 text-stone-700 border-stone-200',
    published: 'bg-teal-50 text-teal-700 border-teal-200',
    archived: 'bg-amber-50 text-amber-700 border-amber-200',
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${variants[status] ?? variants.draft}`}
    >
      {t(status as 'draft' | 'published' | 'archived')}
    </span>
  );
}

function VisibilityBadge({ visibility }: { visibility: 'public' | 'private' }) {
  const t = useTranslations('Admin.curricula');
  if (visibility === 'private') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
        <Lock className="h-3 w-3" />
        {t('visibilityPrivate')}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
      <Globe className="h-3 w-3" />
      {t('visibilityPublic')}
    </span>
  );
}

function AccessManagementPanel({
  curriculumId,
  onClose,
}: {
  curriculumId: string;
  onClose: () => void;
}) {
  const t = useTranslations('Admin.curricula');
  const [emailInput, setEmailInput] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [granting, setGranting] = useState(false);
  const queryClient = useQueryClient();

  const { data: accessList = [], isLoading } = useQuery<CurriculumAccessEntry[]>({
    queryKey: ['admin', 'curricula', curriculumId, 'access'],
    queryFn: () => getCurriculumAccess(curriculumId),
  });

  const { data: groups = [] } = useQuery<UserGroupResponse[]>({
    queryKey: ['admin', 'groups'],
    queryFn: getAdminGroups,
  });

  const invalidateAccess = () =>
    queryClient.invalidateQueries({ queryKey: ['admin', 'curricula', curriculumId, 'access'] });

  const handleGrantUser = async () => {
    if (!emailInput.trim()) return;
    setGranting(true);
    try {
      await grantCurriculumAccess(curriculumId, { user_id: emailInput.trim() });
      setEmailInput('');
      invalidateAccess();
    } finally {
      setGranting(false);
    }
  };

  const handleGrantGroup = async () => {
    if (!selectedGroupId) return;
    setGranting(true);
    try {
      await grantCurriculumAccess(curriculumId, { group_id: selectedGroupId });
      setSelectedGroupId('');
      invalidateAccess();
    } finally {
      setGranting(false);
    }
  };

  const handleRevoke = async (accessId: string) => {
    await revokeCurriculumAccess(curriculumId, accessId);
    invalidateAccess();
  };

  return (
    <Card className="p-4 border-2 border-amber-200 bg-amber-50/30">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-amber-600" />
          <div>
            <p className="text-sm font-medium">{t('accessManagement')}</p>
            <p className="text-xs text-muted-foreground">{t('accessManagementDesc')}</p>
          </div>
        </div>
        <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="space-y-3">
        <div>
          <p className="text-xs font-medium text-stone-700 mb-1.5">{t('grantUserAccess')}</p>
          <div className="flex gap-2">
            <Input
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
              placeholder={t('userEmailPlaceholder')}
              className="h-9 text-sm flex-1"
              onKeyDown={(e) => e.key === 'Enter' && handleGrantUser()}
            />
            <Button size="sm" className="h-9 shrink-0" onClick={handleGrantUser} disabled={granting || !emailInput.trim()}>
              {granting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t('grant')}
            </Button>
          </div>
        </div>

        {groups.length > 0 && (
          <div>
            <p className="text-xs font-medium text-stone-700 mb-1.5">{t('grantGroupAccess')}</p>
            <div className="flex gap-2">
              <Select value={selectedGroupId} onValueChange={setSelectedGroupId}>
                <SelectTrigger className="h-9 text-sm flex-1">
                  <SelectValue placeholder={t('selectGroup')} />
                </SelectTrigger>
                <SelectContent>
                  {groups.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button size="sm" className="h-9 shrink-0" onClick={handleGrantGroup} disabled={granting || !selectedGroupId}>
                {granting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t('grant')}
              </Button>
            </div>
          </div>
        )}

        <div>
          <p className="text-xs font-medium text-stone-700 mb-1.5">{t('currentAccess')}</p>
          {isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-4 w-4 animate-spin text-stone-400" />
            </div>
          ) : accessList.length === 0 ? (
            <p className="text-xs text-muted-foreground py-2">{t('noAccessEntries')}</p>
          ) : (
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {accessList.map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-center justify-between rounded-lg border border-stone-200 bg-white px-3 py-2"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {entry.group_id ? (
                      <Users className="h-3.5 w-3.5 shrink-0 text-blue-500" />
                    ) : (
                      <Globe className="h-3.5 w-3.5 shrink-0 text-stone-400" />
                    )}
                    <span className="text-xs truncate">
                      {entry.group_name ?? entry.user_email ?? entry.user_id ?? entry.group_id}
                    </span>
                    {entry.group_id && (
                      <Badge variant="outline" className="text-[10px] shrink-0">{t('group')}</Badge>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 text-destructive hover:text-destructive shrink-0"
                    onClick={() => handleRevoke(entry.id)}
                    aria-label={t('revoke')}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

interface CurriculumFormData {
  title_fr: string;
  title_en: string;
  description_fr: string;
  description_en: string;
  cover_image_url: string;
}

function CurriculumForm({
  initial,
  onSave,
  onCancel,
  saving,
}: {
  initial?: Partial<CurriculumFormData>;
  onSave: (data: CurriculumFormData) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const t = useTranslations('Admin.curricula');
  const [form, setForm] = useState<CurriculumFormData>({
    title_fr: initial?.title_fr ?? '',
    title_en: initial?.title_en ?? '',
    description_fr: initial?.description_fr ?? '',
    description_en: initial?.description_en ?? '',
    cover_image_url: initial?.cover_image_url ?? '',
  });

  const update = (field: keyof CurriculumFormData, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  return (
    <Card className="p-4 border-2 border-teal-200 bg-teal-50/30">
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="title_fr" className="text-xs">{t('titleFr')}</Label>
            <Input
              id="title_fr"
              value={form.title_fr}
              onChange={(e) => update('title_fr', e.target.value)}
              placeholder="ex. Santé Publique & Numérique"
              className="h-9 text-sm"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="title_en" className="text-xs">{t('titleEn')}</Label>
            <Input
              id="title_en"
              value={form.title_en}
              onChange={(e) => update('title_en', e.target.value)}
              placeholder="e.g. Public Health & Digital"
              className="h-9 text-sm"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="description_fr" className="text-xs">{t('descriptionFr')}</Label>
            <Textarea
              id="description_fr"
              rows={2}
              value={form.description_fr}
              onChange={(e) => update('description_fr', e.target.value)}
              className="text-sm resize-none"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="description_en" className="text-xs">{t('descriptionEn')}</Label>
            <Textarea
              id="description_en"
              rows={2}
              value={form.description_en}
              onChange={(e) => update('description_en', e.target.value)}
              className="text-sm resize-none"
            />
          </div>
        </div>
        <div className="space-y-1">
          <Label htmlFor="cover_image_url" className="text-xs">{t('coverImageUrl')}</Label>
          <Input
            id="cover_image_url"
            type="url"
            value={form.cover_image_url}
            onChange={(e) => update('cover_image_url', e.target.value)}
            placeholder="https://..."
            className="h-9 text-sm"
          />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={onCancel} disabled={saving}>
            {t('cancel')}
          </Button>
          <Button
            size="sm"
            onClick={() => onSave(form)}
            disabled={saving || !form.title_fr || !form.title_en}
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
            {t('save')}
          </Button>
        </div>
      </div>
    </Card>
  );
}

function CourseAssignPanel({
  curriculumId,
  onClose,
  onSave,
  saving,
}: {
  curriculumId: string;
  onClose: () => void;
  onSave: (courseIds: string[]) => void;
  saving: boolean;
}) {
  const t = useTranslations('Admin.curricula');
  const locale = useLocale() as 'fr' | 'en';

  const { data: detail } = useQuery<CurriculumAdminDetailResponse>({
    queryKey: ['admin', 'curricula', curriculumId],
    queryFn: () => getAdminCurriculum(curriculumId),
  });

  const { data: allCourses = [] } = useQuery<AdminCourseBasic[]>({
    queryKey: ['admin', 'courses', 'basic'],
    queryFn: () => apiFetch('/api/v1/admin/courses'),
  });

  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(detail?.courses?.map((c) => c.id) ?? [])
  );

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Card className="p-4 border-2 border-blue-200 bg-blue-50/30">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-sm font-medium">{t('assignCourses')}</p>
          <p className="text-xs text-muted-foreground">{t('assignCoursesDesc')}</p>
        </div>
        <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="max-h-56 overflow-y-auto space-y-1 mb-3">
        {allCourses.map((course) => {
          const title = locale === 'fr' ? course.title_fr : course.title_en;
          const isSelected = selected.has(course.id);
          return (
            <button
              key={course.id}
              type="button"
              onClick={() => toggle(course.id)}
              className={`w-full flex items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm transition-colors min-h-11 ${
                isSelected
                  ? 'bg-teal-50 border-teal-300 text-teal-900'
                  : 'border-stone-200 hover:border-stone-300 hover:bg-stone-50 bg-white'
              }`}
            >
              <span
                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                  isSelected ? 'bg-teal-600 border-teal-600 text-white' : 'border-stone-300 bg-white'
                }`}
              >
                {isSelected && <Check className="h-3 w-3" />}
              </span>
              <span className="flex-1 min-w-0 truncate">{title}</span>
              <Badge variant="outline" className="text-[10px] shrink-0">{course.status}</Badge>
            </button>
          );
        })}
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
          {t('cancel')}
        </Button>
        <Button size="sm" onClick={() => onSave([...selected])} disabled={saving}>
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
          {t('save')}
        </Button>
      </div>
    </Card>
  );
}

type PanelState =
  | { type: 'none' }
  | { type: 'create' }
  | { type: 'edit'; curriculum: CurriculumAdminResponse }
  | { type: 'assign'; curriculumId: string }
  | { type: 'access'; curriculumId: string };

export function CurriculaClient() {
  const t = useTranslations('Admin.curricula');
  const locale = useLocale() as 'fr' | 'en';
  const queryClient = useQueryClient();

  const [panel, setPanel] = useState<PanelState>({ type: 'none' });
  const [deleteTarget, setDeleteTarget] = useState<CurriculumAdminResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [togglingVisibility, setTogglingVisibility] = useState<string | null>(null);

  const { data: curricula = [], isLoading } = useQuery<CurriculumAdminResponse[]>({
    queryKey: ['admin', 'curricula'],
    queryFn: getAdminCurricula,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admin', 'curricula'] });

  const handleCreate = async (form: CurriculumFormData) => {
    setSaving(true);
    try {
      await createAdminCurriculum({
        title_fr: form.title_fr,
        title_en: form.title_en,
        description_fr: form.description_fr || undefined,
        description_en: form.description_en || undefined,
        cover_image_url: form.cover_image_url || undefined,
      });
      setPanel({ type: 'none' });
      invalidate();
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async (form: CurriculumFormData) => {
    if (panel.type !== 'edit') return;
    setSaving(true);
    try {
      await updateAdminCurriculum(panel.curriculum.id, {
        title_fr: form.title_fr,
        title_en: form.title_en,
        description_fr: form.description_fr || undefined,
        description_en: form.description_en || undefined,
        cover_image_url: form.cover_image_url || undefined,
      });
      setPanel({ type: 'none' });
      invalidate();
    } finally {
      setSaving(false);
    }
  };

  const handlePublish = async (id: string) => {
    await publishAdminCurriculum(id);
    invalidate();
  };

  const handleArchive = async (id: string) => {
    await archiveAdminCurriculum(id);
    invalidate();
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteAdminCurriculum(deleteTarget.id);
      setDeleteTarget(null);
      invalidate();
    } catch {
    }
  };

  const handleAssign = async (courseIds: string[]) => {
    if (panel.type !== 'assign') return;
    setSaving(true);
    try {
      await assignCurriculumCourses(panel.curriculumId, courseIds);
      setPanel({ type: 'none' });
      invalidate();
    } finally {
      setSaving(false);
    }
  };

  const handleToggleVisibility = async (curriculum: CurriculumAdminResponse) => {
    const next = curriculum.visibility === 'public' ? 'private' : 'public';
    setTogglingVisibility(curriculum.id);
    try {
      await setCurriculumVisibility(curriculum.id, next);
      invalidate();
      if (next === 'private') {
        setPanel({ type: 'access', curriculumId: curriculum.id });
      }
    } finally {
      setTogglingVisibility(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{t('subtitle')}</p>
        <Button
          size="sm"
          onClick={() => setPanel({ type: 'create' })}
          disabled={panel.type !== 'none'}
        >
          <Plus className="h-4 w-4 mr-1.5" />
          {t('create')}
        </Button>
      </div>

      {panel.type === 'create' && (
        <CurriculumForm
          onSave={handleCreate}
          onCancel={() => setPanel({ type: 'none' })}
          saving={saving}
        />
      )}

      {curricula.length === 0 && panel.type === 'none' ? (
        <Card className="p-8 text-center">
          <BookOpen className="h-10 w-10 text-stone-300 mx-auto mb-3" />
          <p className="text-sm font-medium text-stone-600">{t('noCurricula')}</p>
          <p className="text-xs text-stone-400 mt-1">{t('noCurriculaDescription')}</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {curricula.map((curriculum) => {
            const title = locale === 'fr' ? curriculum.title_fr : curriculum.title_en;
            const isEditingThis = panel.type === 'edit' && panel.curriculum.id === curriculum.id;
            const isAssigningThis = panel.type === 'assign' && panel.curriculumId === curriculum.id;
            const isAccessThis = panel.type === 'access' && panel.curriculumId === curriculum.id;
            const isTogglingThis = togglingVisibility === curriculum.id;

            return (
              <div key={curriculum.id} className="space-y-2">
                <Card className="p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-sm font-semibold text-stone-900 truncate">{title}</h3>
                        <StatusBadge status={curriculum.status} />
                        <VisibilityBadge visibility={curriculum.visibility ?? 'public'} />
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {t('courseCount', { count: curriculum.course_count })} •{' '}
                        <span className="font-mono">/curricula/{curriculum.slug}</span>
                      </p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0 flex-wrap justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-9 px-2 text-xs"
                        onClick={() => handleToggleVisibility(curriculum)}
                        disabled={isTogglingThis || (panel.type !== 'none' && !isAccessThis)}
                        title={curriculum.visibility === 'private' ? t('makePublic') : t('makePrivate')}
                      >
                        {isTogglingThis ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : curriculum.visibility === 'private' ? (
                          <Unlock className="h-3.5 w-3.5 mr-1" />
                        ) : (
                          <Lock className="h-3.5 w-3.5 mr-1" />
                        )}
                        {curriculum.visibility === 'private' ? t('makePublic') : t('makePrivate')}
                      </Button>
                      {curriculum.visibility === 'private' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-9 px-2 text-xs text-amber-600 hover:text-amber-700"
                          onClick={() =>
                            setPanel(
                              isAccessThis
                                ? { type: 'none' }
                                : { type: 'access', curriculumId: curriculum.id }
                            )
                          }
                          disabled={panel.type !== 'none' && !isAccessThis}
                        >
                          <ShieldCheck className="h-3.5 w-3.5 mr-1" />
                          {t('manageAccess')}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-9 px-2 text-xs"
                        onClick={() =>
                          setPanel(
                            isAssigningThis
                              ? { type: 'none' }
                              : { type: 'assign', curriculumId: curriculum.id }
                          )
                        }
                        disabled={panel.type !== 'none' && !isAssigningThis}
                      >
                        <BookOpen className="h-3.5 w-3.5 mr-1" />
                        {t('assignCourses')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-9 w-9 p-0"
                        onClick={() =>
                          setPanel(
                            isEditingThis ? { type: 'none' } : { type: 'edit', curriculum }
                          )
                        }
                        disabled={panel.type !== 'none' && !isEditingThis}
                        aria-label={t('edit')}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      {curriculum.status === 'draft' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-9 px-2 text-xs text-teal-600 hover:text-teal-700"
                          onClick={() => handlePublish(curriculum.id)}
                          disabled={panel.type !== 'none'}
                        >
                          <Globe className="h-3.5 w-3.5 mr-1" />
                          {t('publish')}
                        </Button>
                      )}
                      {curriculum.status === 'published' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-9 px-2 text-xs text-amber-600 hover:text-amber-700"
                          onClick={() => handleArchive(curriculum.id)}
                          disabled={panel.type !== 'none'}
                        >
                          <Archive className="h-3.5 w-3.5 mr-1" />
                          {t('archive')}
                        </Button>
                      )}
                      {curriculum.status !== 'published' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-9 w-9 p-0 text-destructive hover:text-destructive"
                          onClick={() => setDeleteTarget(curriculum)}
                          disabled={panel.type !== 'none'}
                          aria-label={t('delete')}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                </Card>

                {isEditingThis && (
                  <CurriculumForm
                    initial={{
                      title_fr: curriculum.title_fr,
                      title_en: curriculum.title_en,
                      description_fr: curriculum.description_fr,
                      description_en: curriculum.description_en,
                      cover_image_url: curriculum.cover_image_url,
                    }}
                    onSave={handleEdit}
                    onCancel={() => setPanel({ type: 'none' })}
                    saving={saving}
                  />
                )}

                {isAssigningThis && (
                  <CourseAssignPanel
                    curriculumId={curriculum.id}
                    onClose={() => setPanel({ type: 'none' })}
                    onSave={handleAssign}
                    saving={saving}
                  />
                )}

                {isAccessThis && (
                  <AccessManagementPanel
                    curriculumId={curriculum.id}
                    onClose={() => setPanel({ type: 'none' })}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      <AlertDialog open={!!deleteTarget} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogTitle>{t('confirmDelete')}</AlertDialogTitle>
          <AlertDialogDescription>{t('confirmDeleteDesc')}</AlertDialogDescription>
          <div className="flex gap-2 justify-end mt-4">
            <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>{t('delete')}</AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

