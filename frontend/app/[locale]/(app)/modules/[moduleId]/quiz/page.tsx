import { notFound, redirect } from 'next/navigation';
import { getLocale } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { ChevronLeft } from 'lucide-react';
import { QuizContainer } from '@/components/quiz/quiz-container';
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
  
  // Default to a unit if not specified (for now use a default)
  const unitId = unit || 'unit-1';
  const language = locale as 'en' | 'fr';
  
  // Mock user data - in real app, get from auth context
  const userData = {
    country: 'senegal', // Default country
    level: 2, // Default level
  };
  
  const handleQuizComplete = () => {
    // Redirect back to module overview
    redirect(`/${locale}/modules/${moduleId}`);
  };
  
  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      {/* Breadcrumb */}
      <div className="mb-6">
        <Link 
          href={`/modules/${moduleId}`} 
          className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors"
        >
          <ChevronLeft className="w-4 h-4 mr-1" />
          Back to {moduleData.title[language]}
        </Link>
      </div>
      
      {/* Quiz Container */}
      <QuizContainer
        moduleId={moduleId}
        unitId={unitId}
        language={language}
        country={userData.country}
        level={userData.level}
        onComplete={handleQuizComplete}
        onError={(error) => {
          console.error('Quiz error:', error);
          // In real app, might show toast notification
        }}
      />
    </div>
  );
}