"""Note Listener MCP server (stdio, standard library only).

Tools:
  listen               record from the Mac's default input and return the note(s) and a chord guess
  analyze_audio_file   the same for an audio or video file on disk
  list_input_devices   show the default input and the other inputs

Register for every Claude Code project:
  claude mcp add --scope user note-listener -- python3 "/path/to/mac/server.py"
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pitch  # noqa: E402

SERVER = {"name": "note-listener", "version": "1.0.0"}
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]

TOOLS = [
    {
        "name": "listen",
        "title": "Listen to a note or chord",
        "description": ("Record from the Mac's default microphone (the iPhone, when it's connected as the Mac's mic) for a few "
                        "seconds and report what was sung or played: the main held note with octave, cents sharp or flat, and Hz; "
                        "every held note in order; the lowest and highest; and a rough chord guess. Tell the user to sing or play "
                        "right before calling. Pitch reference A4 = 440 Hz."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "minimum": 1, "maximum": pitch.MAX_SECONDS, "default": 4,
                            "description": "How long to listen. 3-5 for one note or chord, up to 15 for a phrase."},
                "chord": {"type": "boolean", "default": True, "description": "Also guess a chord (adds about half a second)."},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "analyze_audio_file",
        "title": "Read notes from an audio file",
        "description": "Find the held notes, range and a rough chord guess in an audio or video file (m4a, mp3, wav, mov, ...). Reads up to 10 minutes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file."},
                "chord": {"type": "boolean", "default": True},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "list_input_devices",
        "title": "List microphones",
        "description": "Show which input device macOS will record from (the default) and the other inputs it sees.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


def text_result(text, is_error=False, data=None):
    out = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if data is not None:
        out["content"].append({"type": "text", "text": json.dumps(data)})
    return out


def call_tool(name, args):
    args = args or {}
    try:
        if name == "listen":
            secs = args.get("seconds", 4)
            if not isinstance(secs, (int, float)) or isinstance(secs, bool):
                return text_result("seconds must be a number from 1 to %d." % pitch.MAX_SECONDS, True)
            res = pitch.listen(secs, want_chord=args.get("chord", True) is not False)
            return text_result(pitch.describe(res), data=res)
        if name == "analyze_audio_file":
            path = args.get("path")
            if not isinstance(path, str) or not path.strip() or len(path) > 4096:
                return text_result("Give the file's full path.", True)
            res = pitch.analyse(pitch.read_file(path), want_chord=args.get("chord", True) is not False)
            return text_result(pitch.describe(res), data=res)
        if name == "list_input_devices":
            default = pitch.default_input_name()
            names = pitch.list_devices()
            lines = ["Default input (what listen records): %s" % (default or "unknown")]
            lines += ["- %s" % n for n in names] or ["No inputs found."]
            return text_result("\n".join(lines))
        return None
    except pitch.AudioError as e:
        return text_result(str(e), True)
    except Exception as e:  # keep the server alive; report briefly
        return text_result("Note Listener hit an error: %s" % type(e).__name__, True)


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # notification: no reply
        return None
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER,
            "instructions": "Call listen when the user says listen, asks what note or chord they're singing or playing, or wants a tuning check. Ask them to start the sound first.",
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        p = msg.get("params") or {}
        res = call_tool(p.get("name"), p.get("arguments"))
        if res is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown tool"}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(msg) if isinstance(msg, dict) else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
