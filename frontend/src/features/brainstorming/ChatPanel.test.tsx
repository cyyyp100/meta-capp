import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLangStore } from "../../i18n";
import { ChatPanel } from "./ChatPanel";

vi.mock("../../api/client", () => ({
  api: {
    discussionMessages: vi.fn(async () => ({ messages: [], answering: false })),
  },
}));

vi.mock("./FolderScopePicker", () => ({ FolderScopePicker: () => null }));

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", class {
      static OPEN = 1;
      readyState = 1;
      onmessage = null;
      onclose = null;
      send = vi.fn();
      close = vi.fn();
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ["fr", "Envoyer"],
    ["en", "Send"],
  ] as const)("names the send button in %s for assistive technology", async (lang, name) => {
    useLangStore.setState({ lang });
    await act(async () => {
      render(<ChatPanel discussionId={1} onFolderChange={vi.fn()} />);
    });

    const button = screen.getByRole("button", { name });
    expect(button).toHaveAccessibleName(name);
    expect(button).toHaveTextContent("↵");
    expect(screen.getByText("↵")).toHaveAttribute("aria-hidden", "true");
  });
});
