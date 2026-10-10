import importlib.util
import sys

REQUIRED_PACKAGES = {
    "requests": "requests",
    "dotenv": "python-dotenv",
    "rich": "rich",
}

missing = [pip_name for mod, pip_name in REQUIRED_PACKAGES.items()
           if importlib.util.find_spec(mod) is None]
if missing:
    sys.exit(f"ERROR: missing required package(s): {', '.join(missing)}\n"
              f"Install with:\n    pip install {' '.join(missing)}")


import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import dotenv_values

# from rich.console import Console

config = dotenv_values(".env")


LOG_FILE = Path("log.txt")
LINKBOOK = Path("links.txt")
TMDB_API = config["TMDB_API_KEY"]
SERIES = config["SERIES"]
# pyrefly: ignore [bad-argument-type]
SEASON = int(config["SEASON"])
SERIES_ID = config["SERIES_ID"]
TYPE = "tv"

STOP_FLAG = Path("STOP_MONITORS")   # tells monitor.py / Qmonitor.py to exit cleanly on their own

YT_DLP_BIN = "yt-dlp"
DENO_BIN = "deno"
MKVMERGE_BIN = "mkvmerge"
MKVPROPEDIT_BIN = "mkvpropedit"

FUNNY_MSG = ["Wait i ate too much, *burrrrp* let me digest some food :)", 
             "Hey You are working too hard, Its a water break reminder",
             "Its good to take break sometimes ;)",
             "Have you taken a washroom break? remember dont long hold your pee :|"]
YTDLP_LOG = Path("ytdlp_output.log")
QUEUE_STATUS_FILE = Path("Queuestatus.json")

def resolve_tool(name: str, env_key: str) -> str:
    """Fixes the dependency checks. .env override first, PATH lookup second, exits with an actionable message otherwise."""
    configured = (config.get(env_key) or "").strip()
    if configured:
        if Path(configured).exists():
            return configured
        sys.exit(f"ERROR: {env_key} in .env points to '{configured}', but that path doesn't exist.")
    found = shutil.which(name)
    if found:
        return found
    sys.exit(f"ERROR: '{name}' not found on PATH, and {env_key} isn't set in .env. Install it first add its Path to System Variable or in the .env")

class Episode:
    def __init__(self, series: str, season: int, epnumber: int):
        self.series = series        # str, Done
        self.season = season        # int, Done
        self.epnumber = epnumber    # int, Done
        self.title = None           # str, Done
        self.youtube_url = "None"     # str, Done
        self.runtime = None         # str, Done
        self.description = None     # str, Done
        self.filename = None        # str, Done
        self.download_status= False # bool, Done

    def fetch_metadata(self, tmdb_cache):
        self.title = tmdb_cache.get(self.epnumber)   # Episode Title


    def build_filename(self) -> str:
        """e.g. 'Nonte Fonte S01E005 <Title>'""" # Total 140 episodes are there
        self.filename = f"{self.series} S{self.season:02d}E{self.epnumber:03d} {self.title}"
        self.filename = re.sub(r'[<>:"/\\|?*]', "", self.filename).strip() # Sanitizing for Windows
        self.filename += ".mkv" # Extension
        return self.filename


    def log_entry(self) -> str:
        """Return the '<Ep no.> <runtime> <description>' line to append to your log file."""
        return f"{self.epnumber} {self.runtime} {self.description}\n"


    def download(self) -> bool:
        """Kick off yt-dlp download, block/poll untill done, set download_complete."""
        extra_flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
        try:
            with open(YTDLP_LOG, "a", encoding="utf-8") as logfile:
                subprocess.run([YT_DLP_BIN, "--js-runtimes", f"deno:{DENO_BIN}",
                                "--ignore-errors", "-f", "bv[vcodec^=avc1]+ba/bv[vcodec^=avc1]+ba",
                                "-o", str(self.filename), "--cookies-from-browser", "firefox",
                                "--merge-output-format", "mkv", "-P", str(Path.cwd()),
                                self.youtube_url], check=True, stdout=logfile, stderr=logfile, **extra_flags)
            return True
        except subprocess.CalledProcessError:
            with open(YTDLP_LOG, "a", encoding="utf-8") as logfile:
                logfile.write("\n\n\nyt-dlp failed to download the file\n\n\n")
            return False


    def fetch_runtime(self):
        """Get duration from the downloaded file itself via mkvmerge -J, set self.runtime in minutes."""

        try:
            result = subprocess.run(
                [MKVMERGE_BIN, "-J", str(self.filename)], capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            duration_ns = info["container"]["properties"]["duration"]
            duration_secs = duration_ns / 1_000_000_000
            self.runtime = str(math.ceil(duration_secs/60))   # e.g. 6:30 becomes 7, 5:01 becomes 6, 9:00 become 9. like this
        except subprocess.CalledProcessError:
            print("Mkvmerge failed to read the runtime of the file")
        except json.JSONDecodeError:
            print("Invalid Json type, couldnot convert it to Runtime duration")
        except KeyError:
            print("Duration Key is missing from returned json, please fill it manually")


    def scrub_and_tag(self):
        """Strip global tags, keep only videos/audio, rename audio stream + set 'bn' lang tag."""
        try:
            subprocess.run([
                        MKVPROPEDIT_BIN,
                        str(self.filename), "--tags", "all:",
                        "--edit", "info", "--set", "title=", "--edit", "track:a1",
                        "--set", "language=ben",
                        "--set", "name=[ বাংলা (Bengali) ]",
                    ], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            print("Mkvpropedit failed to edit the file")

class QueueManager:
    """Owns a queue.Queue of Episode objects; a background thread pulls one at a time
    and runs it through download -> runtime -> tag, so nothing touches yt-dlp/mkv tools
    concurrently."""

    def __init__(self, maxsize: int):
        self.q = queue.Queue(maxsize=maxsize) # maxsize = 0 means unbounded queue
        self.current = None          # the Episode currently being processed, if any
        self.stop_requested = False  # signal to let the worker thread exit cleanly
        self.worker_thread = None

    def start(self):
        """Spin up the background thread that continuously processes the queue."""
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        self.status_writer_thread = threading.Thread(target=self._status_writer, daemon=True)
        self.status_writer_thread.start()

    def _worker(self):
        """Runs in the background thread. Loop: get one Episode, process it, repeat."""
        while not self.stop_requested:
            ep = self.q.get()
            if ep is None:          # sentinel, see stop() below
                self.q.task_done()
                break
            self.current = ep
            ep.download_status = ep.download()
            
            if ep.download_status:
                ep.fetch_runtime()
                ep.scrub_and_tag()
            
            append_to_log(log= ep.log_entry())
            if not ep.download_status:
                append_to_linkbook(url= f"{ep.youtube_url} + NOT SUCCESSFUL!!")
            else:
                append_to_linkbook(url=ep.youtube_url)
            time.sleep(random.randint(3,8))
            self.current = None
            self.q.task_done()    # Next element

    def enqueue(self, ep) -> None:
        """Add an Episode to the queue. Blocks automatically if full — that's queue.Queue's job."""
        self.q.put(ep)


    def empty_slots(self) -> int:
        """How many more Episodes can be added before enqueue would block."""
        return self.q.maxsize - self.q.qsize()  # (careful: maxsize=0 means "unbounded" in queue.Queue)


    # Deleted Status memory

    def stop(self):
        """Signal the worker thread to finish after its current item and exit."""
        self.stop_requested = True
        self.q.put(None)

    # Status memory deleted so window is deleted too


    def snapshot(self) -> dict:
        """Convert current queue state into plain JSON-serializable data."""
        now_processing = self.current.epnumber if self.current else None
        now_title = self.current.title if self.current else None
        left_in_q = list(self.q.queue)
        upcoming = [{"epnumber": ep.epnumber, "title": ep.title} for ep in left_in_q]
        return {
            "now_processing_epnumber": now_processing,
            "now_processing_title": now_title,
            "queue_length": str(len(upcoming))+f"/{self.q.maxsize}",
            "upcoming": upcoming,
        }


    def _status_writer(self):
        """Runs in its own thread - periodically dumps snapshot() to a file for monitor.py to read."""
        while not self.stop_requested:
            snap = self.snapshot()
            with open(QUEUE_STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(snap, f, indent=2)
            time.sleep(1)


class InputPanel:
    """Keeps asking for episode number/URL/description and pushing Episodes into the
    QueueManager's queue, pausing with a message when there isn't enough room."""

    def __init__(self, manager: QueueManager, series: str, season: int, season_metadata: dict, min_free_slots: int = 2):
        self.manager = manager
        self.series = series
        self.season = season
        self.season_metadata = season_metadata
        self.min_free_slots = min_free_slots
        self.resting = False

    def wait_for_space(self, next_episode: int):
        """If fewer than min_free_slots are open, print a rest message and poll until there's room."""
        if self.manager.empty_slots() == 0:
            self.resting = True
        if self.resting:
            while self.manager.empty_slots() < self.min_free_slots:
                
                print(FUNNY_MSG[random.randint(0,len(FUNNY_MSG)-1)])
                print(f"You'll Enter {next_episode} Once the break ends")
                time.sleep(5)
                print("Checking if got any empty slots ")
            self.resting = False   # only clears once we've actually reached min_free_slots

    def run(self, start_epnumber: int):
        """Main input loop: build one Episode per iteration, enqueue it, repeat."""
        epnumber = start_epnumber
        print("(Type 'quit' at the URL prompt to stop adding episodes. Ctrl+C cancels just the current entry.)\n")
        try:
            while True:
                self.wait_for_space(epnumber) # Epnumber is the next episode cause we are stopping it before entering of epnumber
                ep = Episode(series=self.series, season=self.season, epnumber=epnumber)
                
                ep.fetch_metadata(tmdb_cache=self.season_metadata)
                if ep.title is None:
                    print("Metadata returned 'None' as Title. Either skip the episode and manually download the episode later or restart the program after exiting")
                    nter = input("Want to skip? if not then we would exit. [Y/n]:> ")
                    if nter in ["y", "Y", ""]:
                        print(f"Episode number {epnumber} is being skipped, moving to Episode number {epnumber+1}")
                        append_to_log(log= f"{epnumber} SKIPPED\n")
                        epnumber += 1
                        continue
                    else:
                        sys.exit()
                print(f"\nThis Episode is going to be downloaded:v\n{epnumber} : {ep.title}\n")
        
                ep.build_filename()
                try:
                    yt_url = input("YouTube URL (Click Share and copy from there), or 'quit' to stop:> ").strip()
                except KeyboardInterrupt:
                    print(f"\nCancelled — Episode {epnumber} will be asked again.")
                    continue

                if yt_url.lower() == "quit":
                    break

                if "youtu" not in yt_url.lower():
                    print("That doesn't look like a YouTube link.")
                    confirm = input("Use it anyway? [y/N]:> ").strip().lower()
                    if confirm != "y":
                        continue

                yt_url = re.sub(r"[?&]si=(.*)", "", yt_url)
                ep.youtube_url = yt_url

                try:
                    ep.description = input("Paste the description:> ").strip()
                except KeyboardInterrupt:
                    print(f"\nCancelled — Episode {epnumber} will be asked again.")
                    continue
                self.manager.enqueue(ep=ep)
                epnumber += 1
        except KeyboardInterrupt:
            print("Interrupted by User")


def load_metadata_tmdb(series_id: str, season:int) -> dict:
    """
    Return {episode_number: title} for the whole season.
    Check cache first; on miss , call TMDB once, cache result, return it.
    """

    TMDB_LINK = f"https://api.themoviedb.org/3/{TYPE}/{series_id}/season/{season}?api_key={TMDB_API}"

    data = {}

    # Check the file existence
    cache_file = Path("metadata.json")
    if cache_file.exists():
        last_cache_date = datetime.fromtimestamp(cache_file.stat().st_mtime)  # noqa: DTZ006
        fetch_succeeded = False
        while True:
            print(f"\n\nThere exists a previous cached matadata.\nLast fetched time:\t{last_cache_date.strftime("%Y-%m-%d %H:%M:%S")}")
            nter = input("\n\nDo you want to use that?\nif no then fresh metadata will be fetched. [Y/n]:> ")

            if nter in ["y", "Y", ""]:
                try:
                    with open(cache_file, "r") as file:
                        data = json.load(file)
                        if data: 
                            print("The file has been read successfully!")  # In the file we will contain only json part not the whole response. its already in json
                            break
                except json.JSONDecodeError:
                    print("The file exists but contains invalid JSON (corrupted or manually edited incorrectly)")
                    continue
                except PermissionError:
                    print("You dont have permission to read it.")
                    continue
                except OSError:
                    print("Other Filesystem-related errors (disk issues, invalid path, etc.).")
                    continue
            else:
                while True:
                    try:
                        response = requests.get(TMDB_LINK, timeout=20)
                        response.raise_for_status()
                    
                    except requests.exceptions.Timeout:
                        print("Request time out!")
                        nter = input("Want to retry?[Y/n]:> ")
                        if nter in ["y", "Y", ""]:
                            continue
                        else:
                            break
                    except requests.exceptions.ConnectionError:
                        print("Could not connect to TMDB")
                        nter = input("Want to retry? [Y/n]:> ")
                        if nter in ["y", "Y", ""]:
                            continue
                        else:
                            break
                    except requests.exceptions.HTTPError:
                        # pyrefly: ignore [unbound-name]
                        code = response.status_code
                        if code == 401:
                            print("Bad API Key\nRestart the program after correcting the API Key\nExiting...")
                            sys.exit()
                        elif code == 404:
                            print("Series Not found!\nRestart the program after correcting the API Key\nExiting...")
                            sys.exit()
                        else:
                            print(f"Unexpected Error: {code}")
                        nter = input("Want to retry? [Y/n]:> ")
                        if nter in ["y", "Y", ""]:
                            continue
                        else:
                            break

                    data = response.json()
                    if data:
                        try:
                            cache_file_backup = Path("metadatacopy.json")
                            shutil.copy2(cache_file, cache_file_backup) # (src,dest)
                            with open(cache_file, "w") as file:
                                json.dump(data, file, indent=4) # writing the json format in the json file
                                print("\n\nMetadata Successfully fetched and written in the file!")
                            fetch_succeeded = True
                            cache_file_backup.unlink()
                            break
                        except TypeError:
                            print("Your dictionary contains an object that JSON can't serialize (e.g. Path, set, custom class).")
                            cache_file.unlink()
                            # pyrefly: ignore [unbound-name]
                            cache_file_backup.rename("metadata.json")
                            break
                        except PermissionError:
                            print("Cannot write to the file or directory.")
                            cache_file.unlink()
                            # pyrefly: ignore [unbound-name]
                            cache_file_backup.rename("metadata.json")
                            break
                        except OSError:
                            print("Other Filesystem-related errors (disk issues, invalid path, etc.).")
                            cache_file.unlink()
                            # pyrefly: ignore [unbound-name]
                            cache_file_backup.rename("metadata.json")
                            break
                    else: # This case is unsuccessfull metadata fetch, three options either retry or reuse old data or exit.
                        print("\n\nBecause of some unexpected problems we couldn't fetch your fresh metadata.")
                        nter = input("Want to retry?[Y/n]:> ")
                        if nter in ["y", "Y", ""]:
                            continue
                        else:
                            nter = input("Want to exit? if not we will send you to use old data asking page. [Y/n]:> ")
                            if nter in ["y", "Y",""]:
                                sys.exit()
                            else:
                                break # exits from inner loop
            if fetch_succeeded:
                break # leave outer loop too — data is good, go use it
            else:                
                continue # go back to outer loop's top — re-ask about cached data
            # Now WE have the metadata if file EXISTS
    else:
        while True:
            try:
                print("Wait Fetching tmdb\n")
                response = requests.get(TMDB_LINK, timeout=20)
                response.raise_for_status()

            except requests.exceptions.Timeout:
                print("Request time out!")
                nter = input("Want to retry? if not then we would exit. [Y/n]:> ")
                if nter in ["y", "Y", ""]:
                    continue
                else:
                    sys.exit()

            except requests.exceptions.ConnectionError:
                print("Could not connect to TMDB")
                nter = input("Want to retry? if not then we would exit. [Y/n]:> ")
                if nter in ["y", "Y", ""]:
                    continue
                else:
                    sys.exit()
            
            except requests.exceptions.HTTPError:
                # pyrefly: ignore [unbound-name]
                code = response.status_code
                if code == 401:
                    reason = "Bad API Key"
                elif code == 404:
                    reason = "Series Not found!"
                else:
                    reason = code
                print(f"Unexpected Error: {reason}")
                nter = input("Want to retry? if not then we would exit. [Y/n]:> ")
                if nter in ["y", "Y", ""]:
                    continue
                else:
                    sys.exit()

            data = response.json()
            if data:
                try:
                    with open(cache_file, "w") as file:
                        json.dump(data, file, indent=4) # writing the json format in file
                        print("\n\nMetadata Successfully fetched and written in the file!")
                        break
                except TypeError:
                    print("Your dictionary contains an object that JSON can't serialize (e.g. Path, set, custom class).")
                    nter = input("Want to retry? if not then we would exit. [Y/n]:> ")
                    if nter in ["y", "Y", ""]:
                        continue
                    else:
                        sys.exit()
                except PermissionError:
                    print("Cannot write to the file or directory.")
                    nter = input("Want to retry? if not then we would exit. [Y/n]:> ")
                    if nter in ["y", "Y", ""]:
                        continue
                    else:
                        sys.exit()
                except OSError:
                    print("Other Filesystem-related errors (disk issues, invalid path, etc.).")
                    nter = input("Want to retry? if not then we would exit. [Y/n]:> ")
                    if nter in ["y", "Y", ""]:
                        continue
                    else:
                        sys.exit()
            else:
                print("\n\nBecause of some unexpected problems we couldn't fetch your fresh metadata.")
                nter = input("Want to retry? if not then we would exit. [Y/n]:> ")
                if nter in ["y", "Y", ""]:
                    continue
                else:
                    sys.exit()

    # After All of this we will either have the data in hand or we will exit the program
    metadata = {}
    for ep in data["episodes"]:
        metadata[ep["episode_number"]] = ep["name"]   # {Episode Number: Title}
    # We have the meta data dictionary now
    return metadata


def append_to_log(log: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{log}\n")
    except FileNotFoundError:
        print("The parent directory doesn't exist.")
    except PermissionError:
        print("No permission to create or modify the file, or the file is protected.")
    except IsADirectoryError:
        print("You gave a directory path instead of a file path.")
    except NotADirectoryError:
        print("Part of the path that should be a directory is actually a file.")
    except UnicodeEncodeError:
        print("The text can't be encoded using the specified encoding (unlikely with UTF-8, but possible with other encodings).")
    except TypeError:
        print("You passed something other than a string to write(), such as an int or dict.")
    except ValueError:
        print("You tried to write to a file that has already been closed, or you used an invalid mode.")
    except OSError:
        print("General operating system errors (disk full, invalid filename, I/O error, hardware problems, etc.).")

    
def append_to_linkbook(url: str):
    try:
        with open(LINKBOOK, "a", encoding="utf-8") as f:
            f.write(f"{url}\n")
    except FileNotFoundError:
        print("The parent directory doesn't exist.")
    except PermissionError:
        print("No permission to create or modify the file, or the file is protected.")
    except IsADirectoryError:
        print("You gave a directory path instead of a file path.")
    except NotADirectoryError:
        print("Part of the path that should be a directory is actually a file.")
    except UnicodeEncodeError:
        print("The text can't be encoded using the specified encoding (unlikely with UTF-8, but possible with other encodings).")
    except TypeError:
        print("You passed something other than a string to write(), such as an int or dict.")
    except ValueError:
        print("You tried to write to a file that has already been closed, or you used an invalid mode.")
    except OSError:
        print("General operating system errors (disk full, invalid filename, I/O error, hardware problems, etc.).")
    

def check_dependencies():
    global YT_DLP_BIN, DENO_BIN, MKVMERGE_BIN, MKVPROPEDIT_BIN
    YT_DLP_BIN = resolve_tool("yt-dlp", "YT_DLP_PATH")
    DENO_BIN = resolve_tool("deno", "DENO_PATH")
    MKVMERGE_BIN = resolve_tool("mkvmerge", "MKVMERGE_PATH")
    MKVPROPEDIT_BIN = resolve_tool("mkvpropedit", "MKVPROPEDIT_PATH")
    for label, path in [("yt-dlp", YT_DLP_BIN), ("deno", DENO_BIN),
                        ("mkvmerge", MKVMERGE_BIN), ("mkvpropedit", MKVPROPEDIT_BIN)]:
        try:
            subprocess.run([path, "--version"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            sys.exit(f"ERROR: found a path for {label} ('{path}') but running it failed.")

def spawn_console(pyfile: str):
    wt = shutil.which("wt")
    if os.name == "nt" and wt:
        return subprocess.Popen([wt, "-w", "0", "new-tab",
                                 "--tabColor", "#1E90FF" if pyfile == "monitor.py" else "#98FF98",
                                 "--title", "Processes" if pyfile == "monitor.py" else "Queue",
                                 sys.executable, pyfile])
    creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return subprocess.Popen([sys.executable, pyfile], creationflags=creationflags)

def main():
    series = SERIES  # Hardcoded
    series_id = SERIES_ID
    assert SEASON is not None
    season = SEASON
    STOP_FLAG.unlink(missing_ok=True)
    check_dependencies()
    assert series_id is not None
    season_metadata = load_metadata_tmdb(series_id=series_id, season=season)    # One TMDB call, cached
    while True:
        start = input("Enter the starting episode number:> ")
        if not start.isdigit():
            print("Enter Digits Only!!")
            input()
            continue
        epnumber = int(start)
        break
    Q = QueueManager(maxsize=10)
    assert series is not None
    Input = InputPanel(series=series, season=season, season_metadata=season_metadata, manager=Q)
    Q.start()
    monitor = spawn_console("monitor.py")
    Qmonitor = spawn_console("Qmonitor.py")
    InputPanel.run(Input, start_epnumber=epnumber)

    print("WAIT! Dont close the program rightnow!\n\nFinishing up remaining downloads in the queue...")
    Q.q.join()
    Q.stop()
    with open(QUEUE_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump({"now_processing_epnumber": None, "now_processing_title": "All done!",
                   "queue_length": "0/0", "upcoming": []}, f, indent=2)

    STOP_FLAG.touch()
    for proc, name in [(monitor, "monitor.py"), (Qmonitor, "Qmonitor.py")]:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print(f"{name} didn't exit on its own in time, closing it forcefully.")
            proc.terminate()
    STOP_FLAG.unlink(missing_ok=True)
    print("Now you can close")

if __name__ == "__main__":
    main()