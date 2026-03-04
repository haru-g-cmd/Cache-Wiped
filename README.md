# Cache Wiped

CLI tool that scans your system for package manager caches and shows you how much space they're taking up. Covers seven ecosystems: npm, pip, conda, Maven, Gradle, cargo, and Go modules. Runs as a dry run by default so nothing gets deleted unless you pass `--clean`. You can filter by ecosystem with `--type` and review past clean operations with `--history`. Everything shows up in a color coded table sorted by size.

On startup it resolves cache paths for each ecosystem using environment variables and platform specific defaults (handles Linux, macOS, and Windows). Each directory gets scanned recursively to total up the size. The `--clean` flag deletes selected caches with `shutil.rmtree`. Every clean operation is logged to `~/.cacheclean/history.json` with a timestamp and bytes freed. Permission errors and missing directories are caught without crashing.

Python, Click, Rich

```bash
pip install click rich
```

```bash
python cache.py                  # dry run
python cache.py --clean          # delete caches
python cache.py --type npm pip   # only specific ecosystems
python cache.py --history        # view past clean operations
```
