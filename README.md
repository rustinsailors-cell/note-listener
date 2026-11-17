# Note Listener

Sing or play a note and see its name, octave, cents and frequency. Includes a vocal range check, a chord guess and a karaoke key helper.

Live page: https://rustinsailors-cell.github.io/note-listener/

## Files
- `page.src.html`: page source (HTML, CSS, UI script). Edit this.
- `pitchcore.js`: note, chord and voice-type detection (pure functions).
- `build.js`: builds `note-listener.html` and `docs/index.html` (the GitHub Pages site).
- `test.js`: tests for `pitchcore.js`.
- `mac/`: Python listener and MCP server for Claude Code on the Mac.

## Build and test
    node test.js
    node build.js
