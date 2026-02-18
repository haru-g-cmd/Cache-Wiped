#!/usr/bin/env python3
"""Cache Cleaner - Find and clean development caches to reclaim disk space."""

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import box

console = Console()

CACHE_TYPES = {
    "node": {
        "node_modules": (["node_modules"], "Node.js dependencies"),
        "node_cache": ([".cache", ".parcel-cache", ".next/cache", ".nuxt", ".turbo"], "Build caches"),
    },
    "python": {
        "pycache": (["__pycache__", "*.pyc"], "Python bytecode"),
        "venv": ([".venv", "venv", ".env", "env"], "Virtual environments"),
        "pytest": ([".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox"], "Test/lint caches"),
        "eggs": (["*.egg-info", ".eggs", "dist", "build"], "Build artifacts"),
    },
    "rust": {
        "target": (["target"], "Rust build output"),
    },
    "go": {
        "go_build": (["go-build"], "Go build cache"),
    },
    "java": {
        "gradle": ([".gradle", "build"], "Gradle cache"),
    },
    "dotnet": {
        "dotnet": (["bin", "obj"], ".NET build output"),
    },
    "misc": {
        "coverage": (["coverage", ".coverage", "htmlcov", ".nyc_output"], "Coverage reports"),
        "logs": (["*.log", "logs"], "Log files"),
        "temp": (["tmp", "temp", ".tmp"], "Temp files"),
        "os": ([".DS_Store", "Thumbs.db"], "OS files"),
    },
}

GLOBAL_CACHES = {
    "npm": lambda: Path.home() / ("AppData/Local/npm-cache" if os.name == "nt" else ".npm"),
    "yarn": lambda: Path.home() / ("AppData/Local/Yarn/Cache" if os.name == "nt" else ".cache/yarn"),
    "pip": lambda: Path.home() / ("AppData/Local/pip/cache" if os.name == "nt" else ".cache/pip"),
    "cargo": lambda: Path.home() / ".cargo/registry/cache",
    "go": lambda: Path.home() / ("AppData/Local/go-build" if os.name == "nt" else ".cache/go-build"),
}


def get_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total

def fmt_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}" if unit != "B" else f"{b} B"
        b /= 1024
    return f"{b:.1f} TB"

def get_config_path() -> Path:
    p = Path.home() / ".cacheclean"
    p.mkdir(exist_ok=True)
    return p


@dataclass
class Match:
    path: Path
    category: str
    cache_type: str
    size: int

def scan_dir(root: Path, categories: List[str] = None, max_depth: int = None, min_size: int = 1024*1024) -> List[Match]:

    matches = []
    seen = set()
    root = root.resolve()
    base_depth = len(root.parts)
    
    skip_dirs = {".git", ".hg", ".svn", "$RECYCLE.BIN", "Windows", "Program Files"}
    
    def scan(path: Path):
        if path in seen or not path.exists():
            return
        if path.name in skip_dirs:
            return
        if max_depth and len(path.parts) - base_depth > max_depth:
            return
        
        try:
            entries = list(path.iterdir())
        except PermissionError:
            return
        
        for entry in entries:
            if entry in seen:
                continue
            
            matched = False
            for cat, types in CACHE_TYPES.items():
                if categories and cat not in categories:
                    continue
                for type_name, (patterns, _) in types.items():
                    for pattern in patterns:
                        if pattern.startswith("*"):
                            if entry.name.endswith(pattern[1:]):
                                matched = True
                        elif entry.name == pattern:
                            matched = True
                        if matched:
                            size = get_size(entry)
                            if size >= min_size:
                                seen.add(entry)
                                matches.append(Match(entry, cat, type_name, size))
                            break
                    if matched:
                        break
                if matched:
                    break
            
            if not matched and entry.is_dir():
                scan(entry)
    
    scan(root)
    return sorted(matches, key=lambda m: m.size, reverse=True)

def scan_global(min_size: int = 1024*1024) -> List[Match]:
    matches = []
    for name, get_path in GLOBAL_CACHES.items():
        try:
            p = get_path()
            if p.exists():
                size = get_size(p)
                if size >= min_size:
                    matches.append(Match(p, "global", name, size))
        except Exception:
            pass
    return sorted(matches, key=lambda m: m.size, reverse=True)


def load_history() -> List[dict]:
    f = get_config_path() / "history.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text())
        # Handle old format with "sessions" key
        if isinstance(data, dict) and "sessions" in data:
            return data["sessions"]
        if isinstance(data, list):
            return data
        return []
    except:
        return []

def save_history(sessions: List[dict]):
    f = get_config_path() / "history.json"
    f.write_text(json.dumps(sessions[-100:], indent=2))  # Keep last 100

def add_session(scan_path: str, size: int, items: int, dry_run: bool):
    h = load_history()
    h.append({
        "date": datetime.now().isoformat()[:16],
        "path": scan_path,
        "size": size,
        "items": items,
        "dry_run": dry_run
    })
    save_history(h)


def show_results(matches: List[Match], scan_time: float):
    if not matches:
        console.print("[green]✓ No caches found![/green]")
        return
    
    total = sum(m.size for m in matches)
    
    console.print(Panel(
        f"Found [bold]{len(matches)}[/bold] items totaling [bold red]{fmt_size(total)}[/bold red]\n"
        f"Scan time: {scan_time:.1f}s",
        title="Scan Results"
    ))
    
    # By category
    by_cat: Dict[str, int] = {}
    for m in matches:
        by_cat[m.category] = by_cat.get(m.category, 0) + m.size
    
    t = Table(title="By Category", box=box.ROUNDED)
    t.add_column("Category")
    t.add_column("Size", justify="right", style="red")
    for cat, size in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
        t.add_row(cat.upper(), fmt_size(size))
    console.print(t)
    
    # Top items
    t = Table(title="Top 10 Largest", box=box.ROUNDED)
    t.add_column("#", width=3)
    t.add_column("Path")
    t.add_column("Type")
    t.add_column("Size", justify="right", style="red")
    for i, m in enumerate(matches[:10], 1):
        path_str = str(m.path)
        if len(path_str) > 50:
            path_str = "..." + path_str[-47:]
        t.add_row(str(i), path_str, m.cache_type, fmt_size(m.size))
    console.print(t)

def clean_matches(matches: List[Match], dry_run: bool, scan_path: str, skip_confirm: bool = False):
    """Clean matched caches."""
    if not matches:
        return
    
    total = sum(m.size for m in matches)
    
    if dry_run:
        console.print(Panel(
            f"[yellow]DRY RUN[/yellow] - Would free [bold]{fmt_size(total)}[/bold]\n"
            f"Use [bold]-x[/bold] to actually delete",
            title="Preview", border_style="yellow"
        ))
        add_session(scan_path, total, len(matches), True)
        return
    
    if not skip_confirm:
        console.print(f"\n[bold red]About to delete {len(matches)} items ({fmt_size(total)})[/bold red]")
        if not click.confirm("Proceed?"):
            console.print("[yellow]Aborted[/yellow]")
            return
    
    freed = 0
    deleted = 0
    
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TaskProgressColumn()) as prog:
        task = prog.add_task("Cleaning...", total=len(matches))
        for m in matches:
            try:
                if m.path.is_file():
                    m.path.unlink()
                else:
                    shutil.rmtree(m.path)
                freed += m.size
                deleted += 1
            except Exception:
                pass
            prog.advance(task)
    
    console.print(Panel(
        f"[green]✓ Deleted {deleted}/{len(matches)} items[/green]\n"
        f"Freed [bold green]{fmt_size(freed)}[/bold green]",
        title="Done", border_style="green"
    ))
    add_session(scan_path, freed, deleted, False)


@click.group(invoke_without_command=True)
@click.option("-v", "--version", is_flag=True)
@click.pass_context
def cli(ctx, version):
    """Dev Cache Cleaner - Reclaim disk space from dev caches."""
    if version:
        console.print("cacheclean v1.0.0")
        return
    if ctx.invoked_subcommand is None:
        ctx.invoke(scan)

@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("-x", "--execute", is_flag=True, help="Actually delete (default is dry-run)")
@click.option("-g", "--global", "incl_global", is_flag=True, help="Include global caches")
@click.option("-c", "--category", multiple=True, help="Filter by category")
@click.option("--max-depth", type=int, help="Max scan depth")
@click.option("--min-size", default="1MB", help="Min size to show")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
def scan(path, execute, incl_global, category, max_depth, min_size, yes):
    """Scan for caches. Dry-run by default."""
    console.print("[bold blue]Dev Cache Cleaner[/bold blue]\n")
    
    # Parse min size
    min_bytes = 1024 * 1024
    ms = min_size.upper()
    if ms.endswith("GB"):
        min_bytes = int(float(ms[:-2]) * 1024**3)
    elif ms.endswith("MB"):
        min_bytes = int(float(ms[:-2]) * 1024**2)
    elif ms.endswith("KB"):
        min_bytes = int(float(ms[:-2]) * 1024)
    
    cats = list(category) if category else None
    
    console.print(f"Scanning: {Path(path).resolve()}")
    start = time.time()
    
    with console.status("[bold]Scanning..."):
        matches = scan_dir(Path(path), cats, max_depth, min_bytes)
        if incl_global:
            matches.extend(scan_global(min_bytes))
            matches.sort(key=lambda m: m.size, reverse=True)
    
    show_results(matches, time.time() - start)
    clean_matches(matches, not execute, str(Path(path).resolve()), yes)

@cli.command()
@click.option("-n", "--limit", default=10)

def history(limit):
    h = load_history()
    if not h:
        console.print("[yellow]No history yet[/yellow]")
        return
    
    t = Table(title="History", box=box.ROUNDED)
    t.add_column("Date")
    t.add_column("Path")
    t.add_column("Size", style="green")
    t.add_column("Mode")
    
    for s in reversed(h[-limit:]):
        # Handle both old and new format
        date = s.get("date") or s.get("timestamp", "")[:16]
        path = s.get("path") or s.get("scan_path", "")
        size = s.get("size") or s.get("total_size_bytes", 0)
        dry = s.get("dry_run", True)
        
        t.add_row(
            date,
            path[-40:] if len(path) > 40 else path,
            fmt_size(size),
            "DRY RUN" if dry else "CLEANED"
        )
    console.print(t)

@cli.command()
def stats():
    h = load_history()
    cleaned = [s for s in h if not s.get("dry_run", True)]
    total = sum(s.get("size") or s.get("total_size_bytes", 0) for s in cleaned)
    
    console.print(Panel(
        f"Sessions: {len(h)}\n"
        f"Actually cleaned: {len(cleaned)}\n"
        f"[bold green]Total space saved: {fmt_size(total)}[/bold green]",
        title="Stats"
    ))

@cli.command("types")
def list_types():
    t = Table(title="Cache Types", box=box.ROUNDED)
    t.add_column("Category")
    t.add_column("Type")
    t.add_column("Patterns")
    
    for cat, types in CACHE_TYPES.items():
        for name, (patterns, _) in types.items():
            t.add_row(cat, name, ", ".join(patterns[:3]))
    console.print(t)

if __name__ == "__main__":
    cli()
