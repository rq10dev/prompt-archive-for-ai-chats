import browser from 'webextension-polyfill';

import { SITE_LABEL, conversationId } from '@/modules/auto-capture';
import { getChatContent } from '@/modules/chat-content';
import { ChatContent } from '@/modules/types';

// prompt archive: file the exported chat's prompts in ~/prompt_archive as well
export function archiveExport({ messages, meta }: ChatContent) {
  const prompts = messages.filter((m) => m.role !== 'assistant').map((m) => m.content);
  if (!prompts.length) return;
  browser.runtime
    .sendMessage({
      type: 'ARCHIVE_EXPORT',
      site: meta.site,
      project: SITE_LABEL[meta.site],
      origin: window.location.origin,
      conv: conversationId(meta.site) ?? `export-${meta.exportedAt}`,
      url: meta.url,
      title: meta.title,
      exportedAt: meta.exportedAt,
      prompts,
    })
    .catch(() => {
      /* host not installed: the downloaded file is still saved */
    });
}

function downloadFile(content: string, format: string, site = 'chat'): string {
  const mimeTypes: { [key: string]: string } = {
    markdown: 'text/markdown',
    json: 'application/json',
    xml: 'application/xml',
    html: 'text/html',
  };

  const extensions: { [key: string]: string } = {
    markdown: 'md',
    json: 'json',
    xml: 'xml',
    html: 'html',
  };

  const blob = new Blob([content], { type: mimeTypes[format] || 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  a.download = `chat-export-${site}-${stamp}.${extensions[format] || 'txt'}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  return a.download;
}

export async function copyToClipboard() {
  const chat = await getChatContent(false);
  const { format, content, messageCount, failedMessages } = chat;
  archiveExport(chat);

  const failedText = failedMessages > 0 ? `\n⚠️ Failed messages: ${failedMessages}` : '';
  const stats = `Stats:\n📝 Total messages: ${messageCount}\n📏 Total length: ${content.length.toLocaleString()} characters${failedText}`;
  try {
    await navigator.clipboard.writeText(content);
  } catch {
    // Clipboard needs a focused page; a long export easily outlives focus.
    // Fall back to a download so the extracted content is never lost.
    const filename = downloadFile(content, format, chat.meta.site);
    alert(
      `⚠️ Clipboard unavailable (page lost focus?) — saved to file instead.\n\n${stats}\n📁 Filename: ${filename}`
    );
    return;
  }
  alert(`✅ Chat copied to clipboard successfully!\n\n${stats}`);
}

export async function saveToFile() {
  const chat = await getChatContent(true);
  const { format, content, messageCount, failedMessages } = chat;
  archiveExport(chat);
  const filename = downloadFile(content, format, chat.meta.site);

  const failedText = failedMessages > 0 ? `\n⚠️ Failed messages: ${failedMessages}` : '';
  alert(
    `💾 Chat saved to file successfully!\n\nStats:\n📝 Total messages: ${messageCount}\n📏 Total length: ${content.length.toLocaleString()} characters\n📄 Format: ${format.toUpperCase()}\n📁 Filename: ${filename}${failedText}`
  );
}
