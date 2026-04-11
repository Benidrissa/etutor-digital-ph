/**
 * Client-side quiz scoring for offline mode.
 *
 * Calculates results from stored quiz data (which includes correct_answer
 * fields) and queues the attempt in the offline_actions store for later sync.
 */

import { addOfflineAction } from './db';
import type { Quiz, QuizAttemptResponse, QuizAttemptResult } from '@/lib/api';

interface OfflineQuizAttemptResponse extends QuizAttemptResponse {
  /** Marks this as scored locally, not by the server */
  offline: true;
}

/**
 * Score a quiz attempt locally using stored correct answers.
 * Queues the result in IndexedDB for background sync.
 */
export async function scoreQuizOffline(
  quiz: Quiz,
  answers: Record<string, number>,
  totalTimeSeconds: number,
): Promise<OfflineQuizAttemptResponse> {
  const questions = quiz.content.questions;
  const results: QuizAttemptResult[] = [];
  let correctCount = 0;

  for (const question of questions) {
    const userAnswer = answers[question.id];
    const isCorrect = userAnswer === question.correct_answer;
    if (isCorrect) correctCount++;

    results.push({
      question_id: question.id,
      user_answer: userAnswer ?? -1,
      correct_answer: question.correct_answer,
      is_correct: isCorrect,
      explanation: question.explanation,
      time_taken_seconds: 0, // Individual timing not tracked offline
    });
  }

  const totalQuestions = questions.length;
  const score = totalQuestions > 0 ? (correctCount / totalQuestions) * 100 : 0;
  const passed = score >= (quiz.content.passing_score || 70);

  const response: OfflineQuizAttemptResponse = {
    attempt_id: `offline-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    quiz_id: quiz.id,
    score,
    total_questions: totalQuestions,
    correct_answers: correctCount,
    total_time_seconds: totalTimeSeconds,
    passed,
    lesson_validated: passed,
    results,
    attempted_at: new Date().toISOString(),
    offline: true,
  };

  // Queue for background sync
  await addOfflineAction({
    actionType: 'quiz_answer',
    payload: {
      quiz_id: quiz.id,
      module_id: quiz.module_id,
      unit_id: quiz.unit_id,
      answers,
      total_time_seconds: totalTimeSeconds,
      offline_scored_at: response.attempted_at,
    },
  });

  return response;
}
