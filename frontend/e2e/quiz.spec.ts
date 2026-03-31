import { test, expect } from '@playwright/test';

// Mock quiz data matching the Quiz type
const MOCK_QUIZ = {
  id: 'quiz-123',
  module_id: 'M01',
  unit_id: 'M01-U01',
  language: 'en',
  cached: false,
  content: {
    title: 'Foundations of Public Health',
    description: 'Test your knowledge of public health fundamentals.',
    questions: [
      {
        id: 'q1',
        question: 'What is the primary goal of public health?',
        options: [
          'To treat individual patients',
          'To prevent disease and promote health at the population level',
          'To perform surgery',
          'To sell pharmaceuticals',
        ],
        correct_answer: 1,
        explanation: 'Public health focuses on population-level prevention and health promotion.',
        difficulty: 'easy',
        sources_cited: ['Schneider, Introduction to Public Health, Ch.1'],
      },
      {
        id: 'q2',
        question: 'Which organization leads global public health efforts?',
        options: ['UNESCO', 'WHO', 'WTO', 'IMF'],
        correct_answer: 1,
        explanation: 'The World Health Organization (WHO) coordinates international public health.',
        difficulty: 'easy',
        sources_cited: [],
      },
    ],
    time_limit_minutes: 30,
    passing_score: 70,
  },
};

const MOCK_RESULT = {
  quiz_id: 'quiz-123',
  score: 100,
  passed: true,
  total_questions: 2,
  correct_answers: 2,
  total_time_seconds: 45,
  results: [
    { question_id: 'q1', correct: true, selected_option: 1, time_taken_seconds: 20 },
    { question_id: 'q2', correct: true, selected_option: 1, time_taken_seconds: 25 },
  ],
};

test.describe('Quiz Flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });

    // Mock quiz generation API
    await page.route('**/api/v1/quiz/generate', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_QUIZ),
      })
    );

    // Mock quiz submission API
    await page.route('**/api/v1/quiz/attempt', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_RESULT),
      })
    );
  });

  test('shows loading state then quiz ready screen', async ({ page }) => {
    await page.goto('/en/modules/M01/quiz?unit=M01-U01');

    // Should eventually show the quiz title
    await expect(page.getByText('Foundations of Public Health')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('2')).toBeVisible(); // number of questions
    await expect(page.getByText('30')).toBeVisible(); // time limit
    await expect(page.getByText(/70%/)).toBeVisible(); // passing score
  });

  test('shows instructions and start button', async ({ page }) => {
    await page.goto('/en/modules/M01/quiz?unit=M01-U01');
    await expect(page.getByText('Foundations of Public Health')).toBeVisible({ timeout: 10000 });

    await expect(
      page.getByText('Answer all questions to the best of your ability')
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start Quiz' })).toBeVisible();
  });

  test('starts quiz and displays first question', async ({ page }) => {
    await page.goto('/en/modules/M01/quiz?unit=M01-U01');
    await expect(page.getByRole('button', { name: 'Start Quiz' })).toBeVisible({ timeout: 10000 });

    await page.getByRole('button', { name: 'Start Quiz' }).click();

    // Question should be visible
    await expect(page.getByText('What is the primary goal of public health?')).toBeVisible();
    // All 4 options should be visible
    await expect(page.getByText('To treat individual patients')).toBeVisible();
    await expect(
      page.getByText('To prevent disease and promote health at the population level')
    ).toBeVisible();
    await expect(page.getByText('To perform surgery')).toBeVisible();
    await expect(page.getByText('To sell pharmaceuticals')).toBeVisible();
    // Progress indicator
    await expect(page.getByText('Question 1 of 2')).toBeVisible();
  });

  test('select answer, submit, and see feedback', async ({ page }) => {
    await page.goto('/en/modules/M01/quiz?unit=M01-U01');
    await page.getByRole('button', { name: 'Start Quiz' }).click({ timeout: 10000 });

    // Submit button should be disabled until an option is selected
    await expect(page.getByRole('button', { name: 'Submit Answer' })).toBeDisabled();

    // Select the correct answer (option B = index 1)
    await page
      .getByText('To prevent disease and promote health at the population level')
      .click();

    // Submit button should now be enabled
    await expect(page.getByRole('button', { name: 'Submit Answer' })).toBeEnabled();
    await page.getByRole('button', { name: 'Submit Answer' }).click();

    // Should show feedback
    await expect(page.getByText('Correct!')).toBeVisible();
    await expect(page.getByText('Explanation')).toBeVisible();
    await expect(
      page.getByText('Public health focuses on population-level prevention')
    ).toBeVisible();

    // Source citation
    await expect(page.getByText(/Schneider/)).toBeVisible();

    // Next Question button should appear
    await expect(page.getByRole('button', { name: 'Next Question' })).toBeVisible();
  });

  test('navigates through all questions and finishes quiz', async ({ page }) => {
    await page.goto('/en/modules/M01/quiz?unit=M01-U01');
    await page.getByRole('button', { name: 'Start Quiz' }).click({ timeout: 10000 });

    // Answer question 1
    await page
      .getByText('To prevent disease and promote health at the population level')
      .click();
    await page.getByRole('button', { name: 'Submit Answer' }).click();
    await expect(page.getByText('Correct!')).toBeVisible();
    await page.getByRole('button', { name: 'Next Question' }).click();

    // Question 2 should now be visible
    await expect(
      page.getByText('Which organization leads global public health efforts?')
    ).toBeVisible();
    await expect(page.getByText('Question 2 of 2')).toBeVisible();

    // Answer question 2
    await page.getByText('WHO').click();
    await page.getByRole('button', { name: 'Submit Answer' }).click();
    await expect(page.getByText('Correct!')).toBeVisible();

    // Last question should show "Finish Quiz" instead of "Next Question"
    await expect(page.getByRole('button', { name: 'Finish Quiz' })).toBeVisible();
    await page.getByRole('button', { name: 'Finish Quiz' }).click();

    // Results screen
    await expect(page.getByText('Quiz Complete')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('100%')).toBeVisible();
    await expect(page.getByText('Passed!')).toBeVisible();
  });

  test('shows error state when quiz generation fails', async ({ page }) => {
    await page.route('**/api/v1/quiz/generate', (route) =>
      route.fulfill({ status: 500, body: 'Server Error' })
    );

    await page.goto('/en/modules/M01/quiz?unit=M01-U01');
    await expect(page.getByText('Quiz Error')).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: 'Try Again' })).toBeVisible();
  });

  test('previous question button is disabled on first question', async ({ page }) => {
    await page.goto('/en/modules/M01/quiz?unit=M01-U01');
    await page.getByRole('button', { name: 'Start Quiz' }).click({ timeout: 10000 });

    await expect(page.getByRole('button', { name: 'Previous Question' })).toBeDisabled();
  });
});
