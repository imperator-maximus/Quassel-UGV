#!/usr/bin/env python3
"""Erzeugt die Sprachansagen des Fahrzeugs aus ``announcements.json``.

Laeuft auf dem Entwicklungsrechner, nie auf dem Fahrzeug: fal.ai liefert MP3,
ffmpeg macht daraus 48-kHz-Stereo-WAV. Aufs Fahrzeug kommt nur das WAV - dort
gibt es weder Netz noch Decoder noch API-Schluessel.

    python tools/voice/generate_voice.py [--only KEY ...] [--force]

Braucht FAL_KEY in der Umgebung und ffmpeg im Pfad.
"""

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
CATALOG = HERE / 'announcements.json'
OUT_DIR = HERE.parents[1] / 'raspberry_pi' / 'motor_controller' / 'audio'

# Der USB-Stick am Fahrzeug nimmt nur Stereo an; Mono scheitert an
# "Channels count non available", sobald jemand hw: statt plughw: benutzt.
SAMPLE_RATE = 48000
CHANNELS = 2


def synthesize(text: str, cfg: dict, key: str) -> bytes:
    payload = {
        'text': text,
        'voice': cfg['voice'],
        'language_code': cfg['language_code'],
        'speed': cfg.get('speed', 1.0),
    }
    request = urllib.request.Request(
        'https://fal.run/' + cfg['model'],
        data=json.dumps(payload).encode(),
        headers={'Authorization': 'Key ' + key, 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    url = result.get('audio', {}).get('url')
    if not url:
        raise RuntimeError(f'keine Audio-URL in der Antwort: {str(result)[:200]}')
    with urllib.request.urlopen(url, timeout=180) as response:
        return response.read()


def to_wav(mp3: bytes, dest: pathlib.Path, ffmpeg: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, '-y', '-loglevel', 'error', '-f', 'mp3', '-i', 'pipe:0',
         '-ar', str(SAMPLE_RATE), '-ac', str(CHANNELS), '-c:a', 'pcm_s16le',
         str(dest)],
        input=mp3, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', nargs='*', metavar='KEY',
                        help='nur diese Ansagen erzeugen')
    parser.add_argument('--force', action='store_true',
                        help='auch schon vorhandene WAV-Dateien neu erzeugen')
    args = parser.parse_args()

    key = os.environ.get('FAL_KEY')
    if not key:
        print('FAL_KEY fehlt in der Umgebung', file=sys.stderr)
        return 1
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        print('ffmpeg nicht im Pfad', file=sys.stderr)
        return 1

    cfg = json.loads(CATALOG.read_text(encoding='utf-8'))
    items = cfg['announcements']
    if args.only:
        unknown = [k for k in args.only if k not in items]
        if unknown:
            print(f'unbekannte Ansagen: {", ".join(unknown)}', file=sys.stderr)
            return 1
        items = {k: items[k] for k in args.only}

    todo = {
        k: v for k, v in items.items()
        if args.force or not (OUT_DIR / f'{k}.wav').exists()
    }
    skipped = len(items) - len(todo)
    if skipped:
        print(f'{skipped} bereits vorhanden (--force erzwingt neu)')
    if not todo:
        return 0

    failures = []

    def build(item):
        name, text = item
        try:
            to_wav(synthesize(text, cfg, key), OUT_DIR / f'{name}.wav', ffmpeg)
            size = (OUT_DIR / f'{name}.wav').stat().st_size // 1024
            print(f'  {name:24s} {size:4d} KB  "{text}"')
        except Exception as exc:  # noqa: BLE001 - Sammelbericht am Ende
            failures.append((name, exc))
            print(f'  {name:24s} FEHLER: {exc}', file=sys.stderr)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(build, sorted(todo.items())))

    print(f'\n{len(todo) - len(failures)} von {len(todo)} erzeugt -> {OUT_DIR}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
