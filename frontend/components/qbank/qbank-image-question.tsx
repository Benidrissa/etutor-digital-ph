'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import { QBankAudioPlayer } from '@/components/qbank/qbank-audio-player';
import type { QBankQuestion } from '@/lib/api';

const OPTION_LABELS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

interface QBankImageQuestionProps {
  question: QBankQuestion;
  /**
   * Pre-fetched audio URLs keyed by language. Populated from
   * TestStartResponse.audio so the player can mount the <audio>
   * element without a per-question round-trip (#1674).
   */
  preloadedAudio?: Record<string, string>;
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
  preloadedAudio,
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
    <div className="flex flex-col gap-2 sm:gap-3">
      {question.image_url && (
        // Height is capped to a fraction of the viewport so the options
        // stay in view on phones (iPhone SE → 813px desktop). object-contain
        // keeps the full illustration visible regardless of aspect ratio.
        <div className="relative h-[30dvh] max-h-[360px] min-h-[160px] w-full overflow-hidden rounded-lg bg-muted sm:h-[38dvh]">
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

      <QBankAudioPlayer
        questionId={question.id}
        preloadedUrls={preloadedAudio}
      />

      <p className="text-sm font-medium leading-snug sm:text-base">
        {question.question_text}
      </p>

      {showFeedback && hasSelection && (
        <div className={cn(
          'rounded-lg px-3 py-1.5 text-sm font-medium',
          isAnswerCorrect
            ? 'bg-green-100 text-green-800 dark:bg-green-950/50 dark:text-green-300'
            : 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300'
        )}>
          {isAnswerCorrect ? t('correct') : t('incorrect')}
        </div>
      )}

      <div className="flex flex-col gap-1.5 sm:gap-2">
        {question.options.map((option, index) => {
          const isSelected = selectedIndices.includes(index);
          return (
            <button
              key={index}
              onClick={() => onToggle(index)}
              disabled={showFeedback}
              className={cn(
                'flex min-h-11 items-center gap-3 rounded-lg border-2 px-3 py-2 text-left transition-colors sm:px-4 sm:py-3',
                getOptionStyle(index),
                'disabled:cursor-default'
              )}
            >
              <span className={cn(
                'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-sm font-semibold sm:h-8 sm:w-8',
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
