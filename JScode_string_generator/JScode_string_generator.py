import json
import os
import subprocess

url: str = ""
filename: str = ""
string: str = "const items = ["
print("Enter x in url to stop input")
while True:
    url = input("Enter url> ").strip()
    if url == "x":
        break
    filename = input("Enter filename> ").strip()
    if not filename.endswith(".pdf"):
        filename = f"{filename}" + ".pdf"
    # json.dumps escapes quotes/backslashes so the JS string literals stay valid
    item = "\n{ url: " + json.dumps(url) + ", file: " + json.dumps(filename, ensure_ascii=False) + " },"
    string += (item)

if string == "const items = [":
    print("No entries were added, nothing to generate.")
    raise SystemExit

string = string[:-1]
string = f"{string}" + "\n];\n"


forloop = """

for (const item of items) {
fetch(item.url)
  .then(r => r.blob())
  .then(blob => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = item.file;
    a.click();
    URL.revokeObjectURL(a.href);
  });
}
"""

code = string + forloop
subprocess.run("cls" if os.name == "nt" else "clear", shell=True, check=False)
print("="*50 + '\n\n')
print(code.strip())
print("\n\n" + "="*50)