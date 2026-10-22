#!/usr/bin/env python3
"""Compare two pytest JUnit XML reports and list tests that newly fail or were fixed.

Usage: compare_junit.py BASELINE.xml CANDIDATE.xml
Exits non-zero if the candidate has failures that the baseline does not have.
"""
import sys
import xml.etree.ElementTree as ET


def failing(path):
    failed = {}
    for case in ET.parse(path).iter('testcase'):
        problems = case.findall('failure') + case.findall('error')
        if problems:
            name = f"{case.get('classname')}::{case.get('name')}"
            failed[name] = (problems[0].get('message') or '').splitlines()[0][:160] if problems[0].get('message') else ''
    return failed


def main(baseline, candidate):
    base, cand = failing(baseline), failing(candidate)
    new = sorted(set(cand) - set(base))
    fixed = sorted(set(base) - set(cand))
    print(f'baseline failures: {len(base)}, candidate failures: {len(cand)}')
    print(f'\nnew failures ({len(new)}):')
    for name in new:
        print(f'  {name}\n      {cand[name]}')
    print(f'\nfixed ({len(fixed)}):')
    for name in fixed:
        print(f'  {name}')
    return 1 if new else 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
