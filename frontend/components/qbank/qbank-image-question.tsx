'use client';

import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import type { QBankQuestion } from '@/lib/api';

const OPTION_LABELS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

interface QBankImageQuestionProps {
  question: QBankQuestion;
  selectedOption: number | null;
  onSelect: (index: number) => void;
  showFeedback: boolean;
  correctIndices?: number[];
  onImageLoad?: () => void;
}

export function QBankImageQuestion({
  question,
  selectedOption,
  onSelect,
  showFeedback,
  correctIndices,
  onImageLoad,
}: QBankImageQuestionProps) {
  const t = useTranslations('qbank');

  const getOptionStyle = (index: number) => {
    if (!showFeedback || selectedOption === null) {
      return selectedOption === index
        ? 'border-primary bg-primary/10 ring-2 ring-primary'
        : 'border-border hover:border-primary/50 hover:bg-muted/50';
    }

    const isCorrect = correctIndices?.includes(index);
    const isSelected = selectedOption === index;

    if (isCorrect) return 'border-green-500 bg-green-50 dark:bg-green-950/30';
    if (isSelected && !isCorrect) return 'border-red-500 bg-red-50 dark:bg-red-950/30';
    return 'border-border opacity-60';
  };

  return (
    <div className="flex flex-col gap-4">
      {question.image_url && (
        <div className="relative w-full overflow-hidden rounded-lg bg-muted">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={question.image_url}
            alt={question.question_text}
            className="w-full h-auto max-h-[300px] object-contain"
            onLoad={onImageLoad}
          />
        </div>
      )}

      <p className="text-base font-medium leading-relaxed">{question.question_text}</p>

      {showFeedback && selectedOption !== null && (
        <div className={cn(
          'rounded-lg px-3 py-2 text-sm font-medium',
          correctIndices?.includes(selectedOption)
            ? 'bg-green-100 text-green-800 dark:bg-green-950/50 dark:text-green-300'
            : 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300'
        )}>
          {correctIndices?.includes(selectedOption) ? t('correct') : t('incorrect')}
        </div>
      )}

      <div className="flex flex-col gap-2">
        {question.options.map((option, index) => (
          <button
            key={index}
            onClick={() => onSelect(index)}
            disabled={showFeedback && selectedOption !== null}
            className={cn(
              'flex min-h-[44px] items-center gap-3 rounded-lg border-2 px-4 py-3 text-left transition-colors',
              getOptionStyle(index),
              'disabled:cursor-default'
            )}
          >
            <span className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold',
              selectedOption === index
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-muted-foreground/30'
            )}>
              {OPTION_LABELS[index]}
            </span>
            <span className="text-sm">{option}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
