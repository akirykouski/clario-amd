"""Files that exist twice because train/ must stay standalone. Edit one, copy to the other."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIRRORS = [
    ("train/lay_terms.json", "backend/clario/data/lay_terms.json"),
    ("train/prompt.py", "backend/clario/prompt.py"),
]


def test_mirrored_files_are_byte_identical():
    for a, b in MIRRORS:
        assert (ROOT / a).read_bytes() == (ROOT / b).read_bytes(), f"{a} and {b} differ: copy one over the other"
