/**
 * Component tests for the question card (format Appendix A.5 flow).
 *
 * The behaviour under test is the promise A.5 makes to the learner: a wrong
 * answer gets the hint aimed at *her* mistake, she gets a second try, and the
 * answer is never shown before the explanation.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "@/messages/en.json";
import type { Question } from "@/lib/story-course/types";

import { QuestionCard } from "./question-card";

const TIMES = "×";

function renderCard(question: Question, onAnswered = vi.fn(), bilingual = true) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <QuestionCard
        question={question}
        target="en"
        home="fr"
        bilingual={bilingual}
        rewards={{ unit: { en: "mangoes", fr: "mangues" }, first_try: 2, second_try: 1 }}
        onAnswered={onAnswered}
      />
    </NextIntlClientProvider>,
  );
  return onAnswered;
}

const numberQuestion: Question = {
  id: "q5",
  type: "number",
  calculator: false,
  prompt: { en: "Find the HCF of 24 and 36.", fr: "Trouve le PGCD de 24 et 36." },
  answer: 12,
  traps: [
    {
      answer: 72,
      misconception: "m_hcf_lcm_swap",
      hint: {
        en: "That is the smallest shared multiple, not the biggest shared factor.",
        fr: "C'est le plus petit multiple commun.",
      },
    },
  ],
  hints: [{ en: "Use the Venn overlap.", fr: "Utilise l'intersection." }],
  explanation: {
    en: "24 = 2³ × 3 and 36 = 2² × 3².",
    fr: "24 = 2³ × 3 et 36 = 2² × 3².",
  },
};

describe("QuestionCard", () => {
  it("shows the prompt in both languages in bilingual mode", () => {
    renderCard(numberQuestion);
    expect(screen.getByText("Find the HCF of 24 and 36.")).toBeInTheDocument();
    expect(screen.getByText("Trouve le PGCD de 24 et 36.")).toBeInTheDocument();
  });

  it("shows only the language of instruction when bilingual is off", () => {
    renderCard(numberQuestion, vi.fn(), false);
    expect(screen.getByText("Find the HCF of 24 and 36.")).toBeInTheDocument();
    expect(screen.queryByText("Trouve le PGCD de 24 et 36.")).not.toBeInTheDocument();
  });

  it("marks the no-calculator rule", () => {
    renderCard(numberQuestion);
    expect(screen.getByText("No calculator")).toBeInTheDocument();
  });

  it("does not reveal the explanation before she answers", () => {
    renderCard(numberQuestion);
    expect(
      screen.queryByText(/24 = 2³ × 3 and 36/),
    ).not.toBeInTheDocument();
  });

  it("awards 2 mangoes for a right first answer and shows the explanation", async () => {
    const user = userEvent.setup();
    const onAnswered = renderCard(numberQuestion);

    await user.type(screen.getByLabelText("Your answer"), "12");
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByText("+2 mangoes")).toBeInTheDocument();
    expect(screen.getByText(/24 = 2³ × 3 and 36/)).toBeInTheDocument();
    expect(onAnswered).toHaveBeenCalledWith({
      questionId: "q5",
      points: 2,
      attempts: 1,
    });
  });

  it("gives the trap's own hint on a first wrong answer, and keeps the card open", async () => {
    const user = userEvent.setup();
    const onAnswered = renderCard(numberQuestion);

    await user.type(screen.getByLabelText("Your answer"), "72");
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByText("Hint")).toBeInTheDocument();
    expect(
      screen.getByText(/smallest shared multiple, not the biggest shared factor/),
    ).toBeInTheDocument();
    // Not the generic hint, and not settled yet.
    expect(screen.queryByText("Use the Venn overlap.")).not.toBeInTheDocument();
    expect(onAnswered).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Check" })).toBeEnabled();
  });

  it("falls back to the generic hint when no trap matches", async () => {
    const user = userEvent.setup();
    renderCard(numberQuestion);

    await user.type(screen.getByLabelText("Your answer"), "7");
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByText("Use the Venn overlap.")).toBeInTheDocument();
  });

  it("awards 1 mango when the second try is right", async () => {
    const user = userEvent.setup();
    const onAnswered = renderCard(numberQuestion);
    const input = screen.getByLabelText("Your answer");

    await user.type(input, "72");
    await user.click(screen.getByRole("button", { name: "Check" }));
    await user.clear(input);
    await user.type(input, "12");
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByText("+1 mangoes")).toBeInTheDocument();
    expect(onAnswered).toHaveBeenCalledWith({
      questionId: "q5",
      points: 1,
      attempts: 2,
    });
  });

  it("reveals the explanation after two wrong tries and scores zero", async () => {
    const user = userEvent.setup();
    const onAnswered = renderCard(numberQuestion);
    const input = screen.getByLabelText("Your answer");

    await user.type(input, "72");
    await user.click(screen.getByRole("button", { name: "Check" }));
    await user.clear(input);
    await user.type(input, "6");
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByText("Here is how it works")).toBeInTheDocument();
    expect(screen.getByText(/24 = 2³ × 3 and 36/)).toBeInTheDocument();
    expect(onAnswered).toHaveBeenCalledWith({
      questionId: "q5",
      points: 0,
      attempts: 2,
    });
  });

  it("accepts a decimal comma but shows the reminder", async () => {
    const user = userEvent.setup();
    renderCard({
      ...numberQuestion,
      id: "q9",
      answer: 3.25,
      traps: [],
      hints: [],
    });

    await user.type(screen.getByLabelText("Your answer"), "3,25");
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByText("Use a decimal point (3.25), not a comma.")).toBeInTheDocument();
    expect(screen.getByText("+2 mangoes")).toBeInTheDocument();
  });

  describe("choice questions", () => {
    const choiceQuestion: Question = {
      id: "q1",
      type: "choice",
      prompt: { en: "Which one is prime?", fr: "Lequel est premier ?" },
      answer: "c",
      choices: [
        { id: "a", en: "1", fr: "1", misconception: "m_one_prime" },
        { id: "b", en: "9", fr: "9", misconception: "m_odd_prime" },
        { id: "c", en: "13", fr: "13" },
      ],
      explanation: { en: "13 has two factors.", fr: "13 a deux diviseurs." },
    };

    it("renders every option as a button", () => {
      renderCard(choiceQuestion);
      for (const label of ["1", "9", "13"]) {
        expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
      }
    });

    it("scores a tap on the right option", async () => {
      const user = userEvent.setup();
      const onAnswered = renderCard(choiceQuestion);

      await user.click(screen.getByRole("button", { name: "13" }));

      expect(onAnswered).toHaveBeenCalledWith({
        questionId: "q1",
        points: 2,
        attempts: 1,
      });
    });
  });

  describe("index_form questions", () => {
    const indexQuestion: Question = {
      id: "q3",
      type: "index_form",
      require_index: true,
      prompt: { en: "Write 72 in index form.", fr: "Écris 72 avec des puissances." },
      answer: `2³ ${TIMES} 3²`,
      traps: [
        {
          answer: `2 ${TIMES} 2 ${TIMES} 2 ${TIMES} 3 ${TIMES} 3`,
          misconception: "m_not_index_form",
          hint: { en: "Group the repeats with powers.", fr: "Regroupe avec des puissances." },
        },
      ],
      explanation: { en: "72 = 8 × 9.", fr: "72 = 8 × 9." },
    };

    it("offers superscript keys that type into the answer", async () => {
      const user = userEvent.setup();
      renderCard(indexQuestion);

      await user.type(screen.getByLabelText("Your answer"), "2");
      await user.click(screen.getByRole("button", { name: "Insert ³" }));

      expect(screen.getByLabelText("Your answer")).toHaveValue("2³");
    });

    it("accepts caret notation for superscripts", async () => {
      const user = userEvent.setup();
      const onAnswered = renderCard(indexQuestion);

      await user.type(screen.getByLabelText("Your answer"), "2^3 x 3^2");
      await user.click(screen.getByRole("button", { name: "Check" }));

      expect(onAnswered).toHaveBeenCalledWith({
        questionId: "q3",
        points: 2,
        attempts: 1,
      });
    });

    it("tells her to use powers when she expands the product", async () => {
      const user = userEvent.setup();
      renderCard(indexQuestion);

      await user.type(screen.getByLabelText("Your answer"), "2 x 2 x 2 x 3 x 3");
      await user.click(screen.getByRole("button", { name: "Check" }));

      expect(
        screen.getByText("Right primes — now write them with powers."),
      ).toBeInTheDocument();
      expect(screen.getByText("Group the repeats with powers.")).toBeInTheDocument();
    });
  });
});
