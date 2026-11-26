// Prompt archive: capture every prompt the moment it is sent, with no button press.
//
// Listens (capture phase, before the site's own handlers clear the box) for:
//   * Enter in the chat composer (ChatGPT, Claude) or Ctrl/Cmd+Enter (all sites, AI Studio's "Run")
//   * a click on the site's Send / Run button
// and forwards the composer text to the background script, which hands it to the local
// native messaging host. Nothing leaves this computer.
import browser from 'webextension-polyfill';

import { detectSite } from './site-detection';
import { Site } from './types';

// gemini.google.com is capture-only: the original export code supports AI Studio, not the Gemini app
export type CaptureSite = Site | 'geminiapp';

function detectCaptureSite(): CaptureSite {
  if (location.hostname === 'gemini.google.com') return 'geminiapp';
  return detectSite();
}

const COMPOSER_SELECTOR = [
  '#prompt-textarea', // ChatGPT
  'div.ProseMirror[contenteditable="true"]', // ChatGPT / Claude (ProseMirror editors)
  '[data-testid="chat-input"]', // Claude
  'ms-prompt-input-wrapper textarea', // AI Studio
  'ms-chunk-input textarea', // AI Studio
  'ms-autosize-textarea textarea', // AI Studio
  'rich-textarea .ql-editor[contenteditable="true"]', // Gemini app
  '.ql-editor[contenteditable="true"]', // Gemini app
].join(', ');

const SEND_BUTTON_SELECTOR = [
  'button[data-testid="send-button"]', // ChatGPT
  'button[data-testid="composer-submit-button"]', // ChatGPT
  'button[aria-label="Send message"]', // Claude
  'button[aria-label="Send prompt"]', // ChatGPT (older)
  'button[aria-label="Send"]',
  'ms-run-button button', // AI Studio
  'button[aria-label="Run"]', // AI Studio
  'button.send-button', // Gemini app
].join(', ');

export const SITE_LABEL: Record<CaptureSite, string> = {
  chatgpt: 'ChatGPT',
  claude: 'Claude.ai',
  gemini: 'Google AI Studio',
  geminiapp: 'Gemini',
};

/** Conversation id from the URL, or null for a chat that has not been created yet. */
export function conversationId(site: CaptureSite, url: string = location.href): string | null {
  const path = new URL(url).pathname;
  const patterns: Record<CaptureSite, RegExp> = {
    chatgpt: /\/c\/([\w-]+)/,
    claude: /\/chat\/([\w-]+)/,
    gemini: /\/prompts\/(?!new_chat)([\w-]+)/,
    geminiapp: /\/(?:app|gem\/[\w-]+)\/([\w-]+)/,
  };
  return patterns[site].exec(path)?.[1] ?? null;
}

export function chatTitle(): string {
  // Gemini app: the open chat is highlighted in the sidebar; document.title is just "Gemini"
  if (location.hostname === 'gemini.google.com') {
    const selected = document.querySelector(
      '.conversation.selected .conversation-title, [data-test-id="conversation"].selected .conversation-title'
    );
    const t = selected?.textContent?.trim();
    if (t) return t;
  }
  return document.title
    .replace(/\s*[-|–]\s*(Claude|ChatGPT|Google AI Studio|Google Gemini|Gemini)\s*$/i, '')
    .trim();
}

function findComposer(from?: Element | null): HTMLElement | null {
  const own = from?.closest?.(COMPOSER_SELECTOR) as HTMLElement | null;
  if (own) return own;
  return document.querySelector(COMPOSER_SELECTOR) as HTMLElement | null;
}

function readComposer(el: HTMLElement): string {
  const text = el instanceof HTMLTextAreaElement ? el.value : el.innerText;
  return (text || '').replace(/\u00a0/g, ' ').trim();
}

function send(message: Record<string, unknown>) {
  browser.runtime.sendMessage(message).catch(() => {
    /* host not installed or extension reloading: nothing to do */
  });
}

export function initAutoCapture() {
  let site: CaptureSite;
  try {
    site = detectCaptureSite();
  } catch {
    return;
  }
  // A chat that has no URL id yet (brand new) gets a temporary id until the site assigns one.
  const pageSession = `new-${Date.now().toString(36)}`;
  let last = { text: '', at: 0 };

  const capture = (composer: HTMLElement | null) => {
    if (!composer) return;
    const text = readComposer(composer);
    if (!text) return;
    const now = Date.now();
    if (text === last.text && now - last.at < 3000) return; // Enter + click for one send
    last = { text, at: now };

    const ts = new Date(now).toISOString();
    const startId = conversationId(site);
    const dispatch = (conv: string) =>
      send({
        type: 'ARCHIVE_PROMPT',
        site,
        project: SITE_LABEL[site],
        origin: location.origin,
        conv,
        url: location.href,
        title: chatTitle(),
        text,
        ts,
      });

    if (startId) {
      dispatch(startId);
    } else {
      // New chat: wait (up to 20 s) for the site to put the conversation id in the URL.
      let tries = 0;
      const timer = window.setInterval(() => {
        const id = conversationId(site);
        if (id || ++tries >= 40) {
          window.clearInterval(timer);
          dispatch(id ?? pageSession);
        }
      }, 500);
    }

    // Titles are usually generated after the first reply; report the final one later.
    window.setTimeout(() => {
      const conv = conversationId(site);
      if (conv) {
        send({ type: 'ARCHIVE_TITLE', site, conv, title: chatTitle(), url: location.href });
      }
    }, 30000);
  };

  window.addEventListener(
    'keydown',
    (event) => {
      if (event.key !== 'Enter' || event.isComposing || event.shiftKey || event.altKey) return;
      const target = event.target as Element | null;
      if (!target?.closest?.(COMPOSER_SELECTOR)) return;
      const modifier = event.ctrlKey || event.metaKey;
      if (site === 'gemini' && !modifier) return; // AI Studio: Enter is a newline, Ctrl+Enter runs
      capture(findComposer(target));
    },
    true
  );

  window.addEventListener(
    'click',
    (event) => {
      const button = (event.target as Element | null)?.closest?.(SEND_BUTTON_SELECTOR);
      if (!button || (button as HTMLButtonElement).disabled) return;
      capture(findComposer(button.closest('form') ?? null));
    },
    true
  );
}
