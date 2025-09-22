# app/utils/ssml.py  (add)
import re

STYLE_RE = re.compile(r"<style:([a-zA-Z0-9_-]+)>(.*?)</style>", re.DOTALL)
PROSODY_RE = re.compile(r"<prosody([^>]*)>(.*?)</prosody>", re.DOTALL)

def extract_style(text: str):
    emotion = None
    m = STYLE_RE.search(text)
    if m:
        emotion = m.group(1)
        text = STYLE_RE.sub(r"\2", text)
    speed = 1.0; pitch = 0.0; energy = 1.0
    m = PROSODY_RE.search(text)
    if m:
        attrs = m.group(1)
        text = PROSODY_RE.sub(r"\2", text)
        if "speed" in attrs:
            try: speed = float(re.search(r"speed=['\"]([\d\.]+)['\"]", attrs).group(1))
            except: pass
        if "pitch" in attrs:
            try: pitch = float(re.search(r"pitch=['\"]([-\d\.]+)['\"]", attrs).group(1))
            except: pass
        if "energy" in attrs:
            try: energy = float(re.search(r"energy=['\"]([\d\.]+)['\"]", attrs).group(1))
            except: pass
    return text, emotion, speed, pitch, energy
