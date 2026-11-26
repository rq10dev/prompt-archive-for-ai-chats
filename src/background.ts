// Prompt archive: relays prompts captured by the content script to the local native
// messaging host (com.prompt_archive.host), which appends them to ~/prompt_archive.
// Nothing is sent anywhere else: native messaging only talks to a program on this PC.
import browser from 'webextension-polyfill';

const HOST = 'com.prompt_archive.host';

browser.runtime.onMessage.addListener((message: unknown) => {
  if (!message || typeof message !== 'object' || !('type' in message)) return undefined;
  const type = (message as { type: string }).type;
  if (type !== 'ARCHIVE_PROMPT' && type !== 'ARCHIVE_EXPORT' && type !== 'ARCHIVE_TITLE') {
    return undefined;
  }
  return browser.runtime
    .sendNativeMessage(HOST, message)
    .then((reply) => ({ ok: true, reply }))
    .catch((error: Error) => {
      console.warn('[prompt-archive] host unreachable:', error.message);
      return { ok: false, error: error.message };
    });
});
