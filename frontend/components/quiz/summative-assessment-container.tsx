'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Timer, AlertTriangle, Loader2, PlayCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { SummativeAssessmentInterface } from './summative-assessment-interface';
import { SummativeAssessmentResults } from './summative-assessment-results';
import type { 
  Quiz, 
  SummativeAssessmentResponse, 
  SummativeAssessmentAttemptCheck 
} from '@/lib/api';
import { 
  generateSummativeAssessment, 
  canAttemptSummativeAssessment 
} from '@/lib/api';

interface SummativeAssessmentContainerProps {
  moduleId: string;
  language: string;
  country: string;
  level: number;
  onComplete?: () => void;
  onRetry?: () => void;
}

type AssessmentState = 'checking' | 'blocked' | 'ready' | 'loading' | 'taking' | 'completed';

export function SummativeAssessmentContainer({
  moduleId,
  language,
  country,
  level,
  onComplete,
  onRetry,
}: SummativeAssessmentContainerProps) {
  const t = useTranslations('SummativeAssessment');
  
  const [state, setState] = useState<AssessmentState>('checking');
  const [assessment, setAssessment] = useState<Quiz | null>(null);
  const [result, setResult] = useState<SummativeAssessmentResponse | null>(null);
  const [attemptCheck, setAttemptCheck] = useState<SummativeAssessmentAttemptCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  // Check if user can attempt assessment
  useEffect(() => {
    const checkEligibility = async () => {
      try {
        setState('checking');
        const check = await canAttemptSummativeAssessment(moduleId);
        setAttemptCheck(check);
        
        if (check.can_attempt) {
          setState('ready');
        } else {
          setState('blocked');
        }
      } catch (error) {
        console.error('Failed to check assessment eligibility:', error);
        setError(t('failedToCheckEligibility'));
      }
    };
    
    checkEligibility();
  }, [moduleId, t]);
  
  const handleStartAssessment = async () => {
    try {
      setState('loading');
      const assessmentData = await generateSummativeAssessment({
        module_id: moduleId,
        language,
        country,
        level,
      });
      
      setAssessment(assessmentData);
      setState('taking');
    } catch (error) {
      console.error('Failed to generate assessment:', error);
      setError(t('failedToGenerateAssessment'));
      setState('ready');
    }
  };
  
  const handleAssessmentComplete = (resultData: SummativeAssessmentResponse) => {
    setResult(resultData);
    setState('completed');
    
    if (resultData.passed && onComplete) {
      onComplete();
    }
  };
  
  const handleAssessmentError = (errorMessage: string) => {
    setError(errorMessage);
  };
  
  const handleRetryAssessment = () => {
    setAssessment(null);
    setResult(null);
    setError(null);
    setState('checking');
    
    if (onRetry) {
      onRetry();
    }
    
    // Re-check eligibility
    const checkEligibility = async () => {
      try {
        const check = await canAttemptSummativeAssessment(moduleId);
        setAttemptCheck(check);
        
        if (check.can_attempt) {
          setState('ready');
        } else {
          setState('blocked');
        }
      } catch (error) {
        console.error('Failed to check assessment eligibility:', error);
        setError(t('failedToCheckEligibility'));
      }
    };
    
    checkEligibility();
  };
  
  const formatDate = (isoString: string): string => {
    return new Date(isoString).toLocaleString();
  };
  
  if (state === 'checking') {
    return (
      <div className="max-w-4xl mx-auto p-4">
        <Card>
          <CardContent className="p-8 text-center">
            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4 text-stone-500" />
            <p className="text-stone-600">{t('checkingEligibility')}</p>
          </CardContent>
        </Card>
      </div>
    );
  }
  
  if (state === 'blocked' && attemptCheck) {
    return (
      <div className="max-w-4xl mx-auto p-4 space-y-6">
        <Card className="bg-orange-50 border-orange-200">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-orange-900">
              <AlertTriangle className="w-5 h-5" />
              {t('cannotAttempt')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {attemptCheck.reason === 'already_passed' && (
              <Alert>
                <AlertDescription>
                  {t('alreadyPassed', { score: attemptCheck.last_attempt_score })}
                </AlertDescription>
              </Alert>
            )}
            
            {attemptCheck.reason === 'cooldown_active' && attemptCheck.next_retry_at && (
              <Alert>
                <AlertDescription>
                  {t('cooldownActive', { time: formatDate(attemptCheck.next_retry_at) })}
                </AlertDescription>
              </Alert>
            )}
            
            <div className="bg-white p-4 rounded-lg">
              <h4 className="font-medium mb-2">{t('attemptHistory')}</h4>
              <div className="text-sm text-stone-600 space-y-1">
                <p>{t('totalAttempts')}: {attemptCheck.attempt_count}</p>
                {attemptCheck.last_attempt_score && (
                  <p>{t('lastScore')}: {attemptCheck.last_attempt_score}%</p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }
  
  if (state === 'loading') {
    return (
      <div className="max-w-4xl mx-auto p-4">
        <Card>
          <CardContent className="p-8 text-center">
            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-4 text-blue-500" />
            <p className="text-stone-600">{t('generatingAssessment')}</p>
          </CardContent>
        </Card>
      </div>
    );
  }
  
  if (state === 'taking' && assessment) {
    return (
      <SummativeAssessmentInterface
        assessment={assessment}
        onComplete={handleAssessmentComplete}
        onError={handleAssessmentError}
        timeLimit={30} // 30 minutes
      />
    );
  }
  
  if (state === 'completed' && result) {
    return (
      <SummativeAssessmentResults
        result={result}
        onRetry={result.can_retry ? handleRetryAssessment : undefined}
        onContinue={onComplete}
      />
    );
  }
  
  // Ready to start assessment
  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      {error && (
        <Alert className="bg-red-50 border-red-200">
          <AlertTriangle className="w-4 h-4" />
          <AlertDescription className="text-red-800">
            {error}
          </AlertDescription>
        </Alert>
      )}
      
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Timer className="w-6 h-6 text-blue-600" />
            {t('summativeAssessment')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="prose prose-stone max-w-none">
            <p>{t('description')}</p>
            
            <h4>{t('requirements')}</h4>
            <ul>
              <li>{t('requirement1')}</li>
              <li>{t('requirement2')}</li>
              <li>{t('requirement3')}</li>
              <li>{t('requirement4')}</li>
            </ul>
            
            <h4>{t('importantNotes')}</h4>
            <ul>
              <li>{t('note1')}</li>
              <li>{t('note2')}</li>
              <li>{t('note3')}</li>
            </ul>
          </div>
          
          {attemptCheck && (
            <div className="bg-stone-50 p-4 rounded-lg">
              <h4 className="font-medium mb-2">{t('attemptHistory')}</h4>
              <div className="text-sm text-stone-600 space-y-1">
                <p>{t('totalAttempts')}: {attemptCheck.attempt_count}</p>
                {attemptCheck.last_attempt_score && (
                  <p>{t('lastScore')}: {attemptCheck.last_attempt_score}%</p>
                )}
              </div>
            </div>
          )}
          
          <div className="flex justify-center">
            <Button
              onClick={handleStartAssessment}
              size="lg"
              className="min-h-12 px-8"
            >
              <PlayCircle className="w-5 h-5 mr-2" />
              {t('startAssessment')}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}