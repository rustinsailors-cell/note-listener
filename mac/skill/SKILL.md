---
name: note-listener
description: Hear what note or chord the user is singing or playing through the Mac's microphone (the iPhone) and report it with octave, cents and Hz. Use when they say "listen", "what note is this", "what chord am I playing", "am I in tune", "check my pitch", or want notes read from an audio file. Also covers finding a karaoke key from their range.
---

# Note Listener

The `note-listener` MCP server records from the Mac's default input and returns the held notes and a rough chord guess. Pitch reference is A4 = 440 Hz; middle C is C4.

## When to use
- "listen", "listen to this", "what note", "what chord", "am I sharp or flat", "tune me", "what's my range": call `listen`.
- An audio or video file (Voice Memo, mp3, mov) and a question about its notes: call `analyze_audio_file` with the absolute path.
- Recording fails or picks up the wrong mic: call `list_input_devices`.

## How to listen
1. Say one short line first, such as "Listening for 4 seconds: sing or play now." Then call `listen` right away; it starts recording as soon as it's called.
2. Choose `seconds`: 3 to 5 for one note or chord (default 4), 8 to 15 for a phrase or a range sweep. Maximum 15.
3. Set `chord: false` when they only want a single note checked (it's a little faster).

## Reading the result
The tool returns a short summary and a JSON block:
- `main_note`: the longest held note, with `cents` (minus means flat, plus means sharp) and `hz`. Lead with this for "what note".
- `notes`: every held note in order, with when it started and how long it lasted. Use it for melodies, runs and range.
- `lowest` and `highest`: the range across the held notes.
- `chord_guess`: approximate. For "what chord", lead with the chord name and give the strongest notes it heard. If `main_note` is missing but there's a chord guess, they probably played a chord.
- `input_device`: which mic was used.

How to answer:
- One note: "That's A3, 6 cents flat (218.2 Hz)." Within ±5 cents counts as in tune; say so.
- Chord: "Sounds like G7 (rough guess): strongest notes G, B, D, F." Call it a guess; strumming, distortion and a capo can throw it off.
- Range: give lowest to highest, for example "A2 to E4".
- Keep it short, then offer to listen again.

## When it fails
The error text says what's wrong. Pass it on plainly; don't retry in a loop.
- "Only silence" or "quiet background noise" from "MacBook Pro Microphone": the MacBook's own mic doesn't work. They need to connect the iPhone as the Mac's microphone (Continuity) and choose it in System Settings > Sound > Input, then try again.
- "No sound arrived": macOS may be waiting on a microphone permission prompt, or the input isn't sending sound.
- Never guess a note when the tool didn't return one.

## Karaoke key
To find which key to buy a karaoke track in, they can use the Key helper on the web page (https://rustinsailors-cell.github.io/note-listener/): it takes the song's original key and its lowest and highest notes, plus how they sang it. You can also work it out: shift = (their low − song low + their high − song high) / 2 half steps, rounded. Name the new key, and when the shift is more than 6 half steps, give the equivalent within ±6 and say they'd sing an octave higher or lower than the track.

## Files
Code: `~/DEVELOPER/Pitch Pal Note Listener/mac/` (`pitch.py` detection, `server.py` MCP server, `test_pitch.py` tests). Command line without Claude: `python3 pitch.py listen 4`.
