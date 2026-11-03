"""Video scripts written by a chat model for a video model (issue #30): what each video model takes, the instruction
that asks for it, and the check of what comes back. A new video model is an entry in TARGETS.

The limits are what was read on 2026-11-01. None is a vendor's full specification, so `source` says where each came from.
"""

import json
import re

TARGETS = {
    "flow": {
        "label": "Google Flow (Veo)",
        "source": "blog.google/technology/ai/flow-video-tips, Google's own tips",
        "min_seconds": 8, "max_seconds": 8, "min_words": 30, "max_words": 180, "dialogue_words": 20, "negative_prompt": False,
        "rules": ("Every clip is exactly 8 seconds. Write each video_prompt from: subject and action, composition and camera motion "
                  "(shot terms such as wide shot, close-up, tracking shot), location and lighting, style, then audio and dialogue with "
                  "tone and emotion. Flow keeps no memory between clips, so repeat every character's full appearance and the "
                  "setting in every video_prompt. A spoken line must fit well inside the clip."),
    },
    "minimax_h3": {
        "label": "MiniMax H3 (Hailuo 3.0)",
        "source": "kapwing.com/resources/how-to-prompt-minimax-h3-hailuo-3-0, a third party; nothing official was found",
        "min_seconds": 5, "max_seconds": 15, "min_words": 30, "max_words": 250, "dialogue_words": 40, "negative_prompt": False,
        "rules": ("A clip is 5 to 15 seconds. Write each video_prompt in this order: scene, a timeline of timed beats such as [0-3s], camera, "
                  "audio (dialogue, sound effects, ambience and music apart, tied to moments), constraints. Write camera moves in plain "
                  "filmmaking words such as slowly dolly in, track left, rack focus, handheld, whip pan. Do not use the older bracket "
                  "commands such as [Zoom in] or [Truck left]. Carry each scene's ending state into the next scene's opening."),
        "forbidden": (re.compile(r"\[\s*(?:zoom|truck|pan|tilt|push|pull|tracking|static|shake|pedestal)\b[^\]]*\]", re.IGNORECASE),
                      "uses a bracket camera command"),
    },
    "wan": {
        "label": "Wan 2.2",
        "source": "help.scenario.com/en/articles/wan-2-2-models-the-essentials, a third party; nothing official was found",
        "min_seconds": 2, "max_seconds": 5, "min_words": 60, "max_words": 140, "dialogue_words": 0, "negative_prompt": True,
        "rules": ("A clip is at most 5 seconds and silent: no spoken line, keep dialogue empty. Each video_prompt is 80 to 120 words: begin with "
                  "what the camera first captures, then how the shot develops, with camera terms such as pan left, tilt up, dolly in, "
                  "orbital arc, crane up, motion cues, and lighting, color and lens. Add a negative_prompt listing what to avoid, "
                  "such as blurry textures, unwanted text, deformed hands."),
    },
}

SCENE_TEXT = ("description", "camera", "color", "lighting", "image_prompt", "video_prompt")
DIRECTION_TEXT = ("concept", "hook", "visual_style", "palette")
# Room left under a target's max_words: real scripts ran up to 170 of Flow's 180 (storage/mcp-check30) before color and lighting joined them.
PROMPT_WORDS_SPARE = 20


class ScriptError(ValueError):
    """What came back is not a usable script for its target."""


def target_summaries() -> list:
    return [{"name": name, "label": t["label"], "min_seconds": t["min_seconds"], "max_seconds": t["max_seconds"],
             "dialogue": t["dialogue_words"] > 0, "negative_prompt": t["negative_prompt"], "source": t["source"]}
            for name, t in TARGETS.items()]


def build_instruction(brief: str, target: str, scenes=None, total_seconds=None, language="vi") -> str:
    """The message a chat model gets: the person's brief, the target's rules, and the exact shape to answer in."""
    rules = TARGETS[target]
    count = "exactly {} scenes".format(scenes) if scenes else "as many scenes as the story needs"
    length = " The whole film runs about {} seconds.".format(total_seconds) if total_seconds else ""
    negative = ', "negative_prompt": "..."' if rules["negative_prompt"] else ""
    audible = rules["dialogue_words"] > 0
    return (
        "You are a film director writing a shot-by-shot script for the AI video model {label}. target={target} scenes={scenes} "
        "seconds={low}-{high}\n\nThe brief:\n{brief}\n\nWrite {count}.{length} Each scene lasts {low} to {high} seconds.\n\n"
        "Rules for {label}: {rules}\n\nFirst settle the direction: concept, one fresh idea the film is built on; hook, what stops a viewer in "
        "the first two seconds; visual_style, the look, lens and movement; palette, three to five named colors. Then every scene gives its "
        "shot size, angle and movement in camera, how the palette reads in this shot in color, the source, direction and quality of the light in "
        "lighting{sound_rule}. The video model reads only image_prompt and video_prompt, so each must itself state the camera, color and lighting "
        "of its scene. Keep each video_prompt to at most {most} words.\n\n"
        "Keep every character's look the same across scenes. Every image_prompt describes the scene's "
        "first frame as one still picture, with each character's full appearance. Write title, direction, description, camera, color, lighting, sound, "
        "image_prompt, video_prompt and negative_prompt in English. Write dialogue in the language {language}, and leave it an empty string when nobody speaks.\n\n"
        "Answer with one JSON object and nothing else, no markdown, in exactly this shape:\n"
        '{{"title": "...", "direction": {{"concept": "...", "hook": "...", "visual_style": "...", "palette": "..."}}, '
        '"characters": [{{"name": "...", "description": "full look, the same words every time"}}], '
        '"scenes": [{{"number": 1, "duration_seconds": {low}, "description": "...", "camera": "...", "color": "...", "lighting": "...", {sound_shape}"dialogue": "", '
        '"image_prompt": "...", "video_prompt": "..."{negative}}}]}}'
    ).format(label=rules["label"], target=target, scenes=scenes or "any", low=rules["min_seconds"], high=rules["max_seconds"], brief=brief,
             count=count, length=length, rules=rules["rules"], language=language, negative=negative, most=rules["max_words"] - PROMPT_WORDS_SPARE,
             sound_rule=", and the music, effects and ambience in sound; video_prompt states the sound too" if audible else "",
             sound_shape='"sound": "...", ' if audible else "")


def _json_object(text: str) -> dict:
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start < 0 or end <= start:
        raise ScriptError("the answer holds no JSON object")
    try:
        found = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise ScriptError("the answer is not valid JSON: {}".format(exc)) from exc
    if not isinstance(found, dict):
        raise ScriptError("the answer is not a JSON object")
    return found


def _text(value, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScriptError("{} is missing".format(where))
    return value.strip()


def checked_script(text: str, target: str, scenes=None) -> dict:
    """What came back, as the script it must be for its target. Raises ScriptError saying what is wrong."""
    rules = TARGETS[target]
    found = _json_object(text)
    written = found.get("scenes")
    if not isinstance(written, list) or not written:
        raise ScriptError("the script has no scenes")
    if scenes and len(written) != scenes:
        raise ScriptError("{} scenes were asked for and {} came back".format(scenes, len(written)))
    characters = found.get("characters") if isinstance(found.get("characters"), list) else []
    title = _text(found.get("title"), "the title")
    direction = found.get("direction")
    if not isinstance(direction, dict):
        raise ScriptError("the script has no direction")
    script = {"title": title, "target": target,
              "direction": {field: _text(direction.get(field), "the direction's {}".format(field)) for field in DIRECTION_TEXT}, "characters": [
        {"name": _text(c.get("name"), "a character's name"), "description": _text(c.get("description"), "a character's description")}
        for c in characters if isinstance(c, dict)], "scenes": [], "total_seconds": 0}
    for number, scene in enumerate(written, 1):
        where = "scene {}".format(number)
        if not isinstance(scene, dict):
            raise ScriptError("{} is not an object".format(where))
        seconds = scene.get("duration_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ScriptError("{} has no duration_seconds".format(where))
        if not rules["min_seconds"] <= seconds <= rules["max_seconds"]:
            raise ScriptError("{} lasts {}s and {} takes {} to {}s".format(where, seconds, rules["label"], rules["min_seconds"], rules["max_seconds"]))
        kept = {"number": number, "duration_seconds": seconds}
        for field in SCENE_TEXT:
            kept[field] = _text(scene.get(field), "{}'s {}".format(where, field))
        if rules["dialogue_words"] > 0:
            kept["sound"] = _text(scene.get("sound"), "{}'s sound".format(where))
        dialogue = scene.get("dialogue") or ""
        if not isinstance(dialogue, str):
            raise ScriptError("{}'s dialogue is not text".format(where))
        kept["dialogue"] = dialogue.strip()
        if len(kept["dialogue"].split()) > rules["dialogue_words"]:
            raise ScriptError("{}'s dialogue has {} words and {} takes {}".format(
                where, len(kept["dialogue"].split()), rules["label"], rules["dialogue_words"]))
        words = len(kept["video_prompt"].split())
        if not rules["min_words"] <= words <= rules["max_words"]:
            raise ScriptError("{}'s video_prompt has {} words and {} wants {} to {}".format(
                where, words, rules["label"], rules["min_words"], rules["max_words"]))
        if rules["negative_prompt"]:
            kept["negative_prompt"] = _text(scene.get("negative_prompt"), "{}'s negative_prompt".format(where))
        forbidden = rules.get("forbidden")
        if forbidden and forbidden[0].search(kept["video_prompt"]):
            raise ScriptError("{}'s video_prompt {}".format(where, forbidden[1]))
        script["scenes"].append(kept)
        script["total_seconds"] += seconds
    return script
