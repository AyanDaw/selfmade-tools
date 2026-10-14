"""
2srtconverter: converts every .vtt file in <folder>/VTT into an .srt file
in <folder>/SRT.

Rules:
    1. SRT files keep the same file name as the VTT file (only the
       extension changes). They are written to a different folder (SRT).
    2. Existing .srt files with the same name are overwritten.
    3. A file that can't be converted is reported and skipped; the rest
       of the files are still converted.
"""

import html
import re
import shutil
from pathlib import Path

# Timing line, e.g. "00:01:02.500 --> 00:01:04.000" (hours are optional in
# VTT, and cue settings after the end time are simply not matched).
TIMING = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})"
)
# Any tag except <i> <b> <u> (SRT players understand only those).
TAG = re.compile(r"<(?!/?[ibu]>)[^>]*>")
# Blocks that are not cues: file header and comment/style/region blocks.
NON_CUE = re.compile(r"(WEBVTT|NOTE|STYLE|REGION)(\s|$)")


def vtt_to_srt(vtt: str) -> str:
    srtcues = []
    # Make every line ending "\n" and drop a BOM if one is left in the text.
    vtt = vtt.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    # Blocks are separated by one or more blank lines.
    vttcues: list[str] = re.split(r"\n\s*\n", vtt.strip())
    number: int = 1
    for cue in vttcues:
        items: list = cue.splitlines()
        if not items:
            continue
        if NON_CUE.match(items[0]):
            continue
        # The timing line is the 1st line, or the 2nd if the cue has an id.
        match = None
        for i in range(min(2, len(items))):
            match = TIMING.search(items[i])
            if match:
                break
        if not match:
            raise ValueError(f"no timing line in block: {items[0]!r}")
        h1, m1, s1, ms1, h2, m2, s2, ms2 = match.groups()
        timing: str = (
            f"{int(h1 or 0):02d}:{m1}:{s1},{ms1} --> "
            f"{int(h2 or 0):02d}:{m2}:{s2},{ms2}"
        )
        # Everything after the timing line is dialogue.
        dialogues: list[str] = [
            html.unescape(TAG.sub("", line)).strip() for line in items[i + 1:]
        ]
        dialogues = [line for line in dialogues if line]
        if not dialogues:
            continue
        srtcues.append(f"{number}\n{timing}\n" + "\n".join(dialogues) + "\n")
        number += 1
    if not srtcues:
        raise ValueError("no subtitle cues found")
    return "\n".join(srtcues)


def vtt2srtfile(vttfrom: Path, srtto: Path) -> None:
    vtt_files = sorted(
        path for path in vttfrom.iterdir()
        if path.is_file() and path.suffix.lower() == ".vtt"
    )

    if not vtt_files:
        print(f"No VTT files found in: {vttfrom}")
        return

    successful = 0
    failed = 0

    for vtt_file in vtt_files:
        try:
            vtt = vtt_file.read_text(encoding="utf-8-sig")
            srt: str = vtt_to_srt(vtt)

            srt_file: Path = srtto / f"{vtt_file.stem}.srt"
            srt_file.write_text(srt, encoding="utf-8")

            successful += 1
            print(f"Conversion successful: {vtt_file.name} -> {srt_file.name}")

        except (OSError, ValueError) as e:
            failed += 1
            print(f"Conversion failed: {vtt_file.name} : {e}")

    print(f"\nFinished: {successful} successful, {failed} failed.")


def main() -> None:
    print(
        "2srtconverter: enter the path of a folder. It will get two "
        "subfolders:\n"
        "  VTT - put your .vtt files here\n"
        "  SRT - the converted .srt files appear here\n"
        "Make sure the folder has writing permissions."
    )
    input("Press 'enter' when you are ready")

    folder_input: str = input("Enter the full path of your folder: ").strip()
    # Drag and drop often wraps the path in quotes.
    folder_input = folder_input.strip("\"'")
    mainfolder: Path = Path(folder_input).expanduser()

    if not mainfolder.is_dir():
        print("Error: The specified folder doesn't exist.")
        return

    vttfrom: Path = mainfolder / "VTT"  # source folder
    srtto: Path = mainfolder / "SRT"  # destination folder

    try:
        vttfrom.mkdir(parents=True, exist_ok=True)
        srtto.mkdir(parents=True, exist_ok=True)
        for item in mainfolder.iterdir():
            if item == vttfrom:
                continue
            try:
                if item.is_file() and item.suffix.lower() == ".vtt":
                    shutil.move(str(item), str(vttfrom))
            except OSError as e:
                print(f"Error: Faced a {e} error while moving the {item.name}!")
        vtt2srtfile(vttfrom, srtto)
    except OSError as e:
        print(f"Folder or file operation failed: {e}")


if __name__ == "__main__":
    main()