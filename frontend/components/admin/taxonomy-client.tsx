'use client';

import { useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, Loader2, ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import {
  getAdminTaxonomy,
  createTaxonomyCategory,
  updateTaxonomyCategory,
  deleteTaxonomyCategory,
  type TaxonomyCategoryAdmin,
} from '@/lib/api';

const SECTIONS = [
  { key: 'domains', type: 'domain' },
  { key: 'levels', type: 'level' },
  { key: 'audience_types', type: 'audience' },
] as const;

function CategoryRow({
  cat,
  onEdit,
  onDelete,
  locale,
}: {
  cat: TaxonomyCategoryAdmin;
  onEdit: (cat: TaxonomyCategoryAdmin) => void;
  onDelete: (cat: TaxonomyCategoryAdmin) => void;
  locale: string;
}) {
  const t = useTranslations('Admin.taxonomy');

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-background border border-stone-100 hover:border-stone-200 transition-colors">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium truncate">
            {locale === 'fr' ? cat.label_fr : cat.label_en}
          </span>
          <Badge variant="outline" className="text-[10px] shrink-0">
            {cat.slug}
          </Badge>
          {!cat.is_active && (
            <Badge variant="secondary" className="text-[10px] shrink-0">
              {t('inactive')}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          FR: {cat.label_fr} &middot; EN: {cat.label_en}
        </p>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Button
          variant="ghost"
          size="sm"
          className="h-9 w-9 p-0"
          onClick={() => onEdit(cat)}
          aria-label={t('editCategory')}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-9 w-9 p-0 text-destructive hover:text-destructive"
          onClick={() => onDelete(cat)}
          aria-label={t('deleteCategory')}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

function CategoryForm({
  initial,
  type,
  onSave,
  onCancel,
  saving,
}: {
  initial?: TaxonomyCategoryAdmin;
  type: string;
  onSave: (data: {
    type: string;
    slug: string;
    label_fr: string;
    label_en: string;
    sort_order: number;
    is_active?: boolean;
  }) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const t = useTranslations('Admin.taxonomy');
  const [slug, setSlug] = useState(initial?.slug ?? '');
  const [labelFr, setLabelFr] = useState(initial?.label_fr ?? '');
  const [labelEn, setLabelEn] = useState(initial?.label_en ?? '');
  const [sortOrder, setSortOrder] = useState(String(initial?.sort_order ?? 0));
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      type,
      slug: slug.trim().toLowerCase().replace(/\s+/g, '_'),
      label_fr: labelFr.trim(),
      label_en: labelEn.trim(),
      sort_order: parseInt(sortOrder) || 0,
      ...(initial ? { is_active: isActive } : {}),
    });
  };

  return (
    <form onSubmit={handleSubmit} className="border rounded-lg p-3 space-y-3 bg-stone-50">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label className="text-xs">{t('slug')}</Label>
          <Input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="e.g. pharmacy"
            className="h-9 text-sm"
            disabled={!!initial}
            required
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">{t('sortOrder')}</Label>
          <Input
            type="number"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value)}
            className="h-9 text-sm"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label className="text-xs">{t('labelFr')}</Label>
          <Input
            value={labelFr}
            onChange={(e) => setLabelFr(e.target.value)}
            placeholder="Pharmacie"
            className="h-9 text-sm"
            required
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">{t('labelEn')}</Label>
          <Input
            value={labelEn}
            onChange={(e) => setLabelEn(e.target.value)}
            placeholder="Pharmacy"
            className="h-9 text-sm"
            required
          />
        </div>
      </div>
      {initial && (
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="rounded"
          />
          {t('active')}
        </label>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} className="h-9">
          {t('cancel')}
        </Button>
        <Button type="submit" size="sm" disabled={saving} className="h-9 gap-1.5">
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t('save')}
        </Button>
      </div>
    </form>
  );
}

export function TaxonomyClient() {
  const t = useTranslations('Admin.taxonomy');
  const locale = useLocale();
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'taxonomy'],
    queryFn: getAdminTaxonomy,
  });

  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(['domains', 'levels', 'audience_types'])
  );
  const [editingId, setEditingId] = useState<string | null>(null);
  const [addingType, setAddingType] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TaxonomyCategoryAdmin | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const createMutation = useMutation({
    mutationFn: createTaxonomyCategory,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'taxonomy'] });
      queryClient.invalidateQueries({ queryKey: ['taxonomy'] });
      setAddingType(null);
      setSaving(false);
    },
    onError: () => setSaving(false),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      updateTaxonomyCategory(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'taxonomy'] });
      queryClient.invalidateQueries({ queryKey: ['taxonomy'] });
      setEditingId(null);
      setSaving(false);
    },
    onError: () => setSaving(false),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTaxonomyCategory,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'taxonomy'] });
      queryClient.invalidateQueries({ queryKey: ['taxonomy'] });
      setDeleteTarget(null);
      setDeleteError(null);
    },
    onError: () => {
      setDeleteError(t('deleteBlocked'));
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="text-center py-12 text-destructive text-sm">
        Failed to load taxonomy.
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4">
        {SECTIONS.map(({ key, type }) => {
          const items = (data as unknown as Record<string, TaxonomyCategoryAdmin[]>)[key] || [];
          const isExpanded = expandedSections.has(key);

          return (
            <Card key={key} className="overflow-hidden">
              <button
                type="button"
                onClick={() => toggleSection(key)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  )}
                  <h3 className="font-semibold text-sm">
                    {t(`sections.${type}`)}
                  </h3>
                  <Badge variant="secondary" className="text-xs">
                    {items.length}
                  </Badge>
                </div>
              </button>

              {isExpanded && (
                <div className="px-4 pb-4 space-y-2">
                  {items.map((cat) =>
                    editingId === cat.id ? (
                      <CategoryForm
                        key={cat.id}
                        initial={cat}
                        type={type}
                        saving={saving}
                        onCancel={() => setEditingId(null)}
                        onSave={(data) => {
                          setSaving(true);
                          updateMutation.mutate({
                            id: cat.id,
                            label_fr: data.label_fr,
                            label_en: data.label_en,
                            sort_order: data.sort_order,
                            is_active: data.is_active,
                          });
                        }}
                      />
                    ) : (
                      <CategoryRow
                        key={cat.id}
                        cat={cat}
                        locale={locale}
                        onEdit={() => setEditingId(cat.id)}
                        onDelete={() => setDeleteTarget(cat)}
                      />
                    )
                  )}

                  {addingType === type ? (
                    <CategoryForm
                      type={type}
                      saving={saving}
                      onCancel={() => setAddingType(null)}
                      onSave={(data) => {
                        setSaving(true);
                        createMutation.mutate(data);
                      }}
                    />
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full min-h-11 gap-1.5"
                      onClick={() => setAddingType(type)}
                    >
                      <Plus className="h-4 w-4" />
                      {t('addCategory')}
                    </Button>
                  )}
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {/* Delete confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
            setDeleteError(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{t('deleteConfirm')}</AlertDialogTitle>
          <AlertDialogDescription>
            {deleteError || t('deleteConfirmDesc')}
          </AlertDialogDescription>
          <div className="flex justify-end gap-2 mt-4">
            <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
            {!deleteError && (
              <AlertDialogAction
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                onClick={() => {
                  if (deleteTarget) {
                    deleteMutation.mutate(deleteTarget.id);
                  }
                }}
              >
                {t('deleteCategory')}
              </AlertDialogAction>
            )}
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
