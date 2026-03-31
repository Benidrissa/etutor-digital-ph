import { getTranslations } from 'next-intl/server';
import { getLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import Link from 'next/link';
import { ChevronLeft } from 'lucide-react';

import { getModuleById } from '@/lib/modules';
import { LessonViewer } from '@/components/learning/lesson-viewer';

interface LessonPageProps {
  params: Promise<{ moduleId: string; unitId: string }>;
}

export default async function LessonPage({ params }: LessonPageProps) {
  const { moduleId, unitId } = await params;
  const locale = await getLocale();
  const t = await getTranslations('LessonPage');
  
  const moduleData = getModuleById(moduleId);
  
  if (!moduleData) {
    notFound();
  }

  const language = locale as 'fr' | 'en';
  const unit = moduleData.units?.find(u => u.id === unitId);
  
  if (!unit) {
    notFound();
  }

  const handleLessonComplete = () => {
    // This would trigger a router refresh or redirect to next unit
    // For now, we'll just log completion
    console.log('Lesson completed:', moduleId, unitId);
  };

  return (
    <div>
      {/* Breadcrumb */}
      <div className="container mx-auto max-w-4xl px-4 py-4 border-b">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Link 
            href="/modules" 
            className="hover:text-gray-900 transition-colors"
          >
            {t('modules')}
          </Link>
          <span>/</span>
          <Link 
            href={`/modules/${moduleId}`}
            className="hover:text-gray-900 transition-colors"
          >
            {moduleData.title[language]}
          </Link>
          <span>/</span>
          <span className="text-gray-900">
            {unit.title[language]}
          </span>
        </div>
        
        <Link 
          href={`/modules/${moduleId}`} 
          className="inline-flex items-center mt-2 text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ChevronLeft className="w-4 h-4 mr-1" />
          {t('backToModule')}
        </Link>
      </div>

      {/* Lesson Content */}
      <LessonViewer
        moduleId={moduleId}
        unitId={unitId}
        language={language}
        level={moduleData.level}
        countryContext="SN" // This would come from user settings
        onComplete={handleLessonComplete}
      />
    </div>
  );
}

export async function generateMetadata({ params }: LessonPageProps) {
  const { moduleId, unitId } = await params;
  const locale = await getLocale();
  const t = await getTranslations('LessonPage.metadata');
  
  const moduleData = getModuleById(moduleId);
  
  if (!moduleData) {
    return {
      title: t('notFound'),
    };
  }

  const language = locale as 'fr' | 'en';
  const unit = moduleData.units?.find(u => u.id === unitId);
  
  if (!unit) {
    return {
      title: t('notFound'),
    };
  }

  return {
    title: t('title', { 
      unit: unit.title[language], 
      module: moduleData.title[language] 
    }),
    description: unit.description?.[language] || moduleData.description?.[language],
  };
}