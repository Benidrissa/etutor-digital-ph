/**
 * Test helpers for the story player. A card that asks something of the
 * learner (a question, a game, a paper exercise) ignores taps for a moment
 * after it appears, so the tap that brought it up cannot answer it; tests
 * wait for it to be ready before they click inside it.
 */

import { screen, waitFor } from "@testing-library/react";
import type userEvent from "@testing-library/user-event";

/** Waits until the step's card takes clicks. */
export async function cardReady(): Promise<void> {
  await waitFor(
    () => {
      const card = document.querySelector("[data-armed]");
      if (card && card.getAttribute("data-armed") !== "true") throw new Error("card not ready");
    },
    { timeout: 3000 },
  );
}

/** Clicks the button named `name` inside the step's card, once the card is ready. */
export async function clickInCard(
  user: ReturnType<typeof userEvent.setup>,
  name: string | RegExp,
): Promise<void> {
  await cardReady();
  await user.click(screen.getByRole("button", { name }));
}
