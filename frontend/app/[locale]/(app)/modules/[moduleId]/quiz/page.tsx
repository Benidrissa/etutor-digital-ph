import { notFound } from 'next/navigation';
import { getLocale } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { ChevronLeft } from 'lucide-react';
import { QuizPageClient } from '@/components/quiz/quiz-page-client';
import { getModuleById } from '@/lib/modules';

interface QuizPageProps {
  params: Promise<{ moduleId: string }>;
  searchParams: Promise<{ unit?: string }>;
}

export default async function QuizPage({ params, searchParams }: QuizPageProps) {
  const { moduleId } = await params;
  const { unit } = await searchParams;
  const locale = await getLocale();
  
  const moduleData = getModuleById(moduleId);
  
  if (!moduleData) {
    notFound();
  }
  
  const unitId = unit || 'M01-U01';
  const language = locale as 'en' | 'fr';
  
  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6">
        <Link 
          href={`/modules/${moduleId}`} 
          className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors"
        >
          <ChevronLeft className="w-4 h-4 mr-1" />
          {moduleData.title[language]}
        </Link>
      </div>
      
      <QuizPageClient
        moduleId={moduleId}
        unitId={unitId}
        language={language}
        moduleBackPath={`/${locale}/modules/${moduleId}`}
      />
    </div>
  );
}