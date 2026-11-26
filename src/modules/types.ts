export type Site = 'chatgpt' | 'claude' | 'gemini';

export interface Message {
  role: string;
  content: string;
}

export interface ChatMeta {
  site: Site;
  title: string;
  url: string;
  exportedAt: string;
}

export interface ChatContent {
  format: string;
  content: string;
  messageCount: number;
  failedMessages: number;
  messages: Array<Message>;
  meta: ChatMeta;
}
