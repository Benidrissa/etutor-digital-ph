'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import { QBankAudioPlayer } from '@/components/qbank/qbank-audio-player';
import type { QBankQuestion } from '@/lib/api';

const OPTION_LABELS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

interface QBankImageQuestionProps {
  question: QBankQuestion;
  selectedIndices: number[];
  onToggle: (index: number) => void;
  showFeedback: boolean;
  correctIndices?: number[];
  onImageLoad?: () => void;
}

// Multi-answer questions are scored as an exact set match — the picks equal
// the correct set, order-agnostic (#1632).
function selectionIsCorrect(
  selected: readonly number[],
  correct: readonly number[] | undefined
): boolean {
  if (!correct) return false;
  if (selected.length !== correct.length) return false;
  const correctSet = new Set(correct);
  return selected.every((i) => correctSet.has(i));
}

export function QBankImageQuestion({
  question,
  selectedIndices,
  onToggle,
  showFeedback,
  correctIndices,
  onImageLoad,
}: QBankImageQuestionProps) {
  const t = useTranslations('qbank');
  const hasSelection = selectedIndices.length > 0;
  const isAnswerCorrect = selectionIsCorrect(selectedIndices, correctIndices);

  const getOptionStyle = (index: number) => {
    const isSelected = selectedIndices.includes(index);
    if (!showFeedback) {
      return isSelected
        ? 'border-primary bg-primary/10 ring-2 ring-primary'
        : 'border-border hover:border-primary/50 hover:bg-muted/50';
    }

    const isCorrect = correctIndices?.includes(index);
    if (isCorrect) return 'border-green-500 bg-green-50 dark:bg-green-950/30';
    if (isSelected && !isCorrect) return 'border-red-500 bg-red-50 dark:bg-red-950/30';
    return 'border-border opacity-60';
  };

  return (
    <div className="flex flex-col gap-4">
      {question.image_url && (
        <div className="relative h-[300px] w-full overflow-hidden rounded-lg bg-muted">
          <Image
            src={question.image_url}
            alt={question.question_text}
            fill
            // Player container tops out at max-w-2xl (42rem = 672px).
            sizes="(max-width: 768px) 100vw, 42rem"
            className="object-contain"
            onLoad={onImageLoad}
            priority
          />
        </div>
      )}

      <QBankAudioPlayer questionId={question.id} />

      <p className="text-base font-medium leading-relaxed">{question.question_text}</p>

      {showFeedback && hasSelection && (
        <div className={cn(
          'rounded-lg px-3 py-2 text-sm font-medium',
          isAnswerCorrect
            ? 'bg-green-100 text-green-800 dark:bg-green-950/50 dark:text-green-300'
            : 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300'
        )}>
          {isAnswerCorrect ? t('correct') : t('incorrect')}
        </div>
      )}

      <div className="flex flex-col gap-2">
        {question.options.map((option, index) => {
          const isSelected = selectedIndices.includes(index);
          return (
            <button
              key={index}
              onClick={() => onToggle(index)}
              disabled={showFeedback}
              className={cn(
                'flex min-h-[44px] items-center gap-3 rounded-lg border-2 px-4 py-3 text-left transition-colors',
                getOptionStyle(index),
                'disabled:cursor-default'
              )}
            >
              <span className={cn(
                'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold',
                isSelected
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-muted-foreground/30'
              )}>
                {OPTION_LABELS[index]}
              </span>
              <span className="text-sm">{option}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
