#!/usr/bin/env python3
"""Video scripts: what each video model takes, and the check of what a chat model answers (issue #30).

    ~/cloakbrowser-env/bin/python tests/test_scripts.py

Prints N/N PASSED. Pure code, no api, no browser.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from src.scripts import TARGETS, ScriptError, build_instruction, checked_script, target_summaries  # noqa: E402

results = []
WORDS = " ".join(["lighthouse"] * 90)


def record(name, ok, detail=""):
    results.append(bool(ok))
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, str(detail)[:240]), flush=True)


def scene(**over):
    base = {"number": 1, "duration_seconds": 8, "description": "a shot", "camera": "dolly in", "dialogue": "", "image_prompt": "a still", "video_prompt": WORDS}
    base.update(over)
    return base


def answer(*scenes, **over):
    script = {"title": "A film", "characters": [{"name": "Lan", "description": "a red coat"}], "scenes": list(scenes)}
    script.update(over)
    return json.dumps(script)


def refused(text, target="flow", scenes=None):
    try:
        checked_script(text, target, scenes)
        return ""
    except ScriptError as exc:
        return str(exc)


def main():
    got = checked_script(answer(scene(), scene(number=9)), "flow")
    record("a script that fits comes back whole, renumbered, with its total", got["title"] == "A film" and got["target"] == "flow"
           and [s["number"] for s in got["scenes"]] == [1, 2] and got["total_seconds"] == 16 and got["characters"][0]["name"] == "Lan", got["total_seconds"])
    record("a fenced answer with words around it is read", checked_script("Here it is:\n```json\n" + answer(scene()) + "\n```\nEnjoy.", "flow")["scenes"])

    for name, text, word in (("no JSON", "sorry, no script", "no JSON"), ("broken JSON", '{"title": ', "no JSON"), ("bad JSON", "{not json}", "not valid"),
                             ("no scenes", answer(), "no scenes"), ("no title", answer(scene(), title=""), "title"),
                             ("no duration", answer(scene(duration_seconds=None)), "duration"), ("a duration in words", answer(scene(duration_seconds="8")), "duration"),
                             ("a missing video prompt", answer(scene(video_prompt="")), "video_prompt"), ("a missing first frame", answer(scene(image_prompt=None)), "image_prompt"),
                             ("dialogue that is not text", answer(scene(dialogue=["hi"])), "dialogue")):
        said = refused(text)
        record("{} is refused, saying so".format(name), word in said, said)

    record("the number of scenes asked for is held to", "3 scenes" in refused(answer(scene()), scenes=3), refused(answer(scene()), scenes=3))

    record("Flow takes only its 8-second clips", "lasts 10s" in refused(answer(scene(duration_seconds=10))), refused(answer(scene(duration_seconds=10))))
    long_line = " ".join(["word"] * 21)
    record("Flow refuses a line that cannot fit its clip", "dialogue has 21" in refused(answer(scene(dialogue=long_line))), refused(answer(scene(dialogue=long_line))))
    record("Flow takes a short line", not refused(answer(scene(dialogue="Xin chào, tôi là Lan."))))

    record("MiniMax H3 takes 5 to 15 seconds", not refused(answer(scene(duration_seconds=15)), "minimax_h3") and not refused(answer(scene(duration_seconds=5)), "minimax_h3"))
    record("MiniMax H3 refuses 16", "lasts 16s" in refused(answer(scene(duration_seconds=16)), "minimax_h3"))
    bracket = WORDS + " [Zoom in] then more"
    record("MiniMax H3 refuses an old bracket camera command", "bracket" in refused(answer(scene(video_prompt=bracket)), "minimax_h3"),
           refused(answer(scene(video_prompt=bracket)), "minimax_h3"))
    record("MiniMax H3 takes a timed beat in brackets", not refused(answer(scene(video_prompt=WORDS + " [0-3s] she walks")), "minimax_h3"))
    record("only MiniMax H3 refuses those brackets", not refused(answer(scene(video_prompt=bracket))))

    wan = dict(duration_seconds=5, negative_prompt="blurry textures")
    record("Wan takes a silent clip of 5 seconds with a negative prompt", checked_script(answer(scene(**wan)), "wan")["scenes"][0]["negative_prompt"] == "blurry textures")
    record("Wan refuses more than 5 seconds", "lasts 6s" in refused(answer(scene(**dict(wan, duration_seconds=6))), "wan"))
    record("Wan refuses a spoken line", "dialogue" in refused(answer(scene(**dict(wan, dialogue="hello"))), "wan"))
    record("Wan needs its negative prompt", "negative_prompt" in refused(answer(scene(duration_seconds=5)), "wan"))
    short = " ".join(["word"] * 20)
    record("Wan refuses a prompt far from its 80 to 120 words", "20 words" in refused(answer(scene(**dict(wan, video_prompt=short))), "wan"))
    record("only Wan keeps a negative prompt", "negative_prompt" not in checked_script(answer(scene(negative_prompt="x")), "flow")["scenes"][0])

    told = build_instruction("Lan goes home", "wan", 3, 15, "vi")
    record("the instruction carries the brief, the rules, the count, the language and the shape",
           all(word in told for word in ("Lan goes home", "Wan 2.2", "exactly 3 scenes", "about 15 seconds", "language vi", "negative_prompt", "target=wan scenes=3")), told[:120])
    record("the shape asks for a negative prompt only where it is taken", "negative_prompt\": " not in build_instruction("x", "flow"))
    names = [t["name"] for t in target_summaries()]
    record("every target says what it takes and where that came from", names == list(TARGETS) and all(t["source"] for t in target_summaries()), names)

    passed = sum(results)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
