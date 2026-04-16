'use client';

import { useParams } from 'next/navigation';
import { CurriculumDetailView } from '@/components/shared/curriculum-detail-view';

export default function OrgCurriculumDetailPage() {
  const params = useParams();
  const slug = params.slug as string;
  const orgSlug = params.orgSlug as string;

  return (
    <CurriculumDetailView
      slug={slug}
      orgSlug={orgSlug}
      shareUrl={`/org/${orgSlug}/curricula/${slug}`}
    />
  );
}
