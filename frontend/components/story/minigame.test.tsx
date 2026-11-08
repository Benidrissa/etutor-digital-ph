/**
 * Component tests for the mini-game engines (format A.9, contract C5).
 *
 * The `catch` engine is what every lesson story's required mini-game uses, so
 * before it existed an items-shaped round was silently dropped and the game
 * rendered "unavailable", awarding 0 of the points the validator counted into
 * max_points. `pop` must keep working for the authored maths weeks.
 */

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import messages from "@/messages/en.json";
import type { Minigame } from "@/lib/story-course/types";

import { MinigameView, playableRounds } from "./minigame";

const catchGame: Minigame = {
  id: "g1",
  engine: "catch",
  title: { en: "Clean hands", fr: "Mains propres" },
  instruction: { en: "Tap every right answer.", fr: "Touche chaque bonne réponse." },
  hint_after_wrong: {
    en: "Germs travel on hands that look clean too.",
    fr: "Les germes voyagent aussi sur des mains propres en apparence.",
  },
  points: { per_correct: 1 },
  timer_s: 5,
  rounds: [
    {
      prompt: { en: "When must you wash your hands?", fr: "Quand faut-il se laver les mains ?" },
      items: [
        { label: { en: "Before touching a patient", fr: "Avant de toucher un patient" }, correct: true },
        { label: { en: "After touching a patient", fr: "Après avoir touché un patient" }, correct: true },
        {
          label: { en: "Only when they look dirty", fr: "Seulement si elles semblent sales" },
          correct: false,
          trap: "m_visible_dirt",
        },
      ],
    },
    {
      prompt: { en: "What cleans best?", fr: "Qu'est-ce qui nettoie le mieux ?" },
      items: [
        { label: { en: "Soap and water", fr: "Eau et savon" }, correct: true },
        { label: { en: "Water alone", fr: "L'eau seule" }, correct: false, trap: "m_water_only" },
      ],
    },
  ],
};

const popGame: Minigame = {
  id: "g_pop",
  engine: "pop",
  title: { en: "Prime Pop", fr: "Mangues premières" },
  instruction: { en: "Tap only the primes!", fr: "Touche seulement les premiers !" },
  rule: { fn: "is_prime" },
  timer_s: 20,
  rounds: [[2, 9, 13]],
  traps: { "9": "m_odd_prime" },
  hint_after_wrong: { en: "Test 2, 3, 5 and 7 before you tap.", fr: "Teste 2, 3, 5 et 7." },
  points: { per_correct: 1 },
};

function renderGame(game: Minigame, onFinished = vi.fn(), bilingual = false) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <MinigameView game={game} target="en" home="fr" bilingual={bilingual} onFinished={onFinished} />
    </NextIntlClientProvider>,
  );
  return onFinished;
}

/** A game whose `active` flag the test can flip, as the lesson's tabs do. */
function renderSwitchableGame(game: Minigame, onFinished = vi.fn()) {
  const element = (active: boolean) => (
    <NextIntlClientProvider locale="en" messages={messages}>
      <MinigameView
        game={game}
        target="en"
        home="fr"
        bilingual={false}
        active={active}
        onFinished={onFinished}
      />
    </NextIntlClientProvider>
  );
  const view = render(element(true));
  return { onFinished, setActive: (active: boolean) => view.rerender(element(active)) };
}

/** The slot (0-based) the item with this label is shown in. */
function slotOf(label: string): number {
  const items = within(screen.getByRole("list")).getAllByRole("button");
  return items.findIndex((button) => button.textContent?.includes(label));
}

/**
 * Move the fake clock, one second at a time. The countdown schedules each
 * tick from an effect after the previous one renders, so React has to flush
 * between seconds — a single big jump would only fire the first tick.
 */
async function advance(ms: number) {
  for (let left = ms; left > 0; left -= 1000) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(Math.min(1000, left));
    });
  }
}

describe("MinigameView — catch engine (items rounds)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders items rounds instead of the 'unavailable' panel", () => {
    renderGame(catchGame);
    expect(screen.queryByText(/needs the .* engine/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(screen.getByText("When must you wash your hands?")).toBeInTheDocument();
    expect(screen.getByText("Round 1 / 2")).toBeInTheDocument();
    for (const label of ["Before touching a patient", "After touching a patient", "Only when they look dirty"]) {
      const button = screen.getByRole("button", { name: label });
      // Large touch targets (>= 44px): min-h-14 is 56px.
      expect(button.className).toMatch(/min-h-1[46]/);
    }
  });

  it("scores a right tap and shows the hint after a wrong one", () => {
    renderGame(catchGame);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    fireEvent.click(screen.getByRole("button", { name: "Only when they look dirty" }));
    expect(screen.getByText("Germs travel on hands that look clean too.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Only when they look dirty, not this one" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Before touching a patient" }));
    expect(screen.getByRole("button", { name: "Before touching a patient, caught" })).toBeDisabled();
  });

  it("advances once every right item is caught and reports the points once", async () => {
    const onFinished = renderGame(catchGame);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    fireEvent.click(screen.getByRole("button", { name: "Before touching a patient" }));
    fireEvent.click(screen.getByRole("button", { name: "Only when they look dirty" }));
    fireEvent.click(screen.getByRole("button", { name: "After touching a patient" }));
    await advance(600);

    expect(screen.getByText("Round 2 / 2")).toBeInTheDocument();
    expect(screen.getByText("What cleans best?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Soap and water" }));
    await advance(600);

    expect(screen.getByText("Game over — +3")).toBeInTheDocument();
    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(onFinished).toHaveBeenCalledWith({ gameId: "g1", points: 3 });

    // Later renders (a parent re-rendering with a new callback) never re-report.
    await advance(5000);
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("moves on when the round's timer runs out", async () => {
    const onFinished = renderGame(catchGame);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(screen.getByText("5s")).toBeInTheDocument();

    await advance(1000);
    expect(screen.getByText("4s")).toBeInTheDocument();
    await advance(4000);
    expect(screen.getByText("Round 2 / 2")).toBeInTheDocument();

    await advance(5000);
    expect(onFinished).toHaveBeenCalledWith({ gameId: "g1", points: 0 });
  });

  it("defaults to a 30 second round when timer_s is absent", () => {
    renderGame({ ...catchGame, timer_s: undefined });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(screen.getByText("30s")).toBeInTheDocument();
  });

  it("maps keys 1-6 onto the items as displayed", async () => {
    renderGame(catchGame);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    const items = within(screen.getByRole("list")).getAllByRole("button");
    const slot = items.findIndex((button) => button.textContent?.includes("Before touching a patient"));
    fireEvent.keyDown(window, { key: String(slot + 1) });

    expect(screen.getByRole("button", { name: "Before touching a patient, caught" })).toBeDisabled();
  });

  it("shows the home language beneath each item in bilingual mode", () => {
    renderGame(catchGame, vi.fn(), true);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(screen.getByText("Avant de toucher un patient")).toBeInTheDocument();
    expect(screen.getByText("Quand faut-il se laver les mains ?")).toBeInTheDocument();
  });

  it("counts a missing per_correct as 1, like the validator's max_points", async () => {
    const onFinished = renderGame({
      ...catchGame,
      points: undefined,
      rounds: [catchGame.rounds![1]],
    });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    fireEvent.click(screen.getByRole("button", { name: "Soap and water" }));
    await advance(600);
    expect(onFinished).toHaveBeenCalledWith({ gameId: "g1", points: 1 });
  });
});

describe("MinigameView — pop engine (rule rounds)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("still plays a list round with a known rule", async () => {
    const onFinished = renderGame(popGame);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    fireEvent.click(screen.getByRole("button", { name: "9" }));
    expect(screen.getByText("Test 2, 3, 5 and 7 before you tap.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "2" }));
    fireEvent.click(screen.getByRole("button", { name: "13" }));
    expect(screen.getByRole("button", { name: "13, popped" })).toBeDisabled();
    await advance(600);

    expect(onFinished).toHaveBeenCalledWith({ gameId: "g_pop", points: 2 });
  });

  it("keeps the authored order of list rounds", () => {
    expect(playableRounds(popGame)[0].items.map((item) => item.label)).toEqual(["2", "9", "13"]);
  });

  it("says so when no round can be played", () => {
    const onFinished = renderGame({ ...popGame, rule: { fn: "is_square" } });
    expect(screen.getByText(/needs the is_square engine/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(onFinished).toHaveBeenCalledWith({ gameId: "g_pop", points: 0 });
  });
});

describe("MinigameView — keys and visibility", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("ignores digits typed into a text field elsewhere on the page", () => {
    renderGame(catchGame);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    const slot = slotOf("Before touching a patient");

    // The AI tutor's chat box, say.
    const chat = document.createElement("textarea");
    document.body.appendChild(chat);
    fireEvent.keyDown(chat, { key: String(slot + 1) });
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: String(slot + 1) });
    const editor = document.createElement("div");
    editor.setAttribute("contenteditable", "true");
    document.body.appendChild(editor);
    fireEvent.keyDown(editor, { key: String(slot + 1) });

    expect(screen.getByRole("button", { name: "Before touching a patient" })).toBeEnabled();
    chat.remove();
    input.remove();
    editor.remove();
  });

  it("ignores shortcuts and IME composition", () => {
    renderGame(catchGame);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    const key = String(slotOf("Before touching a patient") + 1);

    fireEvent.keyDown(window, { key, ctrlKey: true });
    fireEvent.keyDown(window, { key, metaKey: true });
    fireEvent.keyDown(window, { key, altKey: true });
    fireEvent.keyDown(window, { key, isComposing: true });
    expect(screen.getByRole("button", { name: "Before touching a patient" })).toBeEnabled();

    // A plain press still plays.
    fireEvent.keyDown(window, { key });
    expect(screen.getByRole("button", { name: "Before touching a patient, caught" })).toBeDisabled();
  });

  it("pauses the countdown and the keys while out of sight", async () => {
    const { onFinished, setActive } = renderSwitchableGame(catchGame);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await advance(2000);
    expect(screen.getByText("3s")).toBeInTheDocument();

    // The learner switches to another lesson tab for a while.
    setActive(false);
    await advance(30_000);
    expect(screen.getByText("3s")).toBeInTheDocument();
    expect(screen.getByText("Round 1 / 2")).toBeInTheDocument();
    expect(onFinished).not.toHaveBeenCalled();
    const key = String(slotOf("Before touching a patient") + 1);
    fireEvent.keyDown(window, { key });
    expect(screen.getByRole("button", { name: "Before touching a patient" })).toBeEnabled();

    // Back on the Story tab: the clock and the keys pick up where they were.
    setActive(true);
    fireEvent.keyDown(window, { key });
    expect(screen.getByRole("button", { name: "Before touching a patient, caught" })).toBeDisabled();
    await advance(1000);
    expect(screen.getByText("2s")).toBeInTheDocument();
  });
});
