'use client';

import { useTranslations } from 'next-intl';
import { X, FileText, FileSpreadsheet, File } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface PendingFile {
  localId: string;
  file: File;
  previewUrl?: string;
  uploading: boolean;
  progress: number;
  error?: string;
  fileId?: string;
}

interface FilePreviewProps {
  pendingFile: PendingFile;
  onRemove: (localId: string) => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileIcon({ mimeType, className }: { mimeType: string; className?: string }) {
  if (mimeType.startsWith('image/')) return null;
  if (mimeType === 'application/pdf') return <FileText className={className} />;
  if (
    mimeType === 'text/csv' ||
    mimeType === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  ) {
    return <FileSpreadsheet className={className} />;
  }
  return <File className={className} />;
}

export function FilePreview({ pendingFile, onRemove }: FilePreviewProps) {
  const t = useTranslations('ChatTutor');
  const isImage = pendingFile.file.type.startsWith('image/');
  const sizeLabel = formatBytes(pendingFile.file.size);

  return (
    <div
      className={cn(
        'relative flex items-center gap-2 rounded-lg border bg-muted/50 p-2',
        'min-h-[56px]',
        pendingFile.error && 'border-destructive/50 bg-destructive/5'
      )}
    >
      {isImage && pendingFile.previewUrl ? (
        <img
          src={pendingFile.previewUrl}
          alt={pendingFile.file.name}
          className="h-12 w-12 rounded object-cover shrink-0"
        />
      ) : (
        <div className="flex h-12 w-12 items-center justify-center rounded bg-muted shrink-0">
          <FileIcon mimeType={pendingFile.file.type} className="h-6 w-6 text-muted-foreground" />
        </div>
      )}

      <div className="flex-1 min-w-0">
        <p className="truncate text-sm font-medium leading-tight">{pendingFile.file.name}</p>
        <p className="text-xs text-muted-foreground">{sizeLabel}</p>

        {pendingFile.uploading && (
          <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary transition-all duration-200"
              style={{ width: `${pendingFile.progress}%` }}
            />
          </div>
        )}

        {pendingFile.error && (
          <p className="text-xs text-destructive mt-0.5">{pendingFile.error}</p>
        )}

        {pendingFile.uploading && (
          <p className="text-xs text-muted-foreground mt-0.5">
            {t('fileUpload.uploadProgress', { percent: pendingFile.progress })}
          </p>
        )}
      </div>

      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-8 w-8 shrink-0 rounded-full"
        onClick={() => onRemove(pendingFile.localId)}
        aria-label={t('fileUpload.remove')}
        disabled={pendingFile.uploading}
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
}

interface AttachedFileCardProps {
  name: string;
  mimeType: string;
  sizeBytes: number;
}

export function AttachedFileCard({ name, mimeType, sizeBytes }: AttachedFileCardProps) {
  const isImage = mimeType.startsWith('image/');
  const sizeLabel = formatBytes(sizeBytes);

  return (
    <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-2 py-1.5 text-xs">
      {isImage ? (
        <span className="text-base">🖼</span>
      ) : (
        <FileIcon mimeType={mimeType} className="h-3.5 w-3.5 text-muted-foreground" />
      )}
      <span className="truncate font-medium max-w-[120px]">{name}</span>
      <span className="text-muted-foreground shrink-0">{sizeLabel}</span>
    </div>
  );
}
