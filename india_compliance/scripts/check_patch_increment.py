#!/usr/bin/env python3
"""Pre-commit guard: bump the patch counter when custom-field / property-setter
definitions change.

India Compliance (re)creates its Custom Fields and Property Setters through
``execute:`` patches in ``india_compliance/patches.txt``.  Frappe only re-runs a
patch when its full line changes, so each of those lines carries a trailing
``#<n>`` counter.  Whenever a field/property-setter definition changes, the
counter on the matching patch line MUST be incremented -- otherwise the
new/updated definitions are never synced onto existing sites.

This fails when a definition source file changes without a matching counter
bump.  It has two modes, both git-only:

* local (default): compares the staged index against HEAD -- for pre-commit.
* CI/PR (``--base <ref>``): compares HEAD against its merge base with ``<ref>``
  -- for a GitHub Actions check on the whole pull request, which a local
  ``git commit --no-verify`` cannot bypass.
"""

import argparse
import re
import subprocess
import sys

PATCHES_FILE = "india_compliance/patches.txt"

# Each rule maps a set of definition source files to the patch line that syncs
# them.  ``signature`` is a substring that uniquely identifies that line in
# patches.txt (module path + function keep custom-field lines distinct).
RULES = (
    {
        "label": "GST custom fields",
        "sources": ("india_compliance/gst_india/constants/custom_fields.py",),
        "signature": "gst_india.setup import create_custom_fields",
    },
    {
        "label": "GST property setters",
        "sources": ("india_compliance/gst_india/setup/property_setters.py",),
        "signature": "gst_india.setup import create_property_setters",
    },
    {
        "label": "Income Tax custom fields",
        "sources": ("india_compliance/income_tax_india/constants/custom_fields.py",),
        "signature": "income_tax_india.setup import create_custom_fields",
    },
    {
        "label": "Audit Trail custom fields",
        "sources": ("india_compliance/audit_trail/constants/custom_fields.py",),
        "signature": "audit_trail.setup import create_custom_fields",
    },
)

COUNTER_RE = re.compile(r"#(\d+)\s*$")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def staged_files():
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return {line for line in out.splitlines() if line}


def changed_files(base_rev, head_rev):
    out = git("diff", "--name-only", "--diff-filter=ACMR", base_rev, head_rev)
    return {line for line in out.splitlines() if line}


def merge_base(a, b):
    return git("merge-base", a, b).strip()


def read_patches(rev):
    """Return patches.txt contents at ``rev``.

    ``rev`` is the git revision before the ``:path`` separator -- "HEAD" for the
    last commit, or "" for the staged index copy (git spells the index as
    ``:path``).
    """
    try:
        return git("show", f"{rev}:{PATCHES_FILE}")
    except subprocess.CalledProcessError:
        return ""  # file absent at that rev (e.g. first commit)


def find_line(signature, content):
    for line in content.splitlines():
        if signature in line:
            return line
    return None


def counter_of(line):
    """Return the trailing #<n> counter of a patch line, or None if absent."""
    if line is None:
        return None
    match = COUNTER_RE.search(line)
    return int(match.group(1)) if match else None


def collect(base):
    """Return (changed_files, patches_before, patches_after) for the chosen mode."""
    if base:
        try:
            mb = merge_base(base, "HEAD")
        except subprocess.CalledProcessError:
            print(
                f"error: no merge base between {base!r} and HEAD; fetch the base "
                "branch first (e.g. actions/checkout with fetch-depth: 0).",
                file=sys.stderr,
            )
            sys.exit(1)
        return changed_files(mb, "HEAD"), read_patches(mb), read_patches("HEAD")

    # local pre-commit: staged index vs HEAD ("" is the index side of ``:path``)
    return staged_files(), read_patches("HEAD"), read_patches("")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Guard the patches.txt counters.")
    parser.add_argument(
        "--base",
        help="Base git ref to diff HEAD against (CI/PR mode). Omit for local "
        "pre-commit mode (staged index vs HEAD).",
    )
    args = parser.parse_args(argv)

    changed, before, after = collect(args.base)

    errors = []
    for rule in RULES:
        touched = [src for src in rule["sources"] if src in changed]
        if not touched:
            continue

        after_line = find_line(rule["signature"], after)
        before_counter = counter_of(find_line(rule["signature"], before))
        after_counter = counter_of(after_line)

        floor = before_counter if before_counter is not None else 0
        if after_counter is None or after_counter <= floor:
            errors.append(
                {
                    "rule": rule,
                    "touched": touched,
                    "before": before_counter,
                    "after": after_counter,
                    "line": after_line,
                }
            )

    if not errors:
        return 0

    print(f"\nDefinition changes require a patch counter bump in {PATCHES_FILE}:\n")
    for err in errors:
        rule = err["rule"]
        before = err["before"]
        nxt = (before if before is not None else 0) + 1
        print(f"  ✗ {rule['label']}")
        for src in err["touched"]:
            print(f"      changed: {src}")
        if err["line"] is None:
            print(f"      no patch line matching '{rule['signature']}' was found.")
        else:
            print(f"      line:    {err['line'].strip()}")
        if err["after"] is None and before is None:
            print(f"      action:  add a '#{nxt}' counter to that line.")
        else:
            shown = "removed" if err["after"] is None else err["after"]
            print(f"      action:  increment the counter ({before} → {nxt}); current staged value: {shown}.")
        print()

    print(
        "Frappe only re-runs a patch when its line changes, so bumping the\n"
        "counter is what triggers the field/property-setter sync on existing\n"
        "sites.  Add the counter bump to this change.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
