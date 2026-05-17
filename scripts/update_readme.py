"""
update_readme.py
Fetch real GitHub data via API, then inject it into README.md.
Dijalankan oleh GitHub Actions setiap hari atau setiap push.
"""

import os
import re
import requests
from collections import defaultdict
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ["GH_TOKEN"]          # dari GitHub Actions secret
USERNAME     = os.environ.get("GITHUB_ACTOR", "faat-prasojo")  # otomatis dari Actions
HEADERS      = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json", 
    "X-GitHub-Api-Version": "2022-11-28",
}

# Warna hex per bahasa (untuk badge di README)
LANG_COLORS = {
    "PHP":        "#777BB4",
    "JavaScript": "#F7DF1E",
    "HTML":       "#E34F26",
    "CSS":        "#1572B6",
    "Blade":      "#FF2D20",
    "Python":     "#3572A5",
    "C++":        "#00599C",
    "C":          "#555555",
    "Shell":      "#89e051",
    "TypeScript": "#3178C6",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_repos(username: str) -> list[dict]:
    """Ambil semua public repo milik user (bukan fork)."""
    repos = []
    page  = 1
    while True:
        r = requests.get(
            f"https://api.github.com/users/{username}/repos",
            headers=HEADERS,
            params={"per_page": 100, "page": page, "type": "owner"},
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        # Exclude fork, hanya hitung repo sendiri
        repos.extend(repo for repo in batch if not repo.get("fork", False))
        page += 1
    return repos


def get_language_bytes(repos: list[dict]) -> dict[str, int]:
    """
    Fetch breakdown bahasa (dalam bytes) dari tiap repo.
    GitHub API /repos/{owner}/{repo}/languages mengembalikan dict {lang: bytes}.
    """
    totals: dict[str, int] = defaultdict(int)
    for repo in repos:
        url = repo["languages_url"]
        r   = requests.get(url, headers=HEADERS)
        if r.status_code != 200:
            continue
        for lang, byte_count in r.json().items():
            totals[lang] += byte_count
    return dict(totals)


def compute_percentages(lang_bytes: dict[str, int], top_n: int = 6) -> list[tuple[str, float]]:
    """Konversi bytes → persentase, ambil top N bahasa."""
    total = sum(lang_bytes.values())
    if total == 0:
        return []
    sorted_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)
    top          = sorted_langs[:top_n]
    result       = [(lang, round(count / total * 100, 1)) for lang, count in top]
    return result


def get_tech_stack(repos: list[dict]) -> dict[str, list[str]]:
    """
    Deteksi framework/tools dari topics dan nama repo.
    GitHub repo topics harus di-set manual, tapi kita juga scan nama repo.
    Return dict berisi kategori → list tech.
    """
    topic_counts: dict[str, int] = defaultdict(int)

    for repo in repos:
        # topics adalah list string seperti ["laravel", "tailwindcss", ...]
        for topic in repo.get("topics", []):
            topic_counts[topic.lower()] += 1

    # Mapping topic → nama display yang rapi
    TOPIC_MAP = {
        "laravel":      ("Laravel",     "Framework"),
        "tailwindcss":  ("Tailwind CSS","Framework"),
        "bootstrap":    ("Bootstrap",   "Framework"),
        "react":        ("React",       "Framework"),
        "vue":          ("Vue.js",      "Framework"),
        "nextjs":       ("Next.js",     "Framework"),
        "mysql":        ("MySQL",       "Database"),
        "postgresql":   ("PostgreSQL",  "Database"),
        "sqlite":       ("SQLite",      "Database"),
        "docker":       ("Docker",      "DevOps"),
        "git":          ("Git",         "Tools"),
        "rest-api":     ("REST API",    "Architecture"),
        "api":          ("REST API",    "Architecture"),
        "javascript":   ("JavaScript",  "Language"),
        "php":          ("PHP",         "Language"),
    }

    categories: dict[str, set] = defaultdict(set)
    for topic, (display, category) in TOPIC_MAP.items():
        if topic_counts.get(topic, 0) > 0:
            categories[category].add(display)

    # Convert set → sorted list
    return {cat: sorted(techs) for cat, techs in categories.items()}


# ── README Builder ────────────────────────────────────────────────────────────

def build_lang_section(lang_pcts: list[tuple[str, float]]) -> str:
    """Buat blok Markdown untuk language usage dengan progress bar ASCII."""
    if not lang_pcts:
        return "_No language data found yet._\n"

    lines = ["```"]
    for lang, pct in lang_pcts:
        color = LANG_COLORS.get(lang, "#888888")
        # Progress bar ASCII: 20 karakter lebar
        filled = round(pct / 5)   # 100% = 20 blok
        bar    = "█" * filled + "░" * (20 - filled)
        lines.append(f"  {lang:<14} {bar}  {pct:>5.1f}%")
    lines.append("```")
    return "\n".join(lines)


def build_stack_section(stack: dict[str, list[str]]) -> str:
    """Buat blok Markdown untuk tech stack berdasarkan repo topics."""
    if not stack:
        return "_No topics detected. Add topics to your repos on GitHub!_\n"

    lines = []
    # Urutan kategori yang diinginkan
    order = ["Language", "Framework", "Database", "DevOps", "Architecture", "Tools"]
    for category in order:
        techs = stack.get(category)
        if not techs:
            continue
        badges = " ".join(
            f"`{t}`" for t in techs
        )
        lines.append(f"**{category}** — {badges}  ")

    return "\n".join(lines)


def inject_section(readme: str, marker: str, content: str) -> str:
    """
    Ganti konten di antara dua marker HTML comment.
    Marker format: <!-- START:marker --> ... <!-- END:marker -->
    """
    pattern = rf"(<!-- START:{marker} -->).*?(<!-- END:{marker} -->)"
    replacement = rf"\1\n{content}\n\2"
    new_readme, count = re.subn(pattern, replacement, readme, flags=re.DOTALL)
    if count == 0:
        print(f"  [WARN] Marker '{marker}' tidak ditemukan di README.")
    return new_readme


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}] Fetching GitHub data for @{USERNAME}...")

    # 1. Fetch repos
    print("  → Fetching repositories...")
    repos = get_repos(USERNAME)
    print(f"     Found {len(repos)} original repos (forks excluded)")

    # 2. Language bytes
    print("  → Fetching language breakdown...")
    lang_bytes = get_language_bytes(repos)
    lang_pcts  = compute_percentages(lang_bytes, top_n=6)
    print(f"     Top languages: {[f'{l}({p}%)' for l, p in lang_pcts]}")

    # 3. Tech stack dari topics
    print("  → Detecting tech stack from repo topics...")
    stack = get_tech_stack(repos)
    print(f"     Detected: {stack}")

    # 4. Build section strings
    lang_md  = build_lang_section(lang_pcts)
    stack_md = build_stack_section(stack)
    updated  = f"_Last updated: {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}_"

    # 5. Inject ke README
    print("  → Updating README.md...")
    with open("README.md", "r", encoding="utf-8") as f:
        readme = f.read()

    readme = inject_section(readme, "LANG_USAGE", lang_md)
    readme = inject_section(readme, "TECH_STACK", stack_md)
    readme = inject_section(readme, "LAST_UPDATED", updated)

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme)

    print("  ✓ README.md updated successfully.")


if __name__ == "__main__":
    main()
