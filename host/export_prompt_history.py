"""Prompt Archive for AI Chats - archive every prompt you send to AI, one Markdown file per
project (or chat site) per month.

Part of "Prompt Archive for AI Chats" by Rahil Qureshi (MIT License).
The browser extension is based on Chat Export by Trifall: https://github.com/Trifall/chat-export

Sources (each is skipped if missing):
  * Browser chats: prompts captured by the extension (ChatGPT, Claude.ai, Gemini, AI Studio),
    queued in ~/prompt_archive/.ai_chat_inbox.jsonl by ai_chat_host.py
  * Claude Code (if installed): <claude dir>/projects/**/*.jsonl transcripts and
    <claude dir>/history.jsonl. Only genuine user prompts are kept.
  * Google Takeout (on request): Gemini Apps activity, via --takeout PATH

Every prompt found is merged into ~/prompt_archive/.prompt_store.json, which only ever grows.
The Markdown is rebuilt from that store, so prompts survive Claude Code's transcript cleanup
and unplugged drives. Do not delete the store.

Settings: ~/prompt_archive/config.json (created with defaults on first run). See README.

Output:
  ~/prompt_archive/<index_file>                          index of projects and months
  ~/prompt_archive/projects/<project>/<YYYY-MM>.md       prompts, grouped by session, local time

Usage:
  python export_prompt_history.py                  full update (Claude Code + browser inbox)
  python export_prompt_history.py --no-scan        browser inbox only (fast)
  python export_prompt_history.py --takeout ZIP    also import a Google Takeout (Gemini, JSON format)
"""
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import msvcrt
except ImportError:  # not Windows
    msvcrt = None
    import fcntl

HOME = Path.home()
ARCHIVE = Path(os.environ.get("PROMPT_ARCHIVE_DIR", HOME / "prompt_archive"))
CONFIG = ARCHIVE / "config.json"
PROJECT_DIR = ARCHIVE / "projects"  # projects/<project>/<YYYY-MM>.md
STORE = ARCHIVE / ".prompt_store.json"  # every prompt ever extracted; only grows
INBOX = ARCHIVE / ".ai_chat_inbox.jsonl"  # browser prompts, appended by ai_chat_host.py
LOCK = ARCHIVE / ".archive.lock"  # one archive update at a time
INBOX_LOCK = ARCHIVE / ".inbox.lock"

DEFAULT_CONFIG = {
    "index_file": "index.md",
    "browser_label": "this computer (browser)",
    # Claude Code data folders to read (missing ones are skipped), with the label shown in the archive
    "claude_code_sources": [{"path": "~/.claude", "label": "this computer"}],
    # Treat sessions started in the left-hand folder as part of the right-hand project
    # (the same project at different paths, e.g. on an old computer).
    "merge": {},
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG.is_file():
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    else:
        try:
            ARCHIVE.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        except OSError:
            pass
    return cfg


_CFG = load_config()
OUT = ARCHIVE / _CFG["index_file"]  # index of all projects
WEB_MACHINE = _CFG["browser_label"]
SOURCES = [(Path(os.path.expanduser(s["path"])), s.get("label") or s["path"]) for s in _CFG["claude_code_sources"]]
MERGE = dict(_CFG["merge"])
_MERGE = {k.lower(): v for k, v in MERGE.items()}

SKIP_PREFIXES = (
    "<task-notification>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<local-command-caveat>",
    "[Request interrupted by user",
)


@contextmanager
def file_lock(path, timeout=60):
    """Cross-process lock on `path` (waits up to `timeout` seconds)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    deadline = time.time() + timeout
    while True:
        try:
            fh.seek(0)
            if msvcrt:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() > deadline:
                fh.close()
                raise TimeoutError(f"{path} is locked by another archive update")
            time.sleep(0.1)
    try:
        yield
    finally:
        fh.seek(0)
        if msvcrt:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def safe_filename(name):
    """Make a Windows-safe file name from a project folder name."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "project"


# ---------------------------------------------------------------- transcripts


def text_of(content):
    """Return the text of a message content, or None if it is a tool result."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return None


def slash_command(text):
    """Render '<command-name>/x</command-name>...<command-args>y</command-args>' as '/x y'."""
    name = re.search(r"<command-name>(.*?)</command-name>", text, re.S)
    if not name:
        return None
    args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
    cmd = name.group(1).strip()
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    a = args.group(1).strip() if args else ""
    return f"{cmd} {a}".strip()


def extract(rec):
    """Return (prompt_text, kind) for a genuine user prompt in a transcript record, else None."""
    if rec.get("type") != "user":
        return None
    if rec.get("isMeta") or rec.get("isSidechain") or rec.get("isCompactSummary") or rec.get("isVisibleInTranscriptOnly"):
        return None
    text = text_of((rec.get("message") or {}).get("content"))
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None

    origin = (rec.get("origin") or {}).get("kind")
    if "<command-name>" in text:
        cmd = slash_command(text)
        return (cmd, "slash command") if cmd else None
    bash = re.fullmatch(r"<bash-input>(.*)</bash-input>", text, re.S)
    if bash:
        return f"! {bash.group(1).strip()}", "shell command"
    if origin and origin != "human":
        return None
    if text.startswith(SKIP_PREFIXES):
        return None
    if not origin and text.startswith("<"):
        return None  # older records without origin: drop harness-tagged messages
    source = rec.get("promptSource")
    kind = {"suggestion_accepted": "accepted suggestion", "queued": "queued"}.get(source, "")
    return text, kind


def collect_transcripts(base, machine, store):
    files = [f for f in sorted((base / "projects").rglob("*.jsonl")) if "subagents" not in f.parts]
    found = 0
    for f in files:
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                got = extract(rec)
                if not got or not rec.get("timestamp"):
                    continue
                sid = rec.get("sessionId") or f.stem
                rid = "t:" + (rec.get("uuid") or f"{sid}:{rec['timestamp']}")
                store[rid] = {
                    "sid": sid,
                    "ts": rec["timestamp"],
                    "text": got[0],
                    "kind": got[1],
                    "cwd": rec.get("cwd") or "",
                    "source": "transcript",
                    "machine": machine,
                }
                found += 1
    return len(files), found


# ---------------------------------------------------------------- history.jsonl


def expand_pastes(display, pasted, base):
    """Replace '[Pasted text #N +X lines]' placeholders with the pasted text, when it is still stored."""
    pasted = pasted or {}

    def rep(m):
        p = pasted.get(m.group(1)) or pasted.get(int(m.group(1)))
        if not isinstance(p, dict) or p.get("type") != "text":
            return m.group(0)
        content = p.get("content")
        if content is None and p.get("contentHash"):
            cache = base / "paste-cache" / f"{p['contentHash']}.txt"
            if cache.is_file():
                content = cache.read_text(encoding="utf-8", errors="replace")
        return content if content is not None else m.group(0)[:-1] + " - pasted content no longer stored]"

    return re.sub(r"\[Pasted text #(\d+)[^\]]*\]", rep, display)


def collect_history(base, machine, store):
    path = base / "history.jsonl"
    if not path.is_file():
        return 0
    found = 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = (e.get("display") or "").strip()
            ts = e.get("timestamp")
            if not text or not isinstance(ts, (int, float)):
                continue
            text = expand_pastes(text, e.get("pastedContents"), base).strip()
            kind = "slash command" if text.startswith("/") else ("shell command" if text.startswith("!") else "")
            sid = e.get("sessionId") or f"history-{e.get('project', '')}"
            iso = datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            store[f"h:{machine}:{sid}:{ts}"] = {
                "sid": sid,
                "ts": iso,
                "text": text,
                "kind": kind,
                "cwd": e.get("project") or "",
                "source": "history",
                "machine": machine,
            }
            found += 1
    return found


# ---------------------------------------------------------------- browser chats (inbox)


def append_inbox(message):
    """Called by ai_chat_host.py: queue one message from the browser extension."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    line = json.dumps(message, ensure_ascii=False) + "\n"
    with file_lock(INBOX_LOCK, timeout=20):
        with INBOX.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)


def collect_inbox(store):
    """Turn queued browser messages into store records. Safe to repeat: ids are stable."""
    if not INBOX.is_file():
        return 0
    with file_lock(INBOX_LOCK, timeout=20):
        lines = INBOX.read_text(encoding="utf-8", errors="replace").splitlines()
    found = 0
    for line in lines:
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        site, conv = str(m.get("site", "web")), str(m.get("conv", "unknown"))
        sid = f"{site}:{conv}"
        common = {
            "sid": sid,
            "cwd": m.get("origin") or site,
            "project": m.get("project") or site,
            "title": (m.get("title") or "").strip(),
            "url": m.get("url") or "",
            "machine": WEB_MACHINE,
        }
        t = m.get("type")
        if t == "ARCHIVE_PROMPT" and (m.get("text") or "").strip() and m.get("ts"):
            store[f"w:{sid}:{m['ts']}"] = {
                **common, "ts": m["ts"], "text": m["text"].strip(), "kind": "", "source": "web-live"
            }
            found += 1
        elif t == "ARCHIVE_EXPORT" and m.get("exportedAt"):
            base = datetime.fromisoformat(m["exportedAt"].replace("Z", "+00:00"))
            for i, text in enumerate(m.get("prompts") or []):
                text = (text or "").strip()
                if not text:
                    continue
                rid = f"x:{sid}:{i}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]}"
                if rid in store:
                    continue  # keep the first export's time for prompts already archived
                ts = (base + timedelta(milliseconds=i)).isoformat().replace("+00:00", "Z")
                store[rid] = {**common, "ts": ts, "text": text, "kind": "from export", "source": "web-export"}
                found += 1
        elif t == "ARCHIVE_TITLE" and (m.get("title") or "").strip():
            store[f"title:{sid}"] = {**common, "source": "title", "ts": "", "text": "", "kind": ""}
    return found


# ---------------------------------------------------------------- Google Takeout (Gemini Apps)

GEMINI_ORIGIN = "https://gemini.google.com"
TAKEOUT_MACHINE = "Google account (Takeout)"


def _takeout_files(path):
    """Yield (name, bytes) for every MyActivity.json/.html inside a Takeout zip, folder or file."""
    import zipfile

    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if Path(n).name.lower() in ("myactivity.json", "myactivity.html"):
                    yield n, z.read(n)
    elif path.is_dir():
        for f in path.rglob("*"):
            if f.name.lower() in ("myactivity.json", "myactivity.html") or (f.suffix.lower() == ".zip"):
                yield from (_takeout_files(f) if f.suffix.lower() == ".zip" else [(str(f), f.read_bytes())])
    elif path.is_file():
        yield str(path), path.read_bytes()


def collect_takeout(path, store):
    """Import 'Prompted ...' entries from Google Takeout > My Activity > Gemini Apps (JSON format)."""
    found, html_only, files = 0, False, 0
    for name, data in _takeout_files(path):
        if name.lower().endswith(".html"):
            html_only = html_only or "gemini" in name.lower()
            continue
        try:
            entries = json.loads(data.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(entries, list):
            continue
        gemini = [
            e for e in entries
            if isinstance(e, dict)
            and ("Gemini" in (e.get("header") or "") or any("Gemini" in p for p in e.get("products") or []))
        ]
        if not gemini:
            continue
        files += 1
        for e in gemini:
            title, ts = e.get("title") or "", e.get("time") or ""
            if not title.startswith("Prompted ") or not ts:
                continue  # feedback, settings changes, canvas actions, ...
            text = title[len("Prompted "):].strip()
            if not text:
                continue
            day = f"{local_time(ts):%Y-%m-%d}"
            store[f"g:{ts}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]}"] = {
                "sid": f"geminiapp:takeout-{day}",
                "ts": ts,
                "text": text,
                "kind": "",
                "cwd": GEMINI_ORIGIN,
                "project": "Gemini",
                "title": f"Gemini activity on {day} (Takeout)",
                "url": "",
                "source": "web-takeout",
                "machine": TAKEOUT_MACHINE,
            }
            found += 1
    if not files and html_only:
        raise SystemExit(
            "This Takeout has Gemini activity only as HTML. Export it again with "
            "My Activity > 'Multiple formats' > Activity records: JSON, then re-run."
        )
    if not files:
        raise SystemExit(f"No Gemini Apps activity (MyActivity.json) found in {path}")
    return found


# ---------------------------------------------------------------- store + render


def load_store():
    if STORE.is_file():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {}


def save_store(store):
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=0), encoding="utf-8")
    os.replace(tmp, STORE)


def local_time(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()


_TITLE_SUFFIX = re.compile(r"\s*[-|–]\s*(Claude|ChatGPT|Google AI Studio|Google Gemini|Gemini)\s*$", re.I)


def _clean_title(title):
    """Drop a trailing ' - Google Gemini' / ' | ChatGPT' style site name from a page title."""
    return _TITLE_SUFFIX.sub("", title or "").strip()


_GENERIC_TITLES = {"", "chatgpt", "claude", "google ai studio", "new chat", "gemini", "google gemini"}


def _norm(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def build_sessions(store):
    """Return ({(machine, sid): [prompt, ...]}, {sid: title}).

    Transcript prompts win over history.jsonl for the same session; live-captured browser
    prompts win over the same prompt found again in a later export of that chat.
    """
    raw = defaultdict(list)
    titles = {}
    for r in store.values():
        if r["source"] == "title":
            t = _clean_title(r["title"])
            if t.lower() not in _GENERIC_TITLES:
                titles[r["sid"]] = t
            continue
        raw[(r["machine"], r["sid"])].append(r)
    sessions = {}
    for key, recs in list(raw.items()):
        if any(r["source"] == "transcript" for r in recs):
            recs = [r for r in recs if r["source"] == "transcript"]
        live = {_norm(r["text"]) for r in recs if r["source"] == "web-live"}
        if live:
            recs = [r for r in recs if not (r["source"] == "web-export" and _norm(r["text"]) in live)]
        if recs:
            raw[key] = recs
        else:
            del raw[key]
    # Takeout has no chat ids: drop a Takeout prompt when the extension already captured the
    # same text within 15 minutes of it.
    live_at = defaultdict(list)
    for recs in raw.values():
        for r in recs:
            if r["source"] == "web-live":
                live_at[_norm(r["text"])].append(local_time(r["ts"]))
    for key, recs in list(raw.items()):
        if any(r["source"] == "web-takeout" for r in recs):
            recs = [
                r for r in recs
                if not (r["source"] == "web-takeout" and any(
                    abs((local_time(r["ts"]) - t).total_seconds()) <= 900 for t in live_at.get(_norm(r["text"]), [])
                ))
            ]
            if not recs:
                del raw[key]
                continue
            raw[key] = recs
    for key, recs in raw.items():
        prompts = sorted(
            ({**r, "dt": local_time(r["ts"])} for r in recs), key=lambda r: r["dt"]
        )
        sessions[key] = prompts
        for r in reversed(prompts):  # latest non-generic title seen in the prompts
            t = _clean_title(r.get("title"))
            if t.lower() not in _GENERIC_TITLES:
                titles.setdefault(key[1], t)
                break
    return sessions, titles


def render(store):
    sessions, titles = build_sessions(store)
    generated = f"{datetime.now().astimezone():%Y-%m-%d %H:%M %Z}"

    # A session belongs to the directory it started in, even if `cd` moved it later.
    # Folders listed in MERGE are filed under their target project.
    projects = defaultdict(dict)  # project folder (lower) -> {sid: prompts}
    proj_cwd = {}
    proj_origins = defaultdict(set)  # project -> {(original folder, machine)}
    session_origin = {}  # sid -> (original folder, machine)
    for (machine, sid), prompts in sessions.items():
        cwd0 = prompts[0]["cwd"]
        target = _MERGE.get(cwd0.lower(), cwd0)
        pkey = target.lower()
        proj_cwd.setdefault(pkey, target)
        proj_origins[pkey].add((cwd0, machine))
        session_origin[sid] = (cwd0, machine)
        for p in prompts:
            p["moved"] = "" if p["cwd"].lower() == cwd0.lower() else p["cwd"]
        projects[pkey][sid] = prompts

    def first(ss):
        return min(p[0]["dt"] for p in ss.values())

    ordered = sorted(projects.items(), key=lambda kv: first(kv[1]))
    total_prompts = sum(len(p) for p in sessions.values())

    # projects/ is owned by this script and rebuilt from the store every run. Files are rewritten
    # in place only when their content changes; files no longer produced are removed at the end.
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    written = set()

    def write(path, content):
        written.add(path.resolve())
        if not path.is_file() or path.read_text(encoding="utf-8", errors="replace") != content:
            path.write_text(content, encoding="utf-8")

    index = [
        "# AI Prompt History",
        "",
        f"Generated: {generated}  ",
        f"Prompts: **{total_prompts}** across **{len(sessions)}** sessions in **{len(projects)}** projects  ",
        "Claude Code projects and browser AI chats. Each has a folder in `projects/` with one file per month. "
        "Times are local.",
        "",
    ]
    used, report = set(), []
    for pkey, ss in ordered:
        cwd = proj_cwd[pkey]
        origins = sorted(proj_origins[pkey], key=lambda o: (o[0].lower() != cwd.lower(), o[0]))
        machine = " + ".join(sorted({m for _, m in origins}, reverse=True))
        merged = len({o.lower() for o, _ in origins}) > 1  # different folders, not just two sources
        any_prompt = next(iter(ss.values()))[0]
        web = any_prompt["source"].startswith("web")
        where = "Site" if web else "Directory"
        name = any_prompt.get("project") or Path(cwd).name or cwd or "unknown"
        fname = safe_filename(name)
        if fname.lower() in used:
            fname = safe_filename(f"{Path(cwd).parent.name}-{name}")
        n = 2
        base_fname = fname
        while fname.lower() in used:
            fname, n = f"{base_fname}-{n}", n + 1
        used.add(fname.lower())
        folder = PROJECT_DIR / fname
        folder.mkdir(exist_ok=True)

        months = defaultdict(lambda: defaultdict(list))  # month -> sid -> [(number, prompt)]
        for sid, prompts in ss.items():
            for i, p in enumerate(prompts, 1):
                months[f"{p['dt']:%Y-%m}"][sid].append((i, p))

        n_total = sum(len(p) for p in ss.values())
        folders_md = [f"- `{o}` ({m})" for o, m in origins]
        index += [
            f"## {name}",
            "",
            f"{where}: `{cwd}` · Machine: {machine} · {len(ss)} sessions, {n_total} prompts",
            "",
        ]
        if merged:
            index += ["Merged from:", *folders_md, ""]
        index += [
            "| Month | Sessions | Prompts |",
            "|---|---|---|",
        ]
        report.append(f"  [{machine}] {cwd}: {len(ss)} sessions, {n_total} prompts -> projects\\{fname}")
        for month in sorted(months):
            ms = months[month]
            count = sum(len(v) for v in ms.values())
            label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
            lines = [
                f"# Prompt History: {name} · {label}",
                "",
                f"{where}: `{cwd}`  ",
                f"Machine: {machine}  ",
                f"Generated: {generated}  ",
                f"Prompts: **{count}** across **{len(ms)}** sessions",
                "",
            ]
            if merged:
                lines += ["Merged from these folders; each session below says which one it ran in:", *folders_md, ""]
            for sid, items in sorted(ms.items(), key=lambda kv: kv[1][0][1]["dt"]):
                full = ss[sid]
                start, end = items[0][1]["dt"], items[-1][1]["dt"]
                notes = []
                if len(items) != len(full):
                    notes.append(f"session has {len(full)} prompts in total; the rest are in another month's file")
                if any(p["source"] == "web-export" for _, p in items):
                    notes.append(
                        "prompts marked (from export) are timed at when the chat was exported; "
                        "the site does not show when each message was sent"
                    )
                if full[0]["source"] == "web-takeout":
                    notes.append(
                        "imported from Google Takeout, which does not record which chat a prompt was in, "
                        "so these are grouped by day"
                    )
                if full[0]["source"] == "history":
                    notes.append("recovered from history.jsonl; the full transcript no longer exists, so images are not kept")
                lines += [
                    "---",
                    "",
                    f"## Session: {titles[sid]}" if titles.get(sid) else f"## Session `{sid}`",
                    "",
                    f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} · {len(items)} prompts",
                    "",
                ]
                if web:
                    url = next((p["url"] for p in reversed(full) if p.get("url")), "")
                    if url:
                        lines += [f"Chat: <{url}>", ""]
                    elif full[0]["source"] != "web-takeout":
                        lines += [f"Chat id: `{sid}`", ""]
                if merged:
                    o, m = session_origin[sid]
                    lines += [f"Directory: `{o}` · Machine: {m}", ""]
                lines += [f"_Note: {x}._" for x in notes]
                if notes:
                    lines.append("")
                for i, p in items:
                    tag = f" _({p['kind']})_" if p["kind"] else ""
                    lines += [f"**{i}. {p['dt']:%Y-%m-%d %H:%M:%S}**{tag}", ""]
                    if p["moved"]:
                        lines += [f"Directory: `{p['moved']}`", ""]
                    fence = "````" if "```" in p["text"] else "```"
                    lines += [fence + "text", p["text"], fence, ""]
            write(folder / f"{month}.md", "\n".join(lines))
            link = f"projects/{fname}/{month}.md".replace(" ", "%20")
            index.append(f"| [{label}]({link}) | {len(ms)} | {count} |")
        index.append("")

    OUT.write_text("\n".join(index) + "\n", encoding="utf-8")

    # remove month files (and then empty folders) that are no longer produced
    for f in PROJECT_DIR.rglob("*.md"):
        if f.resolve() not in written:
            f.unlink()
    for d in sorted((d for d in PROJECT_DIR.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True):
        try:
            d.rmdir()  # only succeeds when empty
        except OSError:
            pass
    return total_prompts, len(sessions), len(projects), report


def main(argv):
    """Full run: scan Claude Code sources + browser inbox.

    --no-scan          browser inbox only (fast; used by ai_chat_host.py)
    --takeout PATH     also import Gemini prompts from a Google Takeout zip/folder/MyActivity.json
    """
    argv = list(argv)
    takeout = None
    if "--takeout" in argv:
        i = argv.index("--takeout")
        if i + 1 >= len(argv):
            raise SystemExit("--takeout needs a path to the Takeout .zip, folder or MyActivity.json")
        takeout = argv[i + 1]
        del argv[i:i + 2]
    scan = "--no-scan" not in argv
    extra = [a for a in argv if not a.startswith("--")]
    with file_lock(LOCK):
        _run(scan, extra, takeout)


def _run(scan, extra, takeout=None):
    sources = (SOURCES + [(Path(a), f"extra source {a}") for a in extra]) if scan else []
    store = load_store()
    before = len(store)
    for base, machine in sources:
        if not base.is_dir():
            print(f"Skipped {base} ({machine}): not found")
            continue
        nfiles, nt = collect_transcripts(base, machine, store)
        nh = collect_history(base, machine, store)
        print(f"Read {base} ({machine}): {nfiles} transcripts -> {nt} prompts; history.jsonl -> {nh} entries")
    nw = collect_inbox(store)
    print(f"Read browser inbox: {nw} prompts")
    if takeout:
        ng = collect_takeout(takeout, store)
        print(f"Read Google Takeout {takeout}: {ng} Gemini prompts")
    save_store(store)
    print(f"Store: {len(store)} records ({len(store) - before} new) in {STORE}")

    prompts, nsessions, nprojects, report = render(store)
    print(f"Archive: {prompts} prompts, {nsessions} sessions, {nprojects} projects")
    print("\n".join(report))
    print(f"Index: {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
