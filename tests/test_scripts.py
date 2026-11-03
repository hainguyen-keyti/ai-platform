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
    base = {"number": 1, "duration_seconds": 8, "description": "a shot", "camera": "dolly in", "color": "teal shadows, warm skin", "lighting": "low golden sun",
            "sound": "soft wind, no music", "dialogue": "", "image_prompt": "a still", "video_prompt": WORDS}
    base.update(over)
    return base


DIRECTION = {"concept": "a coat that remembers", "hook": "she walks out of a painting", "visual_style": "35mm, handheld", "palette": "teal, amber, off-white"}


def answer(*scenes, **over):
    script = {"title": "A film", "direction": dict(DIRECTION), "characters": [{"name": "Lan", "description": "a red coat"}], "scenes": list(scenes)}
    script.update(over)
    return json.dumps(script)


def refused(text, target="flow", scenes=None, total_seconds=None):
    try:
        checked_script(text, target, scenes, total_seconds)
        return ""
    except ScriptError as exc:
        return str(exc)


CONCEPT = {"idea": "một chiếc bình nhớ tay người", "audience": "dân văn phòng", "message": "mở một tay", "tone": "ấm", "visual_style": "cầm tay, tự nhiên",
           "palette": "xanh rêu, xám, vàng nắng", "synopsis": "Một ngày bận rộn, một cái bình."}
POST = {"pacing": "cắt nhanh rồi chậm lại", "transitions": "cắt thẳng, một match cut", "color_grade": "ấm, tương phản vừa", "music": "guitar nhẹ, vào từ giây 2",
        "sound_mix": "thoại trên nhạc", "subtitles": "phụ đề tiếng Việt, chữ trắng", "format": "dọc 9:16, 30 fps"}


def shot(seconds=4, **over):
    base = {"number": 1, "duration_seconds": seconds, "shot_size": "cận", "angle": "góc thấp", "lens": "50mm", "movement": "đẩy nhẹ vào", "composition": "bình lệch phải",
            "action": "ngón cái bật nắp", "lighting": "nắng xiên trái", "color": "xanh rêu trên nền xám", "sound": "tiếng click", "transition": "cắt thẳng theo nhịp",
            "dialogue": "", "voice_over": "", "on_screen_text": ""}
    base.update(over)
    return base


def film_scene(*shots, **over):
    base = {"number": 1, "title": "Mở đầu", "location": "lề đường", "purpose": "giữ người xem", "description": "Linh dừng xe.", "shots": list(shots)}
    base.update(over)
    return base


def film(*scenes, **over):
    script = {"title": "Một tay", "concept": dict(CONCEPT), "characters": [{"name": "Linh", "description": "25 tuổi, áo be"}],
              "settings": [{"name": "Lề đường", "description": "buổi chiều, xe máy dựng"}], "scenes": list(scenes), "post": dict(POST)}
    script.update(over)
    return json.dumps(script)


def production_cases():
    got = checked_script(film(film_scene(shot(4), shot(2.5, number=7)), film_scene(shot(8))), "production", None, 15)
    record("a production script comes back whole, its shots of any length, numbered, timed by the api", got["total_seconds"] == 14.5
           and [(s["number"], s["start_seconds"], s["end_seconds"]) for scene in got["scenes"] for s in scene["shots"]] == [(1, 0, 4), (2, 4, 6.5), (3, 6.5, 14.5)]
           and got["concept"] == CONCEPT and got["post"] == POST and got["settings"][0]["name"] == "Lề đường" and got["target"] == "production", got["total_seconds"])
    record("a shot keeps its dialogue, voice-over and on-screen text", checked_script(film(film_scene(shot(4, dialogue="Một tay thôi", voice_over="Dễ", on_screen_text="MÁT LÂU"))), "production")
           ["scenes"][0]["shots"][0]["on_screen_text"] == "MÁT LÂU")
    for section, fields, make in (("concept", CONCEPT, lambda f: film(film_scene(shot()), concept=dict(CONCEPT, **{f: ""}))),
                                  ("post", POST, lambda f: film(film_scene(shot()), post=dict(POST, **{f: " "})))):
        for field in fields:
            said = refused(make(field), "production")
            record("a production with no {} in its {} is refused, saying so".format(field, section), "{}'s {}".format(section, field) in said, said)
    for field in ("title", "location", "purpose", "description"):
        said = refused(film(film_scene(shot(), **{field: ""})), "production")
        record("a scene with no {} is refused, saying which".format(field), "scene 1's {}".format(field) in said, said)
    for field in ("shot_size", "angle", "lens", "movement", "composition", "action", "lighting", "color", "sound", "transition"):
        said = refused(film(film_scene(shot(), shot(**{field: None}))), "production")
        record("a shot with no {} is refused, saying which".format(field), "scene 1 shot 2's {}".format(field) in said, said)
    for name, text, word in (("no concept", film(film_scene(shot()), concept=None), "no concept"), ("no post", film(film_scene(shot()), post="ok"), "no post"),
                             ("no settings", film(film_scene(shot()), settings=[]), "no settings"), ("no scenes", film(), "no scenes"),
                             ("a scene with no shots", film(film_scene()), "no shots"), ("a duration in words", film(film_scene(shot("4"))), "duration"),
                             ("a zero duration", film(film_scene(shot(0))), "lasts 0s"), ("a true duration", film(film_scene(shot(True))), "duration"),
                             ("a duration past a minute", film(film_scene(shot(61))), "lasts 61s"),
                             ("dialogue that is not text", film(film_scene(shot(dialogue=["a"]))), "dialogue")):
        said = refused(text, "production")
        record("a production with {} is refused, saying so".format(name), word in said, said)
    long_line = " ".join(["từ"] * 11)
    said = refused(film(film_scene(shot(2, dialogue=long_line))), "production")
    record("a line that cannot be said in its shot is refused", "11 words" in said and "2s" in said, said)
    said = refused(film(film_scene(shot(2, dialogue=" ".join(["từ"] * 6), voice_over=" ".join(["từ"] * 5)))), "production")
    record("dialogue and voice-over count together", "11 words" in said, said)
    record("a line that fits is kept", not refused(film(film_scene(shot(2, dialogue=" ".join(["từ"] * 10)))), "production"))
    record("the film's length is held to what was asked", "40s" in refused(film(film_scene(shot(40))), "production", None, 30), refused(film(film_scene(shot(40))), "production", None, 30))
    record("a little off the length asked is fine", not refused(film(film_scene(shot(33))), "production", None, 30))
    record("the number of scenes asked for is held to", "2 scenes" in refused(film(film_scene(shot())), "production", 2))
    told = build_instruction("Bình xanh rêu", "production", None, 45, "vi")
    record("the instruction carries the brief, the length, the language and every field",
           all(word in told for word in ("Bình xanh rêu", "45 seconds", "language vi", "target=production", "total_seconds=45") + tuple('"{}"'.format(f) for f in tuple(CONCEPT) + tuple(POST)
               + ("settings", "shots", "lens", "transition", "voice_over", "on_screen_text"))), told[:160])
    record("the instruction asks for shots as long as they need, and names no tool",
           "as long as it needs" in told and "Do not name" in told and "image_prompt" not in told and "video_prompt" not in told and "Flow" not in told, told[:160])
    # Measured 2026-11-03, job fbc7d9f9: a stray brace before a post written after the deep scenes, and shots adding up to 29.3s of 45s.
    record("the shape puts post before the deep scenes", told.index('"post": {') < told.index('"scenes": ['), told[-400:])
    record("the shape keeps a running clock, and says to add shots when short",
           '"ends_at_seconds"' in told and "running clock" in told and "add shots" in told, told[:160])
    record("what the writer's clock says is not kept: the api times the shots",
           "ends_at_seconds" not in checked_script(film(film_scene(shot(4, ends_at_seconds=99))), "production")["scenes"][0]["shots"][0])
    record("production is listed as a target","production" in [t["name"] for t in target_summaries()])
    long_flow = refused(answer(scene(), scene()), "flow", None, 1)
    record("a video model's script is not held to the film's length", not long_flow, long_flow)


def main():
    production_cases()
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

    kept = checked_script(answer(scene()), "flow")
    record("a script keeps its direction, and each scene its color, lighting and sound",
           kept["direction"] == DIRECTION and kept["scenes"][0]["color"] == "teal shadows, warm skin" and kept["scenes"][0]["lighting"] == "low golden sun"
           and kept["scenes"][0]["sound"] == "soft wind, no music", kept["scenes"][0])
    for field in ("color", "lighting", "sound"):
        for name, value in (("missing", None), ("empty", "  ")):
            said = refused(answer(scene(), scene(**{field: value})))
            record("a scene with its {} {} is refused, saying which".format(field, name), "scene 2's {}".format(field) in said, said)
    for field in DIRECTION:
        said = refused(answer(scene(), direction=dict(DIRECTION, **{field: ""})))
        record("a direction with no {} is refused, saying so".format(field), "direction's {}".format(field) in said, said)
    for name, value in (("no direction", None), ("a direction in words", "moody")):
        said = refused(answer(scene(), direction=value))
        record("{} is refused, saying so".format(name), "no direction" in said, said)
    silent = dict(duration_seconds=5, negative_prompt="blurry textures", sound=None)
    record("a silent target needs no sound and keeps none", "sound" not in checked_script(answer(scene(**silent)), "wan")["scenes"][0])
    record("a silent target still needs its color", "color" in refused(answer(scene(**dict(silent, color=""))), "wan"))
    for target in ("flow", "minimax_h3", "wan"):
        told = build_instruction("x", target)
        record("the instruction asks {} for all of it, and says the video model reads only its prompts".format(target),
               all('"{}"'.format(word) in told for word in tuple(DIRECTION) + ("color", "lighting")) and "reads only" in told
               and ('"sound"' in told) == (TARGETS[target]["dialogue_words"] > 0), told[-300:])
        most = TARGETS[target]["max_words"] - 20
        record("the instruction gives {} room under its word limit".format(target), "at most {} words".format(most) in told, most)

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
