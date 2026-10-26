"""
Bedtime Story Generator (ages 5-10)

Pipeline:
  User request -> Classifier -> Planner (story arc) -> Storyteller
       -> Judge -> (Reviser -> Judge)* -> Story shown to user
       -> optional user feedback -> Reviser -> Judge -> ...

Model is intentionally fixed to gpt-5.6-terra (assignment requirement).
Requires: openai==0.28.* and the OPENAI_API_KEY environment variable.
"""

import json
import os
import re

import openai
from dotenv import load_dotenv

load_dotenv()  # reads OPENAI_API_KEY from a local .env file (if present)

MODEL = "gpt-5.6-terra"  # DO NOT CHANGE (assignment requirement)

# ---- Tunable knobs ---------------------------------------------------------
MAX_JUDGE_ROUNDS = 3        # max revise cycles before we ship the best story
PASS_SCORE = 8.0            # average judge score needed to accept a story
MIN_SAFETY_SCORE = 9        # age-appropriateness must be at least this
VERBOSE = True              # print judge scores so you can see the loop work


# ---- LLM wrapper -----------------------------------------------------------
def call_model(prompt: str, max_tokens=3000, system: str = None) -> str:
    """Thin wrapper around the OpenAI chat API (same model as the skeleton)."""
    openai.api_key = os.getenv("OPENAI_API_KEY")  # never hard-code your key
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = openai.ChatCompletion.create(
        model=MODEL,
        messages=messages,
        stream=False,
        max_completion_tokens=max_tokens,
    )
    return resp.choices[0].message["content"]  # type: ignore


def parse_json(text: str, fallback: dict) -> dict:
    """The model sometimes wraps JSON in prose/markdown. Grab the first {...} block."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return fallback
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return fallback


def log(msg: str):
    if VERBOSE:
        print(msg)


# ---- Category-specific storytelling strategies -----------------------------
# "Categorize the request and use a tailored generation strategy" (idea from the brief).
CATEGORY_GUIDES = {
    "adventure": "Fast-moving quest with a clear goal. Include a small, safe obstacle "
                 "and a clever or kind solution. Brave but never scary.",
    "animal_friends": "Warm, funny animal characters with distinct personalities. "
                      "Focus on friendship, teamwork and kindness. Include playful animal sounds.",
    "fantasy_magic": "Gentle magic, whimsical places, and wonder. Magic has simple "
                     "rules and the hero solves the problem with heart, not just a spell.",
    "everyday_life": "Relatable situations (school, siblings, sharing, trying something new). "
                     "Gently model a feeling or lesson without being preachy.",
    "silly_funny": "Giggle-worthy absurdity, wordplay, repetition and surprise. "
                   "A running joke or silly refrain the child can repeat.",
}
DEFAULT_CATEGORY = "adventure"

# Shared rules every prompt inherits.
STORY_RULES = """\
Audience: children aged 5-10, read aloud at bedtime.
- Simple, vivid words; short sentences; some read-aloud rhythm or repetition.
- No violence, scary or graphic content, death, or mean-spirited behavior.
- Problems are real but small, and solved with kindness, creativity or teamwork.
- The ending slows down: calm, cozy, sleepy imagery, and the characters go to sleep.
- Length: about 500-700 words. Give the story a short title."""


# ---- Step 1: Classify & sanitize the request -------------------------------
def classify_request(user_input: str) -> dict:
    prompt = f"""You help a children's bedtime storyteller (ages 5-10).
Read this story request and reply with ONLY a JSON object:
{{
  "category": one of {list(CATEGORY_GUIDES.keys())},
  "characters": [list of main character names/types],
  "kid_safe_request": "the request rewritten so it is appropriate for ages 5-10 (keep the spirit, remove anything scary/violent/inappropriate)"
}}

Request: "{user_input}"
"""
    raw = call_model(prompt, max_tokens=300)
    info = parse_json(raw, {})
    if info.get("category") not in CATEGORY_GUIDES:
        info["category"] = DEFAULT_CATEGORY
    info.setdefault("characters", [])
    info.setdefault("kid_safe_request", user_input)
    return info


# ---- Step 2: Plan the story using a story arc ------------------------------
def plan_story(info: dict) -> str:
    prompt = f"""Plan a bedtime story for children aged 5-10.

Request: {info['kid_safe_request']}
Characters: {', '.join(info['characters']) or 'invent charming ones'}
Style guide ({info['category']}): {CATEGORY_GUIDES[info['category']]}

Write a short outline with exactly these beats (1-2 sentences each):
1. Setting & characters: who they are and what they love
2. The problem or wish: something small they want or need to fix
3. First try: an attempt that doesn't quite work (funny or sweet)
4. The turning point: a clever, kind, or brave idea
5. Resolution: the problem is solved and a gentle lesson shows through
6. Wind-down: cozy, sleepy ending where everyone drifts off

Also suggest a fun repeated phrase or refrain the child can join in on."""
    return call_model(prompt, max_tokens=600)


# ---- Step 3: Write the story ----------------------------------------------
def write_story(info: dict, outline: str) -> str:
    prompt = f"""Write a bedtime story following this outline exactly.

{STORY_RULES}

Style guide ({info['category']}): {CATEGORY_GUIDES[info['category']]}

Request: {info['kid_safe_request']}

Outline:
{outline}

Begin with the title on its own line, then the story."""
    return call_model(
        prompt,
        max_tokens=1500,
        system="You are a warm, imaginative children's author who reads aloud at bedtime.",
    )


# ---- Step 4: LLM Judge -----------------------------------------------------
JUDGE_CRITERIA = [
    "age_appropriateness",   # content + vocabulary suit ages 5-10, nothing scary
    "story_arc",             # clear beginning, problem, turning point, resolution
    "engagement",            # fun, vivid, memorable characters, read-aloud rhythm
    "bedtime_tone",          # ends calm and sleepy
    "request_fit",           # matches what the user asked for
]


def judge_story(user_request: str, story: str) -> dict:
    prompt = f"""You are a strict but kind editor of children's bedtime stories for ages 5-10.
Grade the story below. Score each criterion from 1 (poor) to 10 (excellent).

Criteria:
- age_appropriateness: language and content right for ages 5-10; nothing scary/violent
- story_arc: clear setting, problem, attempt, turning point, resolution
- engagement: vivid, funny/sweet, memorable characters, good read-aloud rhythm
- bedtime_tone: ending is calm, cozy, and sleepy
- request_fit: matches the original request

Original request: "{user_request}"

STORY:
\"\"\"
{story}
\"\"\"

Reply with ONLY a JSON object in this exact shape:
{{
  "scores": {{"age_appropriateness": 0, "story_arc": 0, "engagement": 0, "bedtime_tone": 0, "request_fit": 0}},
  "feedback": ["specific, actionable fix #1", "fix #2", "fix #3"]
}}"""
    raw = call_model(prompt, max_tokens=500)
    result = parse_json(raw, {})
    scores = result.get("scores", {})
    clean = {c: _to_int(scores.get(c)) for c in JUDGE_CRITERIA}
    feedback = result.get("feedback", [])
    if not isinstance(feedback, list):
        feedback = [str(feedback)]
    avg = sum(clean.values()) / len(clean)
    return {"scores": clean, "average": avg, "feedback": feedback}


def _to_int(value) -> int:
    """Be forgiving: the model might return '8', 8.5, or garbage. Default to 5."""
    try:
        return max(1, min(10, int(round(float(value)))))
    except (TypeError, ValueError):
        return 5


def passes(verdict: dict) -> bool:
    return (
        verdict["average"] >= PASS_SCORE
        and verdict["scores"]["age_appropriateness"] >= MIN_SAFETY_SCORE
    )


# ---- Step 5: Reviser -------------------------------------------------------
def revise_story(story: str, feedback: list, original_request: str) -> str:
    notes = "\n".join(f"- {f}" for f in feedback)
    prompt = f"""Revise this bedtime story for children aged 5-10.

{STORY_RULES}

Original request: {original_request}

Apply this feedback while keeping what already works:
{notes}

CURRENT STORY:
\"\"\"
{story}
\"\"\"

Return only the full improved story (title first)."""
    return call_model(
        prompt,
        max_tokens=1500,
        system="You are a warm, imaginative children's author who reads aloud at bedtime.",
    )


# ---- Orchestration: judge loop --------------------------------------------
def improve_until_good(request: str, story: str) -> str:
    """Judge -> revise loop. Keeps the best-scoring draft in case revisions regress."""
    best_story, best_avg = story, -1.0
    current = story

    for round_num in range(1, MAX_JUDGE_ROUNDS + 1):
        verdict = judge_story(request, current)
        log(f"\n[Judge round {round_num}] avg={verdict['average']:.1f} {verdict['scores']}")

        if verdict["average"] > best_avg:
            best_story, best_avg = current, verdict["average"]

        if passes(verdict):
            log("[Judge] Story approved.")
            return current

        if round_num < MAX_JUDGE_ROUNDS:
            log(f"[Judge] Feedback: {verdict['feedback']}")
            current = revise_story(current, verdict["feedback"], request)

    log("[Judge] Max rounds reached; using best draft.")
    return best_story


def tell_story(user_input: str) -> tuple:
    """Full pipeline. Returns (story, info) so the feedback loop can reuse context."""
    info = classify_request(user_input)
    log(f"[Classifier] category={info['category']} characters={info['characters']}")

    outline = plan_story(info)
    log(f"[Planner] outline ready")

    draft = write_story(info, outline)
    story = improve_until_good(info["kid_safe_request"], draft)
    return story, info


# ---- Output: save to disk & read aloud -------------------------------------
STORY_FILE = "story.txt"     # temporary; overwritten with each new/revised story
AUDIO_FILE = "story.mp3"     # temporary narration
TTS_VOICE = "en-US-AnaNeural"  # soft, child-friendly neural voice
TTS_RATE = "-10%"            # a little slower for a calm bedtime pace


def save_story(story: str, path: str = STORY_FILE):
    with open(path, "w", encoding="utf-8") as f:
        f.write(story)
    log(f"[Saved] {path}")


def read_aloud(story: str):
    """Narrate the story with edge-tts (free neural voices) and open it in the default player."""
    import asyncio
    import subprocess
    import sys

    try:
        import edge_tts
    except ImportError:
        print("Install edge-tts to enable narration: pip install edge-tts")
        return

    async def synthesize():
        await edge_tts.Communicate(story, TTS_VOICE, rate=TTS_RATE).save(AUDIO_FILE)

    try:
        asyncio.run(synthesize())
    except Exception as e:  # network issues etc.; the text story is still available
        print(f"Sorry, couldn't create the narration ({e}).")
        return

    print(f"Narration saved to {AUDIO_FILE}. Playing...")
    if sys.platform == "win32":
        os.startfile(AUDIO_FILE)  # type: ignore[attr-defined]
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", AUDIO_FILE])


# ---- Main: interactive loop with user feedback ----------------------------
NO_CHANGE_ANSWERS = {"", "n", "no"}  # answers that mean "no more changes"
example_requests = "A story about a girl named Alice and her best friend Bob, who happens to be a cat."


def main():
    user_input = input("What kind of story do you want to hear? ").strip()
    if not user_input:
        user_input = example_requests
        print(f"(Using example: {user_input})")

    print("\nCooking up your story...\n")
    story, info = tell_story(user_input)
    print("\n" + "=" * 60 + "\n" + story + "\n" + "=" * 60)
    save_story(story)

    # User feedback loop: let the child/parent tweak the story.
    while True:
        change = input(
            "\nWant any changes to the story? Type what you'd like "
            "(e.g. 'make it funnier', 'add a dragon').\n"
            "Press Enter or type "No", to keep the story as is and move on: "
        ).strip()
        if change.lower().rstrip(".!") in NO_CHANGE_ANSWERS:
            break
        story = revise_story(story, [f"The listener asked: {change}"], info["kid_safe_request"])
        info["kid_safe_request"] += f" (Listener also asked: {change})"  # judge scores request_fit against the change
        story = improve_until_good(info["kid_safe_request"], story)  # judge still guards quality & safety
        print("\n" + "=" * 60 + "\n" + story + "\n" + "=" * 60)
        save_story(story)

    if input("\nWould you like me to read it to you? (y/N) ").strip().lower() in ("y", "yes"):
        print("Loading...")  # narration can take a few seconds; let the user know it isn't frozen
        read_aloud(story)
    print("Sweet dreams!")


if __name__ == "__main__":
    main()
