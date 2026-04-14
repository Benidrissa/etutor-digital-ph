'use client';

import { useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, Globe, Archive, BookOpen, Loader2, Check, X, Lock, Unlock, Users, UserPlus, Trash } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import { CourseAssignPanel } from '@/components/shared/course-assign-panel';
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

interface AdminUserBasic {
  id: string;
  email: string;
  name: string;
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
        <Lock className="h-2.5 w-2.5" />
        {t('visibility.private')}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-teal-200 bg-teal-50 px-2 py-0.5 text-xs font-medium text-teal-700">
      <Globe className="h-2.5 w-2.5" />
      {t('visibility.public')}
    </span>
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

function AccessManagementPanel({
  curriculumId,
  onClose,
}: {
  curriculumId: string;
  onClose: () => void;
}) {
  const t = useTranslations('Admin.curricula.access');
  const [grantType, setGrantType] = useState<'user' | 'group'>('user');
  const [userSearch, setUserSearch] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [granting, setGranting] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: accessEntries = [], isLoading } = useQuery<CurriculumAccessEntry[]>({
    queryKey: ['admin', 'curricula', curriculumId, 'access'],
    queryFn: () => getCurriculumAccess(curriculumId),
  });

  const { data: groups = [] } = useQuery<UserGroupResponse[]>({
    queryKey: ['admin', 'groups'],
    queryFn: getAdminGroups,
  });

  const { data: allUsers = [] } = useQuery<AdminUserBasic[]>({
    queryKey: ['admin', 'users', 'basic'],
    queryFn: () => apiFetch('/api/v1/admin/users?limit=200'),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['admin', 'curricula', curriculumId, 'access'] });

  const filteredUsers = allUsers.filter(
    (u) =>
      userSearch.trim() &&
      ((u.email ?? '').toLowerCase().includes(userSearch.toLowerCase()) ||
        (u.name ?? '').toLowerCase().includes(userSearch.toLowerCase()))
  );

  const handleGrantUser = async (userId: string) => {
    setGranting(true);
    try {
      await grantCurriculumAccess(curriculumId, { user_id: userId });
      setUserSearch('');
      invalidate();
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
      invalidate();
    } finally {
      setGranting(false);
    }
  };

  const handleRevoke = async (accessId: string) => {
    setRevoking(accessId);
    try {
      await revokeCurriculumAccess(curriculumId, accessId);
      invalidate();
    } finally {
      setRevoking(null);
    }
  };

  return (
    <Card className="p-4 border-2 border-amber-200 bg-amber-50/20">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-sm font-medium flex items-center gap-1.5">
            <Lock className="h-3.5 w-3.5 text-amber-600" />
            {t('title')}
          </p>
          <p className="text-xs text-muted-foreground">{t('subtitle')}</p>
        </div>
        <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex gap-1 mb-3">
        <Button
          size="sm"
          variant={grantType === 'user' ? 'default' : 'outline'}
          className="h-8 text-xs"
          onClick={() => setGrantType('user')}
        >
          {t('grantUser')}
        </Button>
        <Button
          size="sm"
          variant={grantType === 'group' ? 'default' : 'outline'}
          className="h-8 text-xs"
          onClick={() => setGrantType('group')}
        >
          {t('grantGroup')}
        </Button>
      </div>

      {grantType === 'user' && (
        <div className="mb-3 space-y-2">
          <Input
            value={userSearch}
            onChange={(e) => setUserSearch(e.target.value)}
            placeholder={t('searchUserPlaceholder')}
            className="h-9 text-sm"
          />
          {filteredUsers.length > 0 && (
            <div className="max-h-36 overflow-y-auto space-y-1 rounded-md border border-stone-200 bg-white p-1">
              {filteredUsers.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => handleGrantUser(u.id)}
                  disabled={granting}
                  className="w-full flex items-center justify-between rounded px-2 py-1.5 text-left text-xs hover:bg-stone-50 min-h-9"
                >
                  <span className="truncate">{u.email}</span>
                  <UserPlus className="h-3.5 w-3.5 shrink-0 text-teal-600 ml-2" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {grantType === 'group' && (
        <div className="mb-3 flex gap-2">
          <select
            value={selectedGroupId}
            onChange={(e) => setSelectedGroupId(e.target.value)}
            className="flex-1 h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">{t('selectGroup')}</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name} ({g.member_count})
              </option>
            ))}
          </select>
          <Button
            size="sm"
            className="h-9"
            onClick={handleGrantGroup}
            disabled={granting || !selectedGroupId}
          >
            {granting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : t('grant')}
          </Button>
        </div>
      )}

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground mb-1">{t('currentAccess')}</p>
        {isLoading && (
          <div className="flex justify-center py-3">
            <Loader2 className="h-4 w-4 animate-spin text-stone-400" />
          </div>
        )}
        {!isLoading && accessEntries.length === 0 && (
          <p className="text-xs text-muted-foreground py-2 text-center">{t('noAccess')}</p>
        )}
        {accessEntries.map((entry) => (
          <div
            key={entry.id}
            className="flex items-center justify-between rounded-lg border border-stone-200 bg-white px-3 py-2"
          >
            <div className="flex items-center gap-2 min-w-0">
              {entry.user_id ? (
                <span className="text-xs shrink-0 rounded bg-stone-100 px-1.5 py-0.5 text-stone-600">
                  {t('typeUser')}
                </span>
              ) : (
                <span className="text-xs shrink-0 rounded bg-blue-100 px-1.5 py-0.5 text-blue-700">
                  <Users className="h-2.5 w-2.5 inline mr-0.5" />
                  {t('typeGroup')}
                </span>
              )}
              <span className="text-xs truncate">
                {entry.user_email ?? entry.group_name ?? entry.user_id ?? entry.group_id}
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-destructive hover:text-destructive shrink-0"
              onClick={() => handleRevoke(entry.id)}
              disabled={revoking === entry.id}
              aria-label={t('revoke')}
            >
              {revoking === entry.id ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Trash className="h-3 w-3" />
              )}
            </Button>
          </div>
        ))}
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
    const newVisibility = curriculum.visibility === 'public' ? 'private' : 'public';
    setTogglingVisibility(curriculum.id);
    try {
      await setCurriculumVisibility(curriculum.id, newVisibility);
      invalidate();
      if (newVisibility === 'private') {
        setPanel({ type: 'access', curriculumId: curriculum.id });
      } else if (panel.type === 'access' && panel.curriculumId === curriculum.id) {
        setPanel({ type: 'none' });
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
            const isAccessingThis = panel.type === 'access' && panel.curriculumId === curriculum.id;
            const visibility = curriculum.visibility ?? 'public';

            return (
              <div key={curriculum.id} className="space-y-2">
                <Card className="p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-sm font-semibold text-stone-900 truncate">{title}</h3>
                        <StatusBadge status={curriculum.status} />
                        <VisibilityBadge visibility={visibility} />
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
                        className={`h-9 px-2 text-xs ${
                          visibility === 'private'
                            ? 'text-amber-600 hover:text-amber-700'
                            : 'text-stone-600 hover:text-stone-700'
                        }`}
                        onClick={() => handleToggleVisibility(curriculum)}
                        disabled={
                          togglingVisibility === curriculum.id ||
                          (panel.type !== 'none' && !isAccessingThis)
                        }
                      >
                        {togglingVisibility === curriculum.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : visibility === 'private' ? (
                          <Lock className="h-3.5 w-3.5 mr-1" />
                        ) : (
                          <Unlock className="h-3.5 w-3.5 mr-1" />
                        )}
                        {visibility === 'private'
                          ? t('visibility.makePublic')
                          : t('visibility.makePrivate')}
                      </Button>
                      {visibility === 'private' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-9 px-2 text-xs text-amber-600 hover:text-amber-700"
                          onClick={() =>
                            setPanel(
                              isAccessingThis
                                ? { type: 'none' }
                                : { type: 'access', curriculumId: curriculum.id }
                            )
                          }
                          disabled={panel.type !== 'none' && !isAccessingThis}
                        >
                          <Users className="h-3.5 w-3.5 mr-1" />
                          {t('access.manage')}
                        </Button>
                      )}
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
                    coursesUrl="/api/v1/admin/courses"
                    currentCourseIds={curriculum.courses?.map((c: {id: string}) => c.id) ?? []}
                    onClose={() => setPanel({ type: 'none' })}
                    onSave={handleAssign}
                    saving={saving}
                  />
                )}

                {isAccessingThis && (
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

