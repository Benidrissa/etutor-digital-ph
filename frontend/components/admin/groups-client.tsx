'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, Users, UserPlus, UserMinus, Loader2, ChevronDown, ChevronUp, X } from 'lucide-react';
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
  createAdminGroup,
  updateAdminGroup,
  deleteAdminGroup,
  getAdminGroupMembers,
  addGroupMember,
  removeGroupMember,
  apiFetch,
  type UserGroupResponse,
  type UserGroupMember,
} from '@/lib/api';

interface AdminUserBasic {
  id: string;
  email: string;
  name: string;
}

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

function GroupMembersPanel({
  groupId,
  onClose,
}: {
  groupId: string;
  onClose: () => void;
}) {
  const t = useTranslations('Admin.groups');
  const [userSearch, setUserSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: members = [], isLoading } = useQuery<UserGroupMember[]>({
    queryKey: ['admin', 'groups', groupId, 'members'],
    queryFn: () => getAdminGroupMembers(groupId),
  });

  const { data: allUsers = [] } = useQuery<AdminUserBasic[]>({
    queryKey: ['admin', 'users', 'basic'],
    queryFn: () => apiFetch('/api/v1/admin/users?limit=200'),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['admin', 'groups', groupId, 'members'] });

  const invalidateGroups = () =>
    queryClient.invalidateQueries({ queryKey: ['admin', 'groups'] });

  const memberIds = new Set(members.map((m) => m.user_id));

  const filteredUsers = allUsers.filter(
    (u) =>
      userSearch.trim() &&
      !memberIds.has(u.id) &&
      (u.email.toLowerCase().includes(userSearch.toLowerCase()) ||
        u.name.toLowerCase().includes(userSearch.toLowerCase()))
  );

  const handleAddMember = async (userId: string) => {
    setAdding(true);
    try {
      await addGroupMember(groupId, userId);
      setUserSearch('');
      invalidate();
      invalidateGroups();
    } finally {
      setAdding(false);
    }
  };

  const handleRemoveMember = async (userId: string) => {
    setRemoving(userId);
    try {
      await removeGroupMember(groupId, userId);
      invalidate();
      invalidateGroups();
    } finally {
      setRemoving(null);
    }
  };

  return (
    <Card className="p-4 border-2 border-blue-200 bg-blue-50/20">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium flex items-center gap-1.5">
          <Users className="h-3.5 w-3.5 text-blue-600" />
          {t('members')}
        </p>
        <Button variant="ghost" size="sm" className="h-9 w-9 p-0" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="mb-3 space-y-2">
        <Input
          value={userSearch}
          onChange={(e) => setUserSearch(e.target.value)}
          placeholder={t('searchMemberPlaceholder')}
          className="h-9 text-sm"
        />
        {filteredUsers.length > 0 && (
          <div className="max-h-36 overflow-y-auto space-y-1 rounded-md border border-stone-200 bg-white p-1">
            {filteredUsers.map((u) => (
              <button
                key={u.id}
                type="button"
                onClick={() => handleAddMember(u.id)}
                disabled={adding}
                className="w-full flex items-center justify-between rounded px-2 py-1.5 text-left text-xs hover:bg-stone-50 min-h-9"
              >
                <div className="min-w-0 flex-1">
                  <span className="truncate block">{u.email}</span>
                  {u.name && <span className="truncate block text-stone-400">{u.name}</span>}
                </div>
                <UserPlus className="h-3.5 w-3.5 shrink-0 text-teal-600 ml-2" />
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground mb-1">
          {t('currentMembers')} ({members.length})
        </p>
        {isLoading && (
          <div className="flex justify-center py-3">
            <Loader2 className="h-4 w-4 animate-spin text-stone-400" />
          </div>
        )}
        {!isLoading && members.length === 0 && (
          <p className="text-xs text-muted-foreground py-2 text-center">{t('noMembers')}</p>
        )}
        {members.map((member) => (
          <div
            key={member.user_id}
            className="flex items-center justify-between rounded-lg border border-stone-200 bg-white px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium truncate">{member.email}</p>
              {member.name && <p className="text-xs text-stone-400 truncate">{member.name}</p>}
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-destructive hover:text-destructive shrink-0 ml-2"
              onClick={() => handleRemoveMember(member.user_id)}
              disabled={removing === member.user_id}
              aria-label={t('removeMember')}
            >
              {removing === member.user_id ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <UserMinus className="h-3 w-3" />
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
            const isViewingMembers = panel.type === 'members' && panel.groupId === group.id;

            return (
              <div key={group.id} className="space-y-2">
                <Card className="p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-sm font-semibold text-stone-900">{group.name}</h3>
                        <span className="inline-flex items-center gap-1 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-xs text-stone-600">
                          <Users className="h-2.5 w-2.5" />
                          {t('memberCount', { count: group.member_count })}
                        </span>
                      </div>
                      {group.description && (
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {group.description}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0 flex-wrap justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-9 px-2 text-xs"
                        onClick={() =>
                          setPanel(
                            isViewingMembers
                              ? { type: 'none' }
                              : { type: 'members', groupId: group.id }
                          )
                        }
                        disabled={panel.type !== 'none' && !isViewingMembers}
                      >
                        <Users className="h-3.5 w-3.5 mr-1" />
                        {t('manageMembers')}
                        {isViewingMembers ? (
                          <ChevronUp className="h-3.5 w-3.5 ml-1" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5 ml-1" />
                        )}
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
                    initial={{ name: group.name, description: group.description }}
                    onSave={handleEdit}
                    onCancel={() => setPanel({ type: 'none' })}
                    saving={saving}
                  />
                )}

                {isViewingMembers && (
                  <GroupMembersPanel
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
