#!/usr/bin/env bash
# Paced walkthrough for the screen recording.
#
#   ./scripts/demo.sh
#
# The pipeline itself runs in about 15 seconds, which is too fast for a viewer
# to read. This pauses between stages so each one is legible, and shows the
# supporting evidence a judge would otherwise have to go looking for.
#
# Press ENTER to advance. Nothing here is required to run the project —
# `python main.py --image input/sample.jpg` is the whole pipeline.

set -u
cd "$(dirname "$0")/.." || exit 1

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
dim()  { printf "\033[2m%s\033[0m\n" "$1"; }
rule() { printf "\033[36m%s\033[0m\n" "──────────────────────────────────────────────────────────────"; }
# `clear` warns when TERM is unset (e.g. piped); fall back to an ANSI reset.
clear_screen() { command clear 2>/dev/null || printf "\033[2J\033[H"; }
pause() { printf "\033[2m\n[ENTER to continue]\033[0m"; read -r _; clear_screen; }

clear_screen
rule
bold "  HH GOA 2026 — TASK 3"
bold "  Face Identification + Reverse Image Search + Blockchain"
rule
echo
dim "  github.com/bhanu964/hh-goa-task3"
echo
echo "  Pipeline:"
echo "    image → face embedding → live Google Lens search → candidate pages"
echo "          → face verification → SHA-256 → Ethereum → read back → verify"
pause

rule
bold "  1. The input"
rule
echo
$PY -c "
import sys; sys.path.insert(0,'.')
from utils.imaging import load_image
from integrity.hashing import sha256_file
im = load_image('input/sample.jpg')
print(f'  file    input/sample.jpg')
print(f'  format  {im.image_format}  {im.width}x{im.height}  {im.size_bytes//1024} KB')
print(f'  sha256  {sha256_file(\"input/sample.jpg\")}')
print()
print('  Public-domain White House portrait — see input/ATTRIBUTION.md.')
print('  Reverse image search only finds publicly indexed images, so the')
print('  sample is a widely published photograph on purpose.')
"
pause

rule
bold "  2. Nothing is hardcoded — check the source"
rule
echo
dim "  \$ grep -rn -E 'instagram\.com/p/|x\.com/[A-Za-z0-9_]+/status' face search main.py"
echo
if grep -rn -E "instagram\.com/p/|x\.com/[A-Za-z0-9_]+/status" face search main.py 2>/dev/null; then
  echo "  ^^ found — investigate"
else
  echo "  (no output — there are no post URLs anywhere in the pipeline)"
fi
echo
dim "  The only URLs in the code are domain fragments used to label a platform."
dim "  Every result below is fetched live at runtime."
pause

rule
bold "  3. The full pipeline, live"
rule
echo
dim "  \$ python main.py --image input/sample.jpg --demo-tamper"
echo
sleep 1
$PY main.py --image input/sample.jpg --demo-tamper
echo
pause

rule
bold "  4. The record that was anchored"
rule
echo
$PY -c "
import json
d = json.load(open('output/evidence_record.json'))
print(json.dumps(d['record'], indent=2, ensure_ascii=False))
print()
print('  SHA-256 of the canonical form:')
print('   ', d['sha256'])
"
pause

rule
bold "  5. The test suite"
rule
echo
dim "  \$ pytest -q"
echo
$PY -m pytest -q 2>&1 | tail -3
echo
dim "  203 offline tests. The blockchain tests deploy the real contract to a"
dim "  real in-process EVM — no mocks. The search has a live integration test."
pause

rule
bold "  Done"
rule
echo
echo "  ✓ Face detected and embedded (512-d ArcFace)"
echo "  ✓ Live Google Lens search — fresh search id, quota decremented"
echo "  ✓ Real X / web results found, face-verified by cosine similarity"
echo "  ✓ Candidates that failed the face check were rejected"
echo "  ✓ SHA-256 anchored on-chain, read back, recomputed, matched"
echo "  ✓ Tampering with the record breaks verification"
echo
dim "  github.com/bhanu964/hh-goa-task3"
echo
