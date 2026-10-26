import json
import os
import re
import subprocess

illegal = re.compile(r'[<>:"/\\|?*]|[\x00-\x1f]')
def legalfile(filename: str) -> str:
    sanitized = re.sub(illegal, ' ', filename)
    # Handle reserved names by prepending an underscore
    reserved = r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$'
    if re.match(reserved, sanitized.upper()):
        sanitized = '_' + sanitized
    # Remove leading and trailing dots
    sanitized = re.sub(r'^[. ]+|[. ]+$', "", sanitized)
    return sanitized
url: str = ""
filename: str = ""
string: str = "const items = ["
subprocess.run("cls" if os.name == "nt" else "clear", shell=True, check=False)
print("Enter x in url to stop input")
while True:
    url = input("Enter url> ").strip()
    if url == "x":
        break
    filename = legalfile(input("Enter filename> ").strip())
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}" + ".pdf"
    # json.dumps escapes quotes/backslashes so the JS string literals stay valid
    item = "\n{ url: " + json.dumps(url) + ", file: " + json.dumps(filename, ensure_ascii=False) + " },"
    string += (item)

if string == "const items = [":
    print("No entries were added, nothing to generate.")
    raise SystemExit

string = string[:-1]
string = f"{string}" + "\n];\n"


forloop = r"""
console.log("Starting Downloads...")
const jobs = items.map(item =>
  fetch(item.url)
    .then(r => r.blob())
    .then(blob => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = item.file;
      a.click();
      URL.revokeObjectURL(a.href);
    })
    .catch(err => console.error("Failed:", item.file, err))
);
Promise.all(jobs).then(() => {
    console.log("All files fetched and handed to the browser.\n")
    console.log("Check your browser's downloads list to make sure every file finished saving.")
});
"""

code = string + forloop
subprocess.run("cls" if os.name == "nt" else "clear", shell=True, check=False)
print("="*50 + '\n\n')
print(code.strip())
print("\n\n" + "="*50)


# 01001101 01100001 01100100 01100101 00100000
# 01110111 01101001 01110100 01101000 00100000
# 11110000 10011111 10010001 10111011 00100000
# 01100110 01101111 01110010 00100000
# 01010100 01010100 01001001
