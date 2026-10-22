# ------------------------------------------------------------------------------

"""Download every subtitle track of one episode page.

Steps:
1. Fetch the episode page, using the headers and cookies from a "Copy as cURL"
	of your own browser (the site is behind Cloudflare).
2. Find the video's .m3u8 playlist in the page and read its subtitle tracks.
3. Save each track as <episode>.<lang>.vtt

The cURL is kept in a small file, so a stopped run can continue. That file is
deleted only after every subtitle file is on disk.

Needs Python 3.10+ and:  pip install curl_cffi rich
"""

# --- Imports ------------------------------------------------------------------

import argparse
import json
import re
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Literal, NoReturn
from urllib.parse import urljoin, urlparse

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException, Timeout
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
	BarColumn,
	DownloadColumn,
	MofNCompleteColumn,
	Progress,
	SpinnerColumn,
	TaskID,
	TaskProgressColumn,
	TextColumn,
	TimeRemainingColumn,
	TransferSpeedColumn,
)
from rich.table import Column
from rich.text import Text

# --- Custom Classes -----------------------------------------------------------

class Fatal(Exception):
	"""A problem we can't continue after. The message is shown to the user."""


# --- Data ---------------------------------------------------------------------


@dataclass(frozen=True)
class CurlRequest:
	url: str
	headers: dict[str, str]
	cookies: dict[str, str]


@dataclass(frozen=True)
class Track:
	lang: str
	name: str
	url: str


# --- Settings -----------------------------------------------------------------

DOWNLOADS_DEFAULT = Path.home() / "Downloads" / "hsub_downloads"
SUBTITLES_DEFAULT = DOWNLOADS_DEFAULT / "subtitles"
COOKIES_FOLDER_DEFAULT = DOWNLOADS_DEFAULT / "cookies"

BROWSERS = ("zen", "firefox")  # Firefox-based: the cURL format we know how to read
IMPERSONATE = "firefox"  # browser TLS fingerprint curl_cffi copies (gets past Cloudflare)
TIMEOUT = 15  # seconds, per request
SKIP_HEADERS = ("host", "content-length", "accept-encoding")  # the HTTP library sets these

EXT_X_MEDIA = "#EXT-X-MEDIA:"
# KEY=value pairs of an #EXT-X-MEDIA line. A value is "quoted" (may hold commas) or runs
# to the next comma.
ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')

_show_guide = True

GUIDE = """\
1. What it does?

A>	Downloads every subtitle track of one episode from the site (a very specific site).
	Some tracks can't be saved from the player; this gets all of them at once.

2. What you need

A> 	- A folder for the subtitles (default: {subs}/<episode>). It must be writable.
	
	- A folder for the saved cURL file (default: {cookies}). It lets a stopped run
	continue, and is deleted after a fully successful download.
	
	- A Firefox-based browser (Zen, Firefox) with the episode page open.
"""

CURL_GUIDE = """\
How to copy the cURL from {browser}

	1. Open the episode page, then press F12 to open the dev tools.
	
	2. Open the 'Network' tab (look under '>>' if you can't see it) and reload the page.
	Make sure no filter is active.
	
	3. Find the row with File '{path}', Initiator 'Document' and Type 'html'.
	
	4. Right-click it, then 'Copy Value' > 'Copy as cURL' (the POSIX one, if you get a choice).
	
	5. Paste it here. A multi-line paste is fine.
"""

MAX_CONCURRENT = 4	# Downloads running at the same time

# --- Output ------------------------------------------------------------------

console = Console(highlight=False)

Level = Literal["DEBUG", "INFO", "OK", "WARN", "ERROR"]
STYLES: dict[Level, str] = {
	"DEBUG" : "dim",
	"INFO" : "bright_blue",
	"OK" : "green",
	"WARN" : "yellow",
	"ERROR" : "bold red",
}
_show_debug = False


def log(level: Level, message: str) -> None:
	"""Log isnt private"""
	if level == "DEBUG" and not _show_debug:
		return
	console.print(Text(text=f"[{level:<7}] :", style=STYLES[level]).append(message, style=""))



# --- cURL ---------------------------------------------------------------------


class _CurlParser(argparse.ArgumentParser):
	def error(self, message:str) -> NoReturn:
		raise Fatal(f"Could not read the cURL command ({message}).")

def read_pasted_curl() -> str:
	"""Read a multi-line paste: lines ending in a backslash continue on the next line."""
	lines = []
	while True:
		line = input().rstrip()
		lines.append(line.removesuffix("\\").rstrip())
		if not line.endswith("\\"):
			return " ".join(lines)

def parse_curl(text: str) -> CurlRequest:
	"""Pull the page link, headers and cookies out of a "Copy as cURL" command."""
	try:
		parts = shlex.split(text.replace("\\\n", " "))
	except ValueError as err:
		raise Fatal(f"The cURL command is cut off or has broken quotes ({err}).") from err
	if len(parts) < 2 or parts[0] != "curl":
		raise Fatal("That is not a cURL command.")

	parser = _CurlParser(add_help=False, allow_abbrev=False) # Wont let -h command to work, and wont let abbreviations to work
	parser.add_argument("command")
	parser.add_argument("url")
	parser.add_argument("-H", "--header", action="append", default=[])
	parser.add_argument("-b", "--cookie", default="")
	args, _ignored = parser.parse_known_args(parts)
	if urlparse(args.url).scheme not in ("http", "https"):
		raise Fatal("The cURL command has no page link in it.")

	headers: dict[str, str] = {}
	for header in args.header:
		name, _, value = header.partition(":")  # first ':' only: values may hold more
		headers[name.strip().lower()] = value.strip()

	header_cookie = headers.pop("cookie", "")  # Firefox puts cookies in a header
	cookies: dict[str, str] = {}
	for pair in (args.cookie or header_cookie).split(";"):
		key, sep, value = pair.strip().partition("=")  # first '=' only: values may hold more
		if sep:
			cookies[key] = value

	for name in SKIP_HEADERS:
		headers.pop(name, None)
	return CurlRequest(args.url, headers, cookies)


def paste_curl(curl_file: Path, page_url: str) -> CurlRequest:
	if _show_guide and confirm("Show how to copy the cURL?", default=True):
		browser = ask_browser()
		console.print(Text(CURL_GUIDE.format(browser=browser, path=urlparse(page_url).path)))
	log('INFO', "Paste the cURL now:")
	while True:
		text = read_pasted_curl()
		try:
			request = parse_curl(text)
			break
		except Fatal as err:
			log('ERROR', f"{err} Paste it again:")
	try:
		curl_file.write_text(text, encoding="utf-8") # Storing the whole curl file here so using text instead of request
		curl_file.chmod(0o600) # it holds live cookies: keep it private, although here it is not needed.
	except OSError as err:
		raise Fatal(f"Could not save {curl_file}: {err}") from err
	log('OK', f"cURL saved: {curl_file}")
	return request


def load_request(curl_file: Path, page_url: str) -> CurlRequest:
	if curl_file.exists():
		log('INFO', f"Reusing the saved cURL: {curl_file}")
		log('INFO', "If it fails delete that file and run again to paste a fresh one.")
		try:
			request = parse_curl(curl_file.read_text(encoding="utf-8"))
		except OSError as err:
			raise Fatal(f"Could not read {curl_file}: {err}") from err
		except Fatal as err:
			raise Fatal(f"{err} Delete {curl_file} and run again.") from err
	else:
		request = paste_curl(curl_file, page_url)
	log("DEBUG", f"url: {request.url}")
	log("DEBUG", f"header names: {list(request.headers)}")
	log("DEBUG", f"cookie names: {list(request.cookies)}")
	return request


# --- Network ------------------------------------------------------------------


def get(
	session: requests.Session,
	url: str,
	*,
	headers: dict[str, str],
	cookies: dict[str, str] | None = None,
	hint: str = "",
	stream: bool = False,
) -> requests.Response:
	"""GET a link. Any failure becomes a Fatal with a readable message."""
	try:
		response = session.get(url, headers=headers, cookies=cookies, timeout=TIMEOUT, stream=stream)
	except Timeout as err:
		raise Fatal(f"Timed out after {TIMEOUT}s: {url}") from err
	except RequestException as err:
		raise Fatal(f"Network error for {url}: {err}") from err
	if response.status_code >= 400:
		extra = f" {hint}" if hint and response.status_code == 403 else ""
		raise Fatal(f"HTTP {response.status_code} for {url}.{extra}")
	return response


def find_playlist(page_html: str) -> str | None:
	"""Return the .m3u8 playlist link of the video on a watch page, or None."""
    # 1) schema.org VideoObject in a JSON-LD block (a standard place for it)
	for block in re.findall(
		r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page_html, flags=re.DOTALL
	):
		try:
			data = json.loads(block)
		except ValueError:
			continue
		for item in data if isinstance(data, list) else [data]:
			url = item.get("contentUrl") if isinstance(item, dict) else None
			if isinstance(url, str) and ".m3u8" in url:
				return unescape(url)
	# 2) the <source> tag of the <video> element
	if match := re.search(r'<source[^>]+src="([^"]+\.m3u8[^"]*)"', page_html):
		return unescape(match.group(1))
	# 3) any .m3u8 link anywhere, e.g. inside the page's JSON data (last resort)
	if match := re.search(r"""https?://[^\s"'\\]+\.m3u8[^\s"'\\]*""", page_html):
		return unescape(match.group(0))
	return None


def parse_subtitle_tracks(playlist_text: str, playlist_url: str) -> list[Track]:
	"""List the subtitle tracks (language, name, full link) of a master playlist."""
	tracks = []
	for line in playlist_text.splitlines():
		line = line.strip()
		if not line.startswith(EXT_X_MEDIA):
			continue
		attrs = {k: v.strip('"') for k, v in ATTR.findall(line.removeprefix(EXT_X_MEDIA))}
		if attrs.get("TYPE") != "SUBTITLES" or "URI" not in attrs:
			continue
		link = urljoin(playlist_url, attrs["URI"]) # links in a playlist are often relative
		tracks.append(Track(lang=attrs.get("LANGUAGE", ""), name=attrs.get("NAME", ""), url=link))
	return tracks


def plan_downloads(tracks: list[Track], stem: str) -> list[tuple[str,str]]:
	"""Choose a file name for each usable track: (<stem>.<lang>.vtt, link)."""
	files: list[tuple[str, str]] = []
	used: set[str] = set()
	for track in tracks:
		lang = re.sub(r"[^A-Za-z0-9]", '_', track.lang)
		label = lang or track.name or "(unnamed)"
		if not lang:
			log("WARN", f"Skipped {label}: the track has no language tag.")
		elif lang.lower() in used:
			log("WARN", f"Skipped {label}: a second track with the same language tag.")
		elif not urlparse(track.url).path.lower().endswith(".vtt"):
			log("WARN", f"Skipped {label}: not a plain .vtt link (segmented subtitles aren't supported).")
		else:
			used.add(lang.lower())
			files.append((f"{stem}.{lang}.vtt", track.url))
	return files


def download_one(session: requests.Session, url: str, target: Path, headers: dict[str,str], jobs: Progress, task: TaskID) -> bool:
	"""Save one file. False if it was already there; raises Fatal or OSError on failure."""
	if target.is_file() and target.stat().st_size > 0:
		return False
	response = get(session, url, headers=headers, stream=True)
	part = target.with_name(target.name + ".part")  # write aside, then rename: no half files
	try:
		length = response.headers.get("Content-Length")
		jobs.update(task, total=int(length) if length else None)
		with part.open("wb") as f:
			for chunk in response.iter_content():
				f.write(chunk)
				jobs.advance(task, len(chunk))
	except RequestException as err:
		raise Fatal(f"Network error for {url}: {err}") from err
	finally:
		response.close()
	with part.open("rb") as f:
		start = f.read(16)
	if not start.lstrip(b"\xef\xbb\xbf").startswith(b"WEBVTT"):
		part.unlink()
		raise Fatal("the reply is not a WEBVTT file")
	part.replace(target)
	size = target.stat().st_size
	jobs.update(task, total=size, completed=size)
	return True


def shorten(name: str, width: int = 28) -> str:
	"""Cut a long name to `width` characters, keeping the end (the language tag)."""
	return name if len(name) <= width else "..." + name[-(width - 3) :]


def download_all_progress(
	session: requests.Session,
	files: list[tuple[str, str]],
	dest_dir: Path,
	headers: dict[str,str],
):
	# Progress object only for jobs
	jobs = Progress(
		SpinnerColumn(style="bold green", finished_text="✓"),
		TextColumn("{task.description}", markup=False, table_column=Column(width=32, no_wrap=True)),
		BarColumn(bar_width=20, complete_style="light blue", finished_style="light blue"),
		TaskProgressColumn(),
		DownloadColumn(),
		TimeRemainingColumn(),
		TransferSpeedColumn(),
	)
	overall = Progress(
		SpinnerColumn(style="bold green", finished_text="✓"),
		TextColumn("Total", markup=False, style="bold", table_column=Column(width=32, no_wrap=True)),
		BarColumn(bar_width=20, complete_style="light blue", finished_style="light blue"),
		TaskProgressColumn(),
		MofNCompleteColumn(),
	)
	total_task = overall.add_task(description="Total", total=len(files))

	def work(file): # This starts one job and calls the download_one()
		name, url = file
		task = jobs.add_task(shorten(name), total=None)
		try:
			downloaded = download_one(session, url, dest_dir / name, headers, jobs, task)
		except (Fatal, OSError) as err:
			# This is not a fatal error so we wont call Raise Fatal
			log("ERROR", f"{name}: {err}")
			outcome = "failed"
		else: 
			outcome = "saved" if downloaded else "present"
		if outcome != "saved":
			jobs.remove_task(task)
		overall.advance(total_task)
		return outcome

	with Live(Panel(Group(jobs, overall), title="Donwloads", style="bright_cyan", border_style="bright_cyan", title_align="left"), console=console):  # noqa: SIM117
		with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as pool:
			results = list(pool.map(work, files))

	saved   = [n for (n, _), r in zip(files, results) if r == "saved"]
	present = [n for (n, _), r in zip(files, results) if r == "present"]
	failed  = [n for (n, _), r in zip(files, results) if r == "failed"]
	return saved, present, failed


# --- Prompts ------------------------------------------------------------------


def confirm(question: str, *, default: bool) -> bool:
	answer = input(f"{question} {'[Y/n]' if default else '[y/N]'} ").strip().lower()
	return default if not answer else answer.startswith("y")


def is_http_url(url: str) -> bool:
	parsed = urlparse(url)
	return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def ask_url() -> str:
	while True:
		url = input("Episode page link: ").strip().strip("\"'")
		if is_http_url(url):
			return url
		log("ERROR", "That is not a full link. It should start with https://")


def ask_browser() -> str:
	while True:
		answer = input(f"Browser the page is open in ({'/'.join(BROWSERS)}): ").strip().lower()
		if answer in BROWSERS:
			return answer
		log("ERROR", f"Please choose one of: {', '.join(BROWSERS)} (Chromium isn't supported yet).")


def ask_path(question: str, default: Path) -> Path:
	answer = input(f"{question}\n  [{default}] > ").strip().strip("\"'")
	return Path(answer).expanduser() if answer else default


# --- Names and folders --------------------------------------------------------


def episode_name(url: str) -> str:
	""".../watch/<series>/episode-4/  ->  '<series> episode-4'"""
	parts = [p for p in urlparse(url).path.split("/") if p and p != "watch"]
	name = " ".join(parts[-2:]) or "episode"
	return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", name)  # characters no file name may hold


def slug(text: str) -> str:
	return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "episode"


def make_dirs(*folders: Path) -> None:
	for folder in folders:
		try:
			folder.mkdir(parents=True, exist_ok=True)
		except OSError as err:
			raise Fatal(f"Could not create {folder}: {err}") from err


def same_page(a: str, b: str) -> bool:
	pa, pb = urlparse(a), urlparse(b)
	return (pa.hostname, pa.path.rstrip("/")) == (pb.hostname, pb.path.rstrip("/"))


# --- Main ---------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
	console.rule(Text(Path(__file__).name))
	if _show_guide and confirm("Show the guide?", default=False):
		console.print(Text(GUIDE.format(subs=SUBTITLES_DEFAULT, cookies=COOKIES_FOLDER_DEFAULT)))

	url = args.url or ask_url()
	if not is_http_url(url):
		raise Fatal("The link must be a full address starting with https://")
	episode = episode_name(url)
	stem = slug(episode)

	subs_dir = ask_path("Folder to save the subtitles into", SUBTITLES_DEFAULT / episode)
	cookies_dir = ask_path("Folder to keep the saved cURL file in", COOKIES_FOLDER_DEFAULT)
	make_dirs(subs_dir, cookies_dir)

	curl_file = cookies_dir / f"{episode}_curl.txt"
	request = load_request(curl_file, url)
	if not same_page(request.url, url):
		raise Fatal(f"The cURL is for another page ({request.url}). Delete {curl_file} and run again.")

	with requests.Session(impersonate=IMPERSONATE) as session:
		page = get(
			session,
			request.url,
			headers=request.headers,
			cookies=request.cookies,
			hint=f"The saved cURL may have expired: delete {curl_file} and run again."
		)
		log("DEBUG", f"page: HTTP {page.status_code}, {len(page.text)} characters")

		playlist_url = find_playlist(page.text)
		if not playlist_url:
			raise Fatal("No .m3u8 playlist link found in the page. Is it an episode page?")
		log("DEBUG", f"playlist: {playlist_url}")
		# The playlist and the files live on another domain. They get the User-Agent and a
        # Referer only: the site's cookies are never sent anywhere else.
		
		site = urlparse(request.url)
		other_headers = {"Referer": f"{site.scheme}://{site.netloc}/"}
		if user_agent := request.headers.get("user-agent"):
			other_headers["User-Agent"] = user_agent

		playlist = get(
            session,
            playlist_url,
            headers=other_headers,
            hint="The playlist server may want a different Referer.",
        )

		tracks = parse_subtitle_tracks(playlist.text, playlist_url)
		files = plan_downloads(tracks, stem)
		log("INFO", f"Found {len(tracks)} subtitle track(s), {len(files)} usable.")
		if not files:
			raise Fatal("No usable subtitle tracks in the playlist.")

		saved, present, failed = download_all_progress(session, files, subs_dir, other_headers)

	missing = [name for name, _ in files if not (subs_dir / name).is_file()]
	log("INFO", f"Saved {len(saved)}, already there {len(present)}, failed {len(failed)}.")
	log("INFO", f"Subtitles folder: {subs_dir}")
	if missing:
		log("WARN", f"Missing files: {', '.join(missing)}")
		log("INFO", f"The saved cURL was kept ({curl_file}); run again to retry them.")
		return 1
	curl_file.unlink(missing_ok=True)
	log("OK", "Every subtitle file is on disk. The saved cURL file was deleted.")
	return 0



def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Download every subtitle track of one episode page of this specific site.")
	parser.add_argument('--url', nargs='?', help="episode page link (asked for if left out)")
	parser.add_argument('--debug', action='store_true', help="store extra detail")
	parser.add_argument("--no-guide", action="store_true", help="Use this argument to skip guide asks. This will skip showing guides.")
	return parser.parse_args()


def main() -> int:
	global _show_debug
	global _show_guide
	args = parse_args()
	_show_debug = args.debug
	_show_guide = not args.no_guide
	try:
		return run(args)
	except Fatal as err:
		log("ERROR", str(err))
		return 1
	except (KeyboardInterrupt, EOFError):
		console.print()
		log("WARN", "Stopped. A saved cURL file was kept, so the next run can continue.")
		return 130


if __name__ == "__main__":
	sys.exit(main())