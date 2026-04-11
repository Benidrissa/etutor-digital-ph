'use client';

import { useState, useEffect, useCallback } from 'react';
import { SyncManager, type SyncStatus } from '@/lib/offline/sync-manager';

export interface UseSyncStatusReturn {
  /** Current sync status */
  status: SyncStatus;
  /** Number of pending offline actions */
  pendingCount: number;
  /** Whether sync is currently running */
  isSyncing: boolean;
  /** Manually trigger a sync */
  syncNow: () => void;
}

export function useSyncStatus(): UseSyncStatusReturn {
  const [status, setStatus] = useState<SyncStatus>({ state: 'idle' });
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    const manager = SyncManager.getInstance();
    manager.start();

    // Load initial pending count
    manager.getPendingCount().then(setPendingCount);

    // Subscribe to status changes
    const unsub = manager.onStatusChange((newStatus) => {
      setStatus(newStatus);

      // Refresh pending count after sync completes or errors
      if (newStatus.state === 'complete' || newStatus.state === 'error') {
        manager.getPendingCount().then(setPendingCount);

        // Auto-clear status after 4 seconds
        setTimeout(() => setStatus({ state: 'idle' }), 4000);
      }
    });

    return () => {
      unsub();
    };
  }, []);

  // Refresh pending count periodically (every 30s) to pick up new offline actions
  useEffect(() => {
    const interval = setInterval(() => {
      SyncManager.getInstance().getPendingCount().then(setPendingCount);
    }, 30_000);
    return () => clearInterval(interval);
  }, []);

  const syncNow = useCallback(() => {
    SyncManager.getInstance().syncNow();
  }, []);

  return {
    status,
    pendingCount,
    isSyncing: status.state === 'syncing',
    syncNow,
  };
}
