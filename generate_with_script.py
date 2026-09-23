#!/usr/bin/env python3
"""Generate images and video scripts for Wan 2.2"""

import base64
import sys
from pathlib import Path
import cloakbrowser

STORAGE = Path.home() / ".chatgpt-cli" / "storage_cloak.json"
OUTPUT_DIR = Path(__file__).parent / "images" / "pink_girl"
REF_IMAGE = Path(__file__).parent / "images" / "girls" / "girl_02.png"

SCENES = [
    ("rooftop", "the same pink-haired anime girl with blue eyes, black ribbon, and cat hair clip, sitting on the school rooftop during sunset, looking at the sky peacefully, full body, wind blowing her hair"),
    ("rain", "the same pink-haired anime girl with blue eyes, black ribbon, and cat hair clip, holding a pink umbrella walking in the rain on a city street, full body, reflections on wet ground"),
    ("festival", "the same pink-haired anime girl with blue eyes, black ribbon, and cat hair clip, wearing a pink yukata at a summer festival, holding cotton candy, full body, festival lights and stalls in background"),
    ("study", "the same pink-haired anime girl with blue eyes, black ribbon, and cat hair clip, studying at her desk in her bedroom at night, lamp light, books and notes, full body side view"),
]

def generate():
    browser = cloakbrowser.launch(headless=True)
    ctx = browser.new_context(storage_state=str(STORAGE))
    page = ctx.new_page()
    page.goto("https://chatgpt.com/", timeout=90000, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)

    results = []

    for name, prompt in SCENES:
        print(f"\n=== Generating: {name} ===")

        # Upload reference
        file_input = page.locator("#upload-files")
        file_input.set_input_files(str(REF_IMAGE))
        page.wait_for_timeout(3000)

        # Count existing
        base_count = page.locator('[data-message-author-role="assistant"]').count()

        # Send prompt
        ta = page.locator("#prompt-textarea")
        ta.click()
        ta.fill(f"Generate an image: {prompt}")
        page.wait_for_timeout(300)

        btn = page.locator('button[data-testid="send-button"]')
        if btn.is_visible():
            btn.click()
        else:
            page.keyboard.press("Enter")

        # Wait for response
        print("Waiting for image...")
        result_text = ""
        stable = 0
        for i in range(150):
            page.wait_for_timeout(1000)
            resp_els = page.locator('[data-message-author-role="assistant"]').all()
            if len(resp_els) > base_count:
                txt = resp_els[-1].inner_text()
                if txt == result_text:
                    stable += 1
                    if stable >= 3 and page.locator('[data-testid="stop-button"]').count() == 0:
                        break
                else:
                    result_text = txt
                    stable = 0

        # Download image
        imgs = page.evaluate('''() => {
            const imgs = document.querySelectorAll("img");
            const results = [];
            for (const img of imgs) {
                const rect = img.getBoundingClientRect();
                if (rect.width > 200 && rect.height > 200 && img.src.includes("estuary")) {
                    results.push(img.src);
                }
            }
            return results;
        }''')

        img_path = None
        if imgs:
            src = imgs[-1]
            try:
                data = page.evaluate('''async (url) => {
                    const r = await fetch(url);
                    const b = await r.blob();
                    return new Promise(resolve => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(reader.result);
                        reader.readAsDataURL(b);
                    });
                }''', src)

                if data and data.startswith("data:"):
                    img_path = OUTPUT_DIR / f"scene_{name}.png"
                    with open(img_path, "wb") as f:
                        f.write(base64.b64decode(data.split(",")[1]))
                    print(f"Saved: {img_path}")
            except Exception as e:
                print(f"Error downloading: {e}")

        results.append((name, img_path, prompt))
        page.wait_for_timeout(2000)

    # Now generate scripts for each
    print("\n\n=== GENERATING VIDEO SCRIPTS ===\n")

    scripts = []
    for name, img_path, scene_desc in results:
        if not img_path:
            continue

        print(f"\n--- Script for {name} ---")
        base_count = page.locator('[data-message-author-role="assistant"]').count()

        ta = page.locator("#prompt-textarea")
        ta.click()
        ta.fill(f"Write a Wan 2.2 video prompt (5 seconds) for this scene: {scene_desc}. Describe camera movement, character animation, ambient motion. Single paragraph, under 150 words.")
        page.wait_for_timeout(300)

        btn = page.locator('button[data-testid="send-button"]')
        if btn.is_visible():
            btn.click()
        else:
            page.keyboard.press("Enter")

        script_text = ""
        stable = 0
        for i in range(60):
            page.wait_for_timeout(1000)
            resp_els = page.locator('[data-message-author-role="assistant"]').all()
            if len(resp_els) > base_count:
                txt = resp_els[-1].inner_text()
                if txt == script_text:
                    stable += 1
                    if stable >= 2 and page.locator('[data-testid="stop-button"]').count() == 0:
                        break
                else:
                    script_text = txt
                    stable = 0

        scripts.append((name, img_path, script_text))
        print(f"Script: {script_text[:200]}...")

    ctx.storage_state(path=str(STORAGE))
    browser.close()

    # Print final results
    print("\n\n" + "="*60)
    print("RESULTS")
    print("="*60)

    for name, img_path, script in scripts:
        print(f"\n### {name.upper()} ###")
        print(f"Image: {img_path}")
        print(f"Script:\n{script}\n")

    return scripts

if __name__ == "__main__":
    generate()
