'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, Users, UserPlus, UserMinus, Loader2, X, ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
import {
  getAdminGroups,
  getAdminGroup,
  createAdminGroup,
  updateAdminGroup,
  deleteAdminGroup,
  addGroupMember,
  removeGroupMember,
  type UserGroupResponse,
  type UserGroupDetailResponse,
  type UserGroupMember,
} from '@/lib/api';

interface GroupFormData {
  name: string;
  description: string;
}

function GroupForm({
  initial,
  onSave,
  onCancel,
  saving,
}: {
  initial?: Partial<GroupFormData>;
  onSave: (data: GroupFormData) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const t = useTranslations('Admin.groups');
  const [form, setForm] = useState<GroupFormData>({
    name: initial?.name ?? '',
    description: initial?.description ?? '',
  });

  const update = (field: keyof GroupFormData, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  return (
    <Card className="p-4 border-2 border-teal-200 bg-teal-50/30">
      <div className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor="group_name" className="text-xs">{t('name')}</Label>
          <Input
            id="group_name"
            value={form.name}
            onChange={(e) => update('name', e.target.value)}
            placeholder={t('namePlaceholder')}
            className="h-9 text-sm"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="group_description" className="text-xs">{t('description')}</Label>
          <Textarea
            id="group_description"
            rows={2}
            value={form.description}
            onChange={(e) => update('description', e.target.value)}
            placeholder={t('descriptionPlaceholder')}
            className="text-sm resize-none"
          />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={onCancel} disabled={saving}>
            {t('cancel')}
          </Button>
          <Button
            size="sm"
            onClick={() => onSave(form)}
            disabled={saving || !form.name.trim()}
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
            {t('save')}
          </Button>
        </div>
      </div>
    </Card>
  );
}

function MembersPanel({
  groupId,
  onClose,
}: {
  groupId: string;
  onClose: () => void;
}) {
  const t = useTranslations('Admin.groups');
  const [emailInput, setEmailInput] = useState('');
  const [adding, setAdding] = useState(false);
  const queryClient = useQueryClient();

  const { data: detail, isLoading } = useQuery<UserGroupDetailResponse>({
    queryKey: ['admin', 'groups', groupId],
    queryFn: () => getAdminGroup(groupId),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['admin', 'groups', groupId] });

  const invalidateList = () =>
    queryClient.invalidateQueries({ queryKey: ['admin', 'groups'] });

  const handleAdd = async () => {
    if (!emailInput.trim()) return;
    setAdding(true);
    try {
      await addGroupMember(groupId, { email: emailInput.trim() });
      setEmailInput('');
      invalidate();
      invalidateList();
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (userId: string) => {
    await removeGroupMember(groupId, userId);
    invalidate();
    invalidateList();
  };

  return (
    <Card className="p-4 border-2 border-blue-200 bg-blue-50/30">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-blue-600" />
          <p className="text-sm font-medium">{t('members')}</p>
        </div>
        <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="space-y-3">
        <div>
          <p className="text-xs font-medium text-stone-700 mb-1.5">{t('addMember')}</p>
          <div className="flex gap-2">
            <Input
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
              placeholder={t('memberEmailPlaceholder')}
              className="h-9 text-sm flex-1"
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            />
            <Button
              size="sm"
              className="h-9 shrink-0"
              onClick={handleAdd}
              disabled={adding || !emailInput.trim()}
            >
              {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
            </Button>
          </div>
        </div>

        <div>
          <p className="text-xs font-medium text-stone-700 mb-1.5">{t('currentMembers')}</p>
          {isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-4 w-4 animate-spin text-stone-400" />
            </div>
          ) : !detail?.members?.length ? (
            <p className="text-xs text-muted-foreground py-2">{t('noMembers')}</p>
          ) : (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {detail.members.map((member: UserGroupMember) => (
                <div
                  key={member.user_id}
                  className="flex items-center justify-between rounded-lg border border-stone-200 bg-white px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{member.name ?? member.email}</p>
                    {member.name && (
                      <p className="text-[10px] text-muted-foreground truncate">{member.email}</p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 text-destructive hover:text-destructive shrink-0"
                    onClick={() => handleRemove(member.user_id)}
                    aria-label={t('removeMember')}
                  >
                    <UserMinus className="h-3.5 w-3.5" />
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

type PanelState =
  | { type: 'none' }
  | { type: 'create' }
  | { type: 'edit'; group: UserGroupResponse }
  | { type: 'members'; groupId: string };

export function GroupsClient() {
  const t = useTranslations('Admin.groups');
  const queryClient = useQueryClient();

  const [panel, setPanel] = useState<PanelState>({ type: 'none' });
  const [deleteTarget, setDeleteTarget] = useState<UserGroupResponse | null>(null);
  const [saving, setSaving] = useState(false);

  const { data: groups = [], isLoading } = useQuery<UserGroupResponse[]>({
    queryKey: ['admin', 'groups'],
    queryFn: getAdminGroups,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admin', 'groups'] });

  const handleCreate = async (form: GroupFormData) => {
    setSaving(true);
    try {
      await createAdminGroup({
        name: form.name,
        description: form.description || undefined,
      });
      setPanel({ type: 'none' });
      invalidate();
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async (form: GroupFormData) => {
    if (panel.type !== 'edit') return;
    setSaving(true);
    try {
      await updateAdminGroup(panel.group.id, {
        name: form.name,
        description: form.description || undefined,
      });
      setPanel({ type: 'none' });
      invalidate();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteAdminGroup(deleteTarget.id);
      setDeleteTarget(null);
      invalidate();
    } catch {
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
        <GroupForm
          onSave={handleCreate}
          onCancel={() => setPanel({ type: 'none' })}
          saving={saving}
        />
      )}

      {groups.length === 0 && panel.type === 'none' ? (
        <Card className="p-8 text-center">
          <Users className="h-10 w-10 text-stone-300 mx-auto mb-3" />
          <p className="text-sm font-medium text-stone-600">{t('noGroups')}</p>
          <p className="text-xs text-stone-400 mt-1">{t('noGroupsDescription')}</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {groups.map((group) => {
            const isEditingThis = panel.type === 'edit' && panel.group.id === group.id;
            const isMembersThis = panel.type === 'members' && panel.groupId === group.id;

            return (
              <div key={group.id} className="space-y-2">
                <Card className="p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm font-semibold text-stone-900">{group.name}</h3>
                      {group.description && (
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {group.description}
                        </p>
                      )}
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {t('memberCount', { count: group.member_count })}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0 flex-wrap justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-9 px-2 text-xs"
                        onClick={() =>
                          setPanel(
                            isMembersThis
                              ? { type: 'none' }
                              : { type: 'members', groupId: group.id }
                          )
                        }
                        disabled={panel.type !== 'none' && !isMembersThis}
                      >
                        {isMembersThis ? (
                          <ChevronDown className="h-3.5 w-3.5 mr-1" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5 mr-1" />
                        )}
                        {t('viewMembers')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-9 w-9 p-0"
                        onClick={() =>
                          setPanel(
                            isEditingThis ? { type: 'none' } : { type: 'edit', group }
                          )
                        }
                        disabled={panel.type !== 'none' && !isEditingThis}
                        aria-label={t('edit')}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-9 w-9 p-0 text-destructive hover:text-destructive"
                        onClick={() => setDeleteTarget(group)}
                        disabled={panel.type !== 'none'}
                        aria-label={t('delete')}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </Card>

                {isEditingThis && (
                  <GroupForm
                    initial={{
                      name: group.name,
                      description: group.description,
                    }}
                    onSave={handleEdit}
                    onCancel={() => setPanel({ type: 'none' })}
                    saving={saving}
                  />
                )}

                {isMembersThis && (
                  <MembersPanel
                    groupId={group.id}
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
