# Baseline change log - pointer index

**Check this file first.** It's the only thing that should ever need a
full read; the category files it points to are for when you actually
need the detail behind one row. This mirrors the "small pointer file
routes to focused detail files" pattern (the kind of flat,
grep-friendly notes-repo layout associated with Andrew Karpathy's own
public notes/wiki habits) rather than one giant log or a database.

## What this is

Every request that results in a deployed change - whether asked in this
chat or (once it exists) via Baseline's own built-in Chat tab - gets one
entry, in the category file for the area it touched. Entries are never
edited or removed after the fact; if something turns out to be wrong or
gets superseded, a *new* entry says so and links back to the old one by
date/title. This file (`INDEX.md`) is the only thing that gets
overwritten in place - it's a pointer, not a record.

## Categories

| Category | Open file | Entries | Last updated | Latest entry |
|---|---|---|---|---|
| [boot](boot/001.md) | boot/001.md | 7 | 2026-09-20 | Proxmox<->BaselineOS round trip (chvt-based, both directions) |
| [hardware](hardware/001.md) | hardware/001.md | 7 | 2026-09-20 | Display fact added, then reverted (caused console garble) |
| [network](network/001.md) | network/001.md | 6 | 2026-09-20 | ConnectionModal: bridged identity, alias, enable/disable, lifeline position |
| [ui](ui/001.md) | ui/001.md | 11 | 2026-09-20 | Down arrow as sole navigation unreliable on bare console (Shift+Tab fallback) |
| [chat](chat/001.md) | chat/001.md | 1 | 2026-09-20 | Chat-tab quality assessment (decision only, no code yet) |

Categories are named after the part of the system a change touches, not
the UI tab (e.g. a fix to the Hardware *tab's* focus handling is logged
under `ui`, not `hardware`, if the bug was really about tab/focus
mechanics rather than hardware data - cross-reference when a change
spans two, as several entries above do).

## Adding a new entry

1. Copy the block from [`TEMPLATE.md`](TEMPLATE.md).
2. Append it to the bottom of the open file for the right category
   (the "Open file" column above).
3. If that file is now past ~400 lines or ~15 entries, create the next
   numbered file in that category's directory (e.g. `boot/002.md`),
   add a one-line "block NNN (open)" header to it matching the existing
   files, and change that category's "Open file" link above to point
   to the new file. The old file stays as-is, permanently - do not move
   entries between files.
4. Update this table's row for that category: entry count, date,
   one-line summary of the new latest entry.

## Rotation rule (why blocks, not one file per category)

One unbounded file per category would eventually make "check the
pointer, open the relevant file" slow again, defeating the purpose.
Capping each block at a size that's fast to scan/grep and starting a
new numbered block keeps every individual file cheap to open, while the
full history stays intact across the numbered sequence.

## Cross-references

An entry that spans categories (e.g. the exclusive-worker-group bug
that emptied the Hardware tab was really a Textual/UI mechanics bug)
gets a real entry in its primary category and a short pointer-only
entry in the other, saying so explicitly rather than duplicating the
full write-up.
