'use client';

import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import {
  CheckCircle,
  Star,
  TrendingUp,
  ArrowRight,
  Calendar,
  Trophy,
} from 'lucide-react';

interface PlacementTestResult {
  assigned_level: number;
  score_percentage: number;
  competency_areas: string[];
  recommendations: string[];
  level_description: { en: string; fr: string };
  can_retake_after?: string;
  skipped?: boolean;
}

interface PlacementTestResultsProps {
  result: PlacementTestResult;
  locale: string;
  isSkipped?: boolean;
}

export function PlacementTestResults({ result, locale, isSkipped = false }: PlacementTestResultsProps) {
  const t = useTranslations('PlacementTest');
  const router = useRouter();

  const handleContinue = () => {
    router.push(`/${locale}/dashboard`);
  };

  const getLevelColor = (level: number) => {
    switch (level) {
      case 1: return 'bg-blue-500';
      case 2: return 'bg-green-500';
      case 3: return 'bg-orange-500';
      case 4: return 'bg-purple-500';
      default: return 'bg-gray-500';
    }
  };

  const getLevelBadgeVariant = (level: number) => {
    switch (level) {
      case 1: return 'secondary';
      case 2: return 'default';
      case 3: return 'secondary';
      case 4: return 'default';
      default: return 'secondary';
    }
  };

  return (
    <div className="space-y-6">
      {/* Main Result Card */}
      <Card>
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-full bg-green-100">
            {isSkipped ? (
              <Calendar className="h-10 w-10 text-green-600" />
            ) : (
              <Trophy className="h-10 w-10 text-green-600" />
            )}
          </div>
          <CardTitle className="text-2xl">
            {isSkipped ? 'Assessment Skipped' : t('results.title')}
          </CardTitle>
          <CardDescription>
            {isSkipped 
              ? 'You have been assigned to the beginner level.'
              : 'Your personalized learning path has been determined.'
            }
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Level Assignment */}
          <div className="text-center space-y-3">
            <div className="flex items-center justify-center">
              <Badge
                variant={getLevelBadgeVariant(result.assigned_level)}
                className="text-lg px-4 py-2"
              >
                {t('results.assignedLevel', { level: result.assigned_level })}
              </Badge>
            </div>
            <p className="text-lg font-medium">
              {result.level_description[locale as 'en' | 'fr']}
            </p>
            
            {!isSkipped && (
              <div className="flex items-center justify-center space-x-2">
                <Star className="h-5 w-5 text-yellow-500" />
                <span className="text-xl font-bold">
                  {t('results.overallScore', { score: Math.round(result.score_percentage) })}
                </span>
                <Star className="h-5 w-5 text-yellow-500" />
              </div>
            )}
          </div>

          {/* Level Progress Indicator */}
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span>Level 1</span>
              <span>Level 2</span>
              <span>Level 3</span>
              <span>Level 4</span>
            </div>
            <div className="relative">
              <Progress value={(result.assigned_level / 4) * 100} className="h-3" />
              <div
                className={`absolute top-0 left-0 h-3 rounded-full ${getLevelColor(result.assigned_level)}`}
                style={{ width: `${(result.assigned_level / 4) * 100}%` }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Competency Areas */}
      {result.competency_areas.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center">
              <CheckCircle className="h-5 w-5 mr-2 text-green-600" />
              {t('results.strongAreas')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 md:grid-cols-2">
              {result.competency_areas.map((area, index) => (
                <Badge key={index} variant="outline" className="justify-start p-3">
                  <TrendingUp className="h-4 w-4 mr-2 text-green-600" />
                  {area}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recommendations */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center">
            <Star className="h-5 w-5 mr-2 text-blue-600" />
            {t('results.recommendations')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-3">
            {result.recommendations.map((recommendation, index) => (
              <li key={index} className="flex items-start">
                <ArrowRight className="h-4 w-4 mr-3 mt-1 text-blue-600 flex-shrink-0" />
                <span>{recommendation}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {/* Retake Information */}
      {result.can_retake_after && !isSkipped && (
        <Card className="border-amber-200 bg-amber-50">
          <CardContent className="pt-6">
            <div className="flex items-center space-x-3">
              <Calendar className="h-5 w-5 text-amber-600" />
              <div>
                <p className="text-sm font-medium text-amber-900">
                  {t('results.retakeAvailable')}
                </p>
                <p className="text-sm text-amber-800">
                  Next available: {new Date(result.can_retake_after).toLocaleDateString()}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Continue Button */}
      <div className="text-center">
        <Button
          onClick={handleContinue}
          size="lg"
          className="min-h-12 px-8"
        >
          {t('results.continueToLearning')}
          <ArrowRight className="h-4 w-4 ml-2" />
        </Button>
      </div>
    </div>
  );
}