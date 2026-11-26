# Prompt Archive for AI Chats

**Developed by Rahil Qureshi** · Based on [Chat Export](https://github.com/Trifall/chat-export) by Trifall (MIT License)

A browser extension for Microsoft Edge and Google Chrome on Windows that **automatically saves every prompt you send** on ChatGPT, Claude.ai, Gemini and Google AI Studio into tidy Markdown files on your own PC, one file per site per month. It can also export whole chats to Markdown, JSON, XML or HTML.

```
%USERPROFILE%\prompt_archive\
├── index.md                       ← every site/project, with a table of months
└── projects\
    ├── ChatGPT\2026-11.md
    ├── Claude.ai\2026-11.md
    ├── Gemini\2026-10.md
    └── Google AI Studio\2026-11.md
```

Each month file lists your chats (with title and link) and every prompt with the date and time you sent it.

## Privacy

- Your prompts **never leave your computer**. The extension hands each prompt to a small helper program on your PC (browser "native messaging"), which writes it into `%USERPROFILE%\prompt_archive`. There are no servers, accounts, analytics or network requests.
- The extension only runs on `chatgpt.com`, `chat.openai.com`, `claude.ai`, `gemini.google.com` and `aistudio.google.com`.
- Only the prompts **you** send are archived automatically, not the AI's replies (use **Export** for whole chats).
- The source code of the extension and the helper is in this repository.

## Requirements

- Windows 10 or 11
- Microsoft Edge or Google Chrome
- [Python 3.8 or newer](https://www.python.org/downloads/) (tick "Add python.exe to PATH" when installing)

## Install

1. Download `PromptArchive-<version>.zip` from the [Releases](../../releases) page and **extract** it.
2. Double-click **`install.cmd`**. It finds Python, copies the files to `%LOCALAPPDATA%\PromptArchive`, and registers the helper with Edge and Chrome for your user account (no admin rights needed).
3. Load the extension:
   1. Open `edge://extensions` (or `chrome://extensions`).
   2. Turn on **Developer mode**.
   3. Click **Load unpacked** and select `%LOCALAPPDATA%\PromptArchive\extension` (the installer prints the full path).
4. Reload any open ChatGPT / Claude.ai / Gemini / AI Studio tabs and send a prompt. It appears in `%USERPROFILE%\prompt_archive\projects\<site>\<year>-<month>.md` within a few seconds.

## Using it

| You do | What is archived |
|---|---|
| Send a prompt (Enter, Send, or Ctrl+Enter / Run in AI Studio) | The prompt, with the time you sent it, the chat title and its link |
| Click **Export** next to the chat's Share button (ChatGPT, Claude.ai, AI Studio), or use the toolbar popup | A file in your Downloads, **and** any earlier prompts of that chat that are not in the archive yet, marked *(from export)* |

Prompts you already archived are never duplicated.

### Import your older Gemini history (Google Takeout)

Gemini's own page has no Export button, but Google Takeout has your full history:

1. Go to [takeout.google.com](https://takeout.google.com) → **Deselect all** → tick **My Activity**.
2. **All activity data included** → select only **Gemini Apps**.
3. **Multiple formats** → set **Activity records** to **JSON** (the default HTML cannot be imported).
4. Download the zip and run:
   ```
   python "%LOCALAPPDATA%\PromptArchive\export_prompt_history.py" --takeout "C:\path\to\takeout-....zip"
   ```

Takeout does not say which chat a prompt was in, so imported prompts are grouped by day.

### Claude Code users

If you use [Claude Code](https://claude.com/claude-code), its prompts can go in the same archive (one project per folder you worked in). Run:

```
python "%LOCALAPPDATA%\PromptArchive\export_prompt_history.py"
```

Run it again any time; everything it finds is kept even after Claude Code cleans up old sessions.

## Settings

`%USERPROFILE%\prompt_archive\config.json` is created on first run:

```json
{
  "index_file": "index.md",
  "browser_label": "this computer (browser)",
  "claude_code_sources": [{"path": "~/.claude", "label": "this computer"}],
  "merge": {}
}
```

- **claude_code_sources**: extra Claude Code data folders to read, e.g. an old PC's drive: `{"path": "D:\\Users\\OldName\\.claude", "label": "old laptop"}`.
- **merge**: file one project folder under another, e.g. the same project on an old PC: `{"C:\\Users\\OldName\\Projects\\App": "C:\\Users\\NewName\\Projects\\App"}`.

Do not delete `prompt_archive\.prompt_store.json`: it holds every prompt ever archived, and the Markdown files are rebuilt from it.

## Limitations

- Prompts that are only an image or file (no text) are not captured. Large pastes that a site turns into an attachment keep only the text you typed.
- Editing an earlier message may not be captured on some sites.
- The extension finds each site's message box and Send button by the page structure; when a site redesigns its page, capture can stop until the extension is updated. Errors are written to `prompt_archive\errors.log`.
- Windows only (the installer and helper registration are Windows-specific).

## Uninstall

Double-click **`uninstall.cmd`** (from the release zip), then remove the extension in `edge://extensions`. Your archive folder is kept.

## Build from source

```
npm ci
npm run build          # builds the extension into dist/
npm run package        # builds and creates release/PromptArchive-<version>.zip
```

Load `dist/` with **Load unpacked** while developing. The extension ID is fixed by the `key` in `src/manifest.json`, so the helper's registration keeps working across rebuilds.

## Credits and license

- **Rahil Qureshi**: Prompt Archive (automatic prompt capture, local archive helper, monthly Markdown archive, Gemini and Google Takeout support, export metadata, installer).
- **Trifall**: the original [Chat Export](https://github.com/Trifall/chat-export) extension (chat export to Markdown/JSON/XML/HTML for ChatGPT, Claude and AI Studio), on which this is built.

Released under the [MIT License](LICENSE).
