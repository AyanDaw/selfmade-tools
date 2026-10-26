<div align="center">

# 🧰 selfmade-tools

### small scripts for chores that annoyed me enough to automate

![Python](https://img.shields.io/badge/python-3-3776AB?style=flat-square&logo=python&logoColor=white)
![Tools](https://img.shields.io/badge/tools-5-blue?style=flat-square)
![Made by](https://img.shields.io/badge/made%20by-hand%20%26%20spite-brightgreen?style=flat-square)
![Scope](https://img.shields.io/badge/scope-narrow%20on%20purpose-lightgrey?style=flat-square)
![Yapping](https://img.shields.io/badge/yapping-heavy-ff69b4?style=flat-square)

[**📖 Author's Note**](#author-note) · [**🧰 The Tools**](#tools) · [**🚀 Getting Started**](#getting-started) · [**🛡️ Use Responsibly**](#responsible-use)

</div>

---

<a id="author-note"></a>

## 📝 A note from the author

> [!WARNING]
> 🗣️
> **Yapping ahead.** The note below is long, honest and slightly unhinged. Skip to [the tools](#tools) if you only came for the code. I won't be offended. *(I will be slightly offended. 😤)*
>
> I love to **YAP**. *(yapping noises: yap yap yap yap yap yap yap yap yap...)*

👋 *Hi. I'm an odd person with a weird mindset, and I'm a* 🐍 *Python learner* 🤓 *who implements whatever he learns, usually the same day (nobody asked me to, not even me). One rule runs my whole life: if a task needs logic and not emotional intelligence, a machine should be doing it.*

*Here's the thing. I like doing stuff uniformly: every item in the same order, same rules, zero exceptions. But I'm very forgetful, lazy and, shocking twist, also a human, so I mess up. And I hate messing up. Following my own strict rules like a robot for hours is hectic, slow and honestly braindead. (A lazy, forgetful human cannot do it. I tried. Many times. Ask my old folders.) So I hand the job to* 🐍*, and watching a miserable task finish faster and more correctly than I ever could makes me stupidly happy. That's why I love programs and programming.* 🥹

*Strangely, I found out that in Python you can automate basically anything you can do on a PC* 💻*, even the tiniest things. So I did. A job that costs me 10 days by hand might take 20 days to write as code, and then it finishes in 10 seconds. (Yes, the maths is bad. No, I don't care. Those 10 seconds are the best part of my 3 weeks of grinding* 😌*.)*

*I'm an archiver* 📦 *and a homelabber* 🤓*, so repetitive work follows me everywhere. And before you say "just use PowerToys—": shut up! I know, it renames stuff with regex and it's great. But merging a batch of 3 seasons with 40+ episodes each (yeah, it’s one of my favourite animes), in 4 languages, with proper audio stream names? Or scraping a site's PDFs in batch for my own offline copy (yeah, just for ME, only me)? That's big, boring, braindead and extremely personal work. No app does my version of it. So a script does.*

🎢 *One more reason, and it's a bit emotional: I don't enjoy apps that were made by AI or by someone I don’t know. There's no feel behind them, no satisfaction of my own, no dopamine rush from building the thing. So even when the same tool exists online everywhere, I'd rather do it natively, with insane speed and the highest privacy, and know it's mine. By now you've probably guessed that I have sort of ADHD (Who said It's bad? it’s a gift from God for me* 😇*) and probably a few other things, plus a very healthy ego problem. (Self-diagnosed vibes, not a doctor's note* 💀*.) I know I'm insane. That's why you'll find 500+ lines of code for a simple subtitle downloader from a "specific site"* 💀*. (Yes, more than 500. For just SUBTITLES.)*

*I also just like scraping. Whenever something I should be able to keep for life only exists as a stream, I save my own copy. (Personal archiving only, relax. See the disclaimer at the bottom.) So yeah, that's how all of this was made.*

🏠 *Why a repo? These tools were just sitting on my PC and I figured other people might like them too. Some of them grew up into proper repos of their own (hi, [Epidex](https://github.com/AyanDaw/epidex)* 👋*). Others are too tiny to even call a repo, so they all live together here. It also keeps my tools in sync across my own devices* 💻*, and if you find something useful in here, I'm happy too* 😇*.*

🔍 *Take what's useful, and read the code before you run it. Good advice for anything that touches your files or your cookies. (Yes, even mine. Especially mine.)*

*Some aren’t uploaded here yet, but they will be* 👀

🙏 *Thanks for giving time to this yapping. And thanks in advance if you want to contribute in any way: an issue, an idea, a bug report, a better regex, a kind word. All of it is welcome.*

---

<a id="tools"></a>

## 🧰 The tools

| | Tool | What it does | Needs |
|:-:|---|---|---|
| 🎞️ | [`2srtconverter`](./2srtconverter/) | Converts a whole folder of `.vtt` subtitles to `.srt`, keeping the exact same file names | Python 3.8+, nothing else |
| 📥 | [`hsub_downloader`](./hsub_downloader/) | Saves every subtitle track of one episode from a very specific streaming site | Python 3.10+, `curl_cffi`, `rich` |
| 🧩 | [`JScode_string_generator`](./JScode_string_generator/) | Turns links and filenames into one block of JavaScript that saves the files from your browser console | Python 3, nothing else |
| 🔍 | [`sub_copy_checker`](./sub_copy_checker/) | Compares copies of the same subtitle file and shows exactly where they differ, down to the character | Python 3.6+, nothing else |
| 📺 | [`nonfondownloader`](./nonfondownloader/) | Queue-driven downloader, tagger and logger for YouTube episodes, built on yt-dlp and MKVToolNix | Python 3.12+, `requests`, `python-dotenv`, `rich`, plus external tools |

Each tool has its own folder with its own README: examples, options and known limits.

*(So you can skip these short yappings below here. There’s yapping there too, just less.)*

---

### 🎞️ 2srtconverter
<details>
<summary><b>Origin Yapping</b></summary>

> 💢 **Reason:** VLC didn't support `.vtt` back then.
>
> 😮‍💨 **Effect:** for mass compatibility, I had to turn the files into `.srt` one by one on some online site.
>
> 🚀 **Aftereffect:** now I convert a whole folder in batch at insane speed. Wooohooooo!
>
> *(The day after I finished it, I heard that VLC supports `.vtt` now too. Like... seriously?? 🫩 Still happy though 😊. Long live VLC, my GOAT.)*
</details>

Point it at a folder, press Enter, and every `.vtt` comes out as an `.srt` with the same name, so language tags like `episode.ar.vtt` survive. It skips the parts of WebVTT that aren't subtitles, reports every file it can't convert, and carries on with the rest.

```bash
python 2srtconverter.py
```

### 📥 hsub_downloader
<details>
<summary><b>Origin Yapping</b></summary>

> 💢 **Reason:** iykyk, fellow weeb. 💀 The player lets you *watch* 25 languages of subtitles, but not *save* them. Rude.
>
> 😮‍💨 **Effect:** I tried downloading them one by one, but after all that yapping you already know how that went.
>
> 🚀 **Aftereffect:** I give it an episode page and it hands me every subtitle track. No more digging links out of a network tab like an animal.
</details>

Give it the episode page plus a "Copy as cURL" from your own browser, and it saves every subtitle track as `<episode>.<lang>.vtt`. Four downloads at a time, a live progress panel, a check that each file really is WebVTT, and it can continue after a stop. One site, one episode per run.

```bash
python hsub_downloader.py
```

### 🧩 JScode_string_generator
<details>
<summary><b>Origin Yapping</b></summary>

> 💢 **Reason:** back then I had no idea how to scrape in batch using JS and Python together.
>
> 😮‍💨 **Effect:** If you read the previous yapping, you already know why I created this.
>
> 🚀 **Aftereffect:** this tiny generator writes the JavaScript **for me**, so I only paste links and filenames. It's kind of the **predecessor of hsub_downloader**, if you squint. *(Every legend has a humble origin story. This is mine. It's about 70 lines.)*
</details>

It asks for a URL and a filename, over and over, then prints one block of JavaScript. You paste it into the browser console on the site and the browser saves every file. It doesn't download anything itself.

```bash
python JScode_string_generator.py
```

### 🔍 sub_copy_checker
<details>
<summary><b>Origin Yapping</b></summary>

> 💢 **Reason:** I used to scrape Pokémon episodes in various languages, from where? YouTube, obviously, my beloved scrapyard. My folder kept getting bloated with the same subtitle again and again, and as an anxiety patient *(yes, I'm an "anxietian" too)* I couldn't delete anything without checking first.
>
> 🚀 **Aftereffect:** the computer does the staring now, and I get to delete things in peace.
>
> ⚠️ **Honest warning:** this one is mostly **vibe coded**. *(Yes, after all that "I don't like AI apps" yapping above. I know. I KNOW. 🙈)*
</details>

Give it two or more subtitle files (`.srt`, `.vtt`, `.ass`, `.ssa`, `.sub`, `.sbv`). It groups identical copies and reports every difference: numbers, timestamps, dialogue and styles. Differing characters are shown with their Unicode code points, which exposes look-alike and invisible differences.

```bash
python sub_copy_checker.py
```

### 📺 nonfondownloader
<details>
<summary><b>Origin Yapping</b></summary>

> 💢 **Reason:** I wanted to make an archive of **Nonte Fonte**, and I was filling in its info on TMDB at the same time.
>
> 😮‍💨 **Effect:** I made it to grab every episode of **Nonte Fonte** from YouTube for my home server and my archive. *(Yes, the name is kinda weird, I know. It's the first thing I ever built, leave me alone.)*
>
> 🚀 **Aftereffect:** I type in the next episode while the last one downloads, gets named, tagged and logged. It can do more than that now.
</details>

A producer/consumer queue on top of yt-dlp and MKVToolNix: official episode titles from TMDB, clean MKV output, automatic tagging and runtime, plus two live monitor windows (`monitor.py` and `Qmonitor.py`).

> [!IMPORTANT]
> **`nonfondownloader` is superseded by [Epidex](https://github.com/AyanDaw/epidex).** If something breaks in it, try **Epidex** first. It's the better, more capable version, and it's where the active development lives.

```bash
python nonfondownloader.py
```

---

<a id="getting-started"></a>

## 🚀 Getting started

```bash
git clone https://github.com/AyanDaw/selfmade-tools
cd selfmade-tools
python -m venv .venv
```

Activate the environment (`source .venv/bin/activate` on Linux and macOS, `.venv\Scripts\activate` on Windows), then install the shared libraries:

```bash
pip install -r requirements.txt
```

Then open the folder of the tool you want and follow its README.

> [!TIP]
> `2srtconverter`, `JScode_string_generator` and `sub_copy_checker` only use Python's standard library, so they run with no install at all. `nonfondownloader` also needs `python-dotenv` and some external programs (yt-dlp, deno, MKVToolNix); its README lists them all.

<details>
<summary><b>📁 Repository layout</b></summary>

```text
selfmade-tools/
├── 2srtconverter/             # .vtt to .srt, a whole folder at a time
├── hsub_downloader/           # subtitle tracks of one episode, from one site
├── JScode_string_generator/   # builds a browser-console download snippet
├── nonfondownloader/          # queue downloader + monitors (superseded by Epidex)
├── sub_copy_checker/          # finds how copies of a subtitle file differ
├── requirements.txt           # shared Python libraries
├── .gitignore
└── README.md
```

</details>

---

<a id="responsible-use"></a>

## 🛡️ Responsible use

> [!CAUTION]
>
> These tools are for **personal archiving** of content you are entitled to access and keep. Respect the terms of use of every site you work with and the laws where you live. You are responsible for how you use them.
>
> `hsub_downloader` and the code from `JScode_string_generator` work with **your** cookies and **your** login. Keep those private, and never share a saved cURL file.

## 🌱 Status

A personal repo, built and maintained at my own pace. New tools show up when a new annoyance earns one. They stay small on purpose.

---
<div align="center">

*made with spite, annoyance, regex and way too much yapping* 💙

</div>
