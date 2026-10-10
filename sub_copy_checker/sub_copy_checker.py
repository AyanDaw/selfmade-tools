"""sub-copy-checker: find out exactly how copies of the same subtitle file differ.

Give it two or more subtitle files. Files are grouped by format and only compared
with files of the same format (an .srt is never compared with a .vtt).
"""

import difflib
import hashlib
import re
import unicodedata
from pathlib import Path

# ============================================================================
# Reading files
# ============================================================================

def read_text(filename):
    """Read a subtitle file and guess its encoding.

    Returns (text, encoding_name, sha256_of_raw_bytes).
    """
    raw = Path(filename).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ["utf-16"]
    else:
        encodings = ["utf-8-sig", "cp1252"]

    for encoding in encodings:
        try:
            return raw.decode(encoding), encoding, digest
        except UnicodeDecodeError:
            continue

    # latin-1 can decode any byte, so this is the last resort
    return raw.decode("latin-1"), "latin-1", digest


def split_lines(text):
    """Split text into lines, treating CRLF, CR and LF the same."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def split_blocks(text):
    """Split text into blocks of non-empty lines separated by blank lines."""
    blocks = []
    block = []

    for line in split_lines(text):
        if line.strip() == "":
            if block:
                blocks.append(block)
                block = []
        else:
            block.append(line)

    if block:
        blocks.append(block)

    return blocks


def make_cue(number, timestamp, dialogue, meta=""):
    """Every format is converted into this same shape, so one comparer fits all.

    number    : the subtitle's own number/identifier, or "" if the format has none
    timestamp : the timing, as written in the file
    dialogue  : list of text lines
    meta      : extra per-subtitle data (used by ASS/SSA for style, margins, ...)
    """
    return {"number": number, "timestamp": timestamp, "dialogue": dialogue, "meta": meta}


def find_timestamp_line(block):
    """Return 0 or 1, the index of the line holding '-->' in a cue block, else None."""
    for index in (0, 1):
        if index < len(block) and "-->" in block[index]:
            return index
    return None


# ============================================================================
# One parser per format. Each returns (cues, skipped).
#   cues    : list of make_cue() dicts
#   skipped : text of anything that could not be understood, so it is never
#             silently ignored
# ============================================================================

def parse_srt(text):
    """Parse SRT: optional number, a 'start --> end' line, then dialogue."""
    cues = []
    skipped = []

    for block in split_blocks(text):
        index = find_timestamp_line(block)

        if index is None:
            skipped.append(" / ".join(block))
            continue

        number = block[0] if index == 1 else ""
        cues.append(make_cue(number, block[index], block[index + 1:]))

    return cues, skipped


def parse_vtt(text):
    """Parse WebVTT: a WEBVTT header, optional NOTE/STYLE/REGION blocks, then cues."""
    if not text.lstrip("﻿").startswith("WEBVTT"):
        raise ValueError("missing the WEBVTT header, so it is not a valid .vtt file")

    cues = []
    skipped = []

    for position, block in enumerate(split_blocks(text)):
        if position == 0 and block[0].lstrip("﻿").startswith("WEBVTT"):
            continue  # header block
        if re.match(r"(NOTE|STYLE|REGION)(\s|$)", block[0]):
            continue  # not subtitles

        index = find_timestamp_line(block)

        if index is None:
            skipped.append(" / ".join(block))
            continue

        number = block[0] if index == 1 else ""
        cues.append(make_cue(number, block[index], block[index + 1:]))

    return cues, skipped


def parse_ass(text):
    """Parse ASS/SSA: only the Dialogue events of the [Events] section are compared.

    Each event's style, layer, margins, name and effect are kept in 'meta'.
    """
    cues = []
    skipped = []
    in_events = False
    columns = None

    for raw in split_lines(text):
        line = raw.lstrip()

        if line.startswith("[") and line.rstrip().endswith("]"):
            in_events = line.strip().lower() == "[events]"
            continue

        if not in_events:
            continue

        lowered = line.lower()

        if lowered.startswith("format:"):
            columns = [c.strip().lower() for c in line.split(":", 1)[1].split(",")]
            if not {"start", "end", "text"} <= set(columns):
                raise ValueError("the [Events] Format line has no Start/End/Text columns")

        elif lowered.startswith("dialogue:"):
            if columns is None:
                raise ValueError("[Events] has Dialogue lines but no Format line")

            # Text is the last column and may itself contain commas
            values = line.split(":", 1)[1].lstrip().split(",", len(columns) - 1)

            if len(values) != len(columns):
                skipped.append(raw)
                continue

            row = dict(zip(columns, values))
            timestamp = f"{row['start'].strip()} --> {row['end'].strip()}"
            meta = ",".join(f"{name}={value.strip()}"
                            for name, value in row.items()
                            if name not in ("start", "end", "text"))
            cues.append(make_cue("", timestamp, row["text"].split("\\N"), meta))

    return cues, skipped


MICRODVD_LINE = re.compile(r"^\{(\d+)\}\{(\d+)\}(.*)$")


def parse_sub(text):
    """Parse MicroDVD .sub: one '{start}{end}Text|Next line' per line (frame based)."""
    cues = []
    skipped = []

    for raw in split_lines(text):
        if raw.strip() == "":
            continue

        match = MICRODVD_LINE.match(raw.lstrip())

        if not match:
            skipped.append(raw)
            continue

        start, end, body = match.groups()
        cues.append(make_cue("", f"{{{start}}}{{{end}}}", body.split("|")))

    if not cues:
        raise ValueError("no MicroDVD lines found (VobSub .sub/.idx image subtitles are not supported)")

    return cues, skipped


SBV_TIMESTAMP = re.compile(r"^\d+:\d{2}:\d{2}\.\d{3},\d+:\d{2}:\d{2}\.\d{3}\s*$")


def parse_sbv(text):
    """Parse YouTube .sbv: a 'start,end' line followed by dialogue, blocks separated by blank lines."""
    cues = []
    skipped = []

    for block in split_blocks(text):
        if not SBV_TIMESTAMP.match(block[0]):
            skipped.append(" / ".join(block))
            continue

        cues.append(make_cue("", block[0], block[1:]))

    return cues, skipped


# Dispatch table: file extension -> parser. Add a new format by writing a parser
# and adding one line here. Each extension counts as its own format.
PARSERS = {
    ".srt": parse_srt,
    ".vtt": parse_vtt,
    ".ass": parse_ass,
    ".ssa": parse_ass,
    ".sub": parse_sub,
    ".sbv": parse_sbv,
}


def load_subtitles(path):
    """Read a file, pick the parser for its format, and return everything we know about it."""
    path = Path(path).expanduser()

    if not path.exists():
        raise ValueError("file not found")
    if not path.is_file():
        raise ValueError("that is a folder, not a file")

    fmt = path.suffix.lower()
    parser = PARSERS.get(fmt)

    if parser is None:
        raise ValueError(f"unsupported format '{fmt or 'no extension'}' "
                         f"(supported: {' '.join(PARSERS)})")

    text, encoding, digest = read_text(path)
    cues, skipped = parser(text)

    if not cues:
        raise ValueError("no subtitles could be parsed from it")

    return {
        "path": path.resolve(),
        "label": path.name,
        "format": fmt,
        "cues": cues,
        "skipped": skipped,
        "encoding": encoding,
        "digest": digest,
    }


# ============================================================================
# Collecting the files from the user
# ============================================================================

QUOTED_PATH = re.compile(r'"([^"]+)"|\'([^\']+)\'')


def clean_path(raw):
    """Strip spaces and the quotes that drag-and-drop adds around a path."""
    path = raw.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in "\"'":
        path = path[1:-1].strip()
    return path


def extract_paths(line):
    """Turn one input line into a list of paths.

    A line naming a single existing file is used as it is. Otherwise, several
    quoted paths on one line (drag-and-drop of many files) are split apart.
    """
    cleaned = clean_path(line)

    if Path(cleaned).expanduser().is_file():
        return [cleaned]

    quoted = [double or single for double, single in QUOTED_PATH.findall(line)]
    return quoted if quoted else [cleaned]


def short(text, limit=60):
    """Shorten text for display."""
    return text if len(text) <= limit else text[:limit - 3] + "..."


def collect_files():
    """Keep asking for files until the user types 'done'. Returns the loaded files."""
    print("Supported formats:", " ".join(PARSERS))
    print("Enter one subtitle file path per line (dragging several files in at once works too).")
    print("Type 'done' when you have entered all the files to start checking.\n")

    files = []
    seen = set()

    while True:
        try:
            line = input(f"File {len(files) + 1} (or 'done')> ")
        except EOFError:
            print("\n(end of input)")
            break

        if line.strip().lower() == "done":
            break
        if line.strip() == "":
            continue

        for raw_path in extract_paths(line):
            try:
                loaded = load_subtitles(raw_path)
            except (OSError, ValueError) as error:
                print(f"  ! skipped '{raw_path}': {error}")
                continue

            if loaded["path"] in seen:
                print(f"  ! skipped '{raw_path}': already added")
                continue

            seen.add(loaded["path"])
            files.append(loaded)

            print(f"  + added {loaded['label']}  "
                  f"[{loaded['format']} | {loaded['encoding']} | {len(loaded['cues'])} subtitles]")

            if loaded["skipped"]:
                print(f"    ! {len(loaded['skipped'])} block(s)/line(s) could not be parsed; "
                      f"they are still compared as raw text. First: {short(loaded['skipped'][0])}")

    return files


# ============================================================================
# Comparing
# ============================================================================

def first_difference(a, b):
    """Return index of first differing character."""
    length = min(len(a), len(b))

    for i in range(length):
        if a[i] != b[i]:
            return i

    if len(a) != len(b):
        return length

    return None


def display_width(text):
    """Approximate how many terminal columns text takes (combining marks take none)."""
    width = 0

    for char in text:
        if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me", "Cf"):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1

    return width


def describe_char(line, index):
    """Show a character together with its code point, which exposes invisible differences."""
    if index >= len(line):
        return "<END>"

    char = line[index]
    name = unicodedata.name(char, "")
    return f"{char!r} U+{ord(char):04X}" + (f" {name}" if name else "")


def describe_line_difference(line_number, line1, line2):
    """Return the report lines for one pair of differing dialogue lines."""
    out = ["", f"Dialogue differs (line {line_number})",
           f" File1: {line1}",
           f" File2: {line2}"]

    diff = first_difference(line1, line2)

    if diff is not None:
        if unicodedata.normalize("NFC", line1) == unicodedata.normalize("NFC", line2):
            out.append(" Note: same text after Unicode normalization (looks identical, encoded differently)")

        out += [f"First difference at character {diff + 1}", "",
                "File1:", line1,
                " " * display_width(line1[:diff]) + "^",
                f"Character: {describe_char(line1, diff)}", "",
                "File2:", line2,
                " " * display_width(line2[:diff]) + "^",
                f"Character: {describe_char(line2, diff)}"]

    return out


def cue_label(cue, index):
    """A readable name for a subtitle: its own number if it has one, else its position."""
    return f"#{cue['number']}" if cue["number"] else f"cue {index + 1}"


def preview(cue):
    """One-line preview of a subtitle's dialogue."""
    return short(" / ".join(cue["dialogue"]), 70)


def cue_key(cue):
    """What decides whether two subtitles are 'the same one' when lining the files up.

    The number is left out on purpose: renumbering must not make every subtitle look different.
    """
    return (cue["timestamp"], tuple(cue["dialogue"]), cue["meta"])


def compare_cue(cue1, index1, cue2, index2, stats):
    """Compare two paired subtitles in detail. Prints only if something differs."""
    out = []

    if cue1["number"] != cue2["number"]:
        stats["number"] += 1
        out += ["Subtitle number differs", f" File1: {cue1['number']}", f" File2: {cue2['number']}"]

    if cue1["timestamp"] != cue2["timestamp"]:
        stats["timestamp"] += 1
        out += ["Timestamp differs", f" File1: {cue1['timestamp']}", f" File2: {cue2['timestamp']}"]

    if cue1["meta"] != cue2["meta"]:
        stats["meta"] += 1
        out += ["Style/settings differ", f" File1: {cue1['meta']}", f" File2: {cue2['meta']}"]

    dialogue1 = cue1["dialogue"]
    dialogue2 = cue2["dialogue"]

    if len(dialogue1) != len(dialogue2):
        stats["line_count"] += 1
        out += ["Dialogue line count differs",
                f" File1: {len(dialogue1)} line(s)",
                f" File2: {len(dialogue2)} line(s)"]

    for j in range(max(len(dialogue1), len(dialogue2))):
        if j >= len(dialogue1):
            out.append(f"Extra dialogue line in File2: {dialogue2[j]}")
            continue

        if j >= len(dialogue2):
            out.append(f"Missing dialogue line in File2: {dialogue1[j]}")
            continue

        if dialogue1[j] != dialogue2[j]:
            stats["text"] += 1
            out += describe_line_difference(j + 1, dialogue1[j], dialogue2[j])

    if out:
        print(f"\n=== File1 {cue_label(cue1, index1)} / File2 {cue_label(cue2, index2)}"
              f"  [{cue1['timestamp']}] ===")
        for line in out:
            print(line)


def cue_similarity(cue1, cue2):
    """0..1 score for how much two subtitles look like the same one (text counts most)."""
    text_ratio = difflib.SequenceMatcher(
        None, " / ".join(cue1["dialogue"]), " / ".join(cue2["dialogue"])).ratio()

    if cue1["timestamp"] == cue2["timestamp"]:
        time_ratio = 1.0
    else:
        time_ratio = difflib.SequenceMatcher(None, cue1["timestamp"], cue2["timestamp"]).ratio()

    return 0.7 * text_ratio + 0.3 * time_ratio


def pair_cues(cues1, i1, i2, cues2, j1, j2):
    """Decide which subtitles inside a differing region belong together.

    Returns a list of (index_in_file1, index_in_file2). Subtitles left out of the
    list are reported as missing/extra. Regions of equal size are paired by
    position; otherwise the most similar subtitles are paired, in order.
    """
    m = i2 - i1
    n = j2 - j1

    if m == n or m * n > 40000:
        return [(i1 + k, j1 + k) for k in range(min(m, n))]

    sim = [[cue_similarity(cues1[i1 + a], cues2[j1 + b]) for b in range(n)] for a in range(m)]

    # best[a][b] = best total similarity using the first a subtitles of File1 and b of File2
    best = [[0.0] * (n + 1) for _ in range(m + 1)]
    for a in range(1, m + 1):
        for b in range(1, n + 1):
            options = [best[a - 1][b], best[a][b - 1]]
            if sim[a - 1][b - 1] >= 0.5:
                options.append(best[a - 1][b - 1] + sim[a - 1][b - 1])
            best[a][b] = max(options)

    pairs = []
    a, b = m, n
    while a > 0 and b > 0:
        if sim[a - 1][b - 1] >= 0.5 and best[a][b] == best[a - 1][b - 1] + sim[a - 1][b - 1]:
            pairs.append((i1 + a - 1, j1 + b - 1))
            a -= 1
            b -= 1
        elif best[a][b] == best[a - 1][b]:
            a -= 1
        else:
            b -= 1

    return pairs[::-1]


def compare(file1, file2):
    """Compare two loaded files of the same format. Prints only the differences.

    Subtitles are lined up by content (not by position), so one extra or missing
    subtitle shows up as one difference instead of shifting everything after it.
    Returns True if the files are identical.
    """
    cues1 = file1["cues"]
    cues2 = file2["cues"]

    matcher = difflib.SequenceMatcher(None,
                                      [cue_key(c) for c in cues1],
                                      [cue_key(c) for c in cues2],
                                      autojunk=False)

    stats = dict.fromkeys(("number", "timestamp", "meta", "line_count", "text",
                           "missing", "extra", "skipped"), 0)
    matched = 0
    renumbered = 0
    first_renumbered = None

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                matched += 1
                number1 = cues1[i1 + k]["number"]
                number2 = cues2[j1 + k]["number"]
                if number1 != number2:
                    renumbered += 1
                    if first_renumbered is None:
                        first_renumbered = (number1, number2)
            continue

        pairs = pair_cues(cues1, i1, i2, cues2, j1, j2)
        paired1 = {i for i, _ in pairs}
        paired2 = {j for _, j in pairs}

        for i, j in pairs:
            compare_cue(cues1[i], i, cues2[j], j, stats)

        for i in range(i1, i2):
            if i not in paired1:
                stats["missing"] += 1
                cue = cues1[i]
                print(f"\nMissing in File2: {cue_label(cue, i)} [{cue['timestamp']}] {preview(cue)}")

        for j in range(j1, j2):
            if j not in paired2:
                stats["extra"] += 1
                cue = cues2[j]
                print(f"\nExtra in File2: {cue_label(cue, j)} [{cue['timestamp']}] {preview(cue)}")

    if renumbered:
        stats["number"] += renumbered
        print(f"\nNote: {renumbered} otherwise identical subtitle(s) carry a different number "
              # pyrefly: ignore [unsupported-operation]
              f"(first: File1 #{first_renumbered[0]} vs File2 #{first_renumbered[1]}).")

    if file1["skipped"] != file2["skipped"]:
        stats["skipped"] = max(1, len(set(file1["skipped"]) ^ set(file2["skipped"])))
        print("\nBlocks that could not be parsed differ:")
        print(f" File1: {len(file1['skipped'])} block(s)", [short(s, 40) for s in file1["skipped"][:5]])
        print(f" File2: {len(file2['skipped'])} block(s)", [short(s, 40) for s in file2["skipped"][:5]])

    print("\n========== SUMMARY ==========")
    print("Subtitles in File1 / File2 :", f"{len(cues1)} / {len(cues2)}")
    print("Matched exactly :", matched)
    print("Only in File1 (missing in File2) :", stats["missing"])
    print("Only in File2 (extra) :", stats["extra"])
    print("Subtitle number differences :", stats["number"])
    print("Timestamp differences :", stats["timestamp"])
    print("Style/settings differences :", stats["meta"])
    print("Dialogue line-count differences :", stats["line_count"])
    print("Dialogue text differences :", stats["text"])
    print("Unparsed-block differences :", stats["skipped"])

    identical = (sum(stats.values()) == 0)
    print("\nFiles are IDENTICAL." if identical else "\nFiles are NOT identical.")
    return identical


# ============================================================================
# Checking many files
# ============================================================================

def signature(loaded):
    """Everything that counts when deciding that two files are the same."""
    cues = tuple((c["number"], c["timestamp"], tuple(c["dialogue"]), c["meta"])
                 for c in loaded["cues"])
    return cues, tuple(loaded["skipped"])


def group_by_signature(items):
    """Split files into groups with identical content, in order of first appearance."""
    groups = {}
    for loaded in items:
        groups.setdefault(signature(loaded), []).append(loaded)
    return list(groups.values())


def names(items):
    return ", ".join(f["label"] for f in items)


def byte_note(group):
    """Explain why files with identical content might still not be byte-identical."""
    if len({f["digest"] for f in group}) > 1:
        return ("  (note: the raw bytes differ, e.g. BOM, line endings or encoding: "
                + ", ".join(sorted({f["encoding"] for f in group})) + ")")
    return ""


def check_group(fmt, items):
    """Check all the files of one format against each other."""
    print(f"\n{'#' * 12} {fmt} files ({len(items)}) {'#' * 12}")

    if len(items) < 2:
        print(f"Only one {fmt} file ({items[0]['label']}), so there is nothing to compare it with.")
        return

    groups = group_by_signature(items)

    if len(groups) == 1:
        print(f"All {len(items)} files are IDENTICAL in content: {names(items)}")
        note = byte_note(items)
        if note:
            print(note)
        return

    reference = groups[0][0]
    print(f"Reference file: {reference['label']}")
    if len(groups[0]) > 1:
        print(f"Identical to the reference: {names(groups[0][1:])}")

    for group in groups[1:]:
        print("\n" + "-" * 70)
        print(f"File1 = {reference['label']}\nFile2 = {group[0]['label']}")
        if len(group) > 1:
            print(f"(these files have exactly the same content as File2: {names(group[1:])})")
        compare(reference, group[0])

    print("\n" + "=" * 70)
    print(f"GROUPS of identical {fmt} files")
    for number, group in enumerate(groups, start=1):
        print(f"Group {number} ({len(group)} file(s)): {names(group)}")
        note = byte_note(group) if len(group) > 1 else ""
        if note:
            print(note)


def assign_labels(files):
    """Use the file name as its label, or the full path if two files share a name."""
    all_names = [f["path"].name for f in files]

    for loaded in files:
        name = loaded["path"].name
        loaded["label"] = name if all_names.count(name) == 1 else str(loaded["path"])


def check_all(files):
    """Group the files by format and check each group. Formats are never mixed."""
    assign_labels(files)

    by_format = {}
    for loaded in files:
        by_format.setdefault(loaded["format"], []).append(loaded)

    for fmt, items in by_format.items():
        check_group(fmt, items)

    if len(by_format) > 1:
        print("\nNote: files of different formats were not compared with each other.")


def main():
    try:
        files = collect_files()

        if not files:
            print("No files were added, nothing to check.")
            return

        print(f"\nChecking {len(files)} file(s)...")
        check_all(files)
    except KeyboardInterrupt:
        print("\nCancelled.")


if __name__ == "__main__":
    main()