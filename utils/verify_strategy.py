import json
import re
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")


client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=OPENAI_BASE_URL
)


def run_ai_verification(case_title, strategy, milestones):
    """
    Send strategy + milestones to AI for verification and suggestions.
    Always returns a safe JSON structure.
    """

    milestones_text = "\n".join(
        [
            f"- {m['milestone_name']} "
            f"(Due: {m['due_date'].strftime('%d %b %Y')}, "
            f"Status: {m['status']})"
            for m in milestones if m.get("due_date")
        ]
    )

    prompt = f"""
You are a legal AI assistant.

A lawyer created the following case strategy:

Case Title: {case_title}

Strategy:
{strategy}

Deadlines/Milestones:
{milestones_text if milestones else "No milestones yet."}

✅ Task:
1. Verify if the strategy logically fits the case and milestones.
2. Point out strengths & weaknesses.
3. Suggest improvements or missing steps.
4. Suggest next deadlines if needed.

⚠️ IMPORTANT: Return your response strictly in valid JSON with this structure:

{{
  "analysis": "overall analysis text",
  "strengths": ["point 1", "point 2"],
  "weaknesses": ["point 1", "point 2"],
  "improvements": ["point 1", "point 2"],
  "suggested_deadlines": [
    {{
      "task": "string",
      "due_date": "DD MMM YYYY"
    }}
  ]
}}

Do not include Markdown formatting, explanations, or extra text.
Only return valid JSON.
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3
    )

    raw_text = response.choices[0].message.content.strip()

    json_data = _extract_json(raw_text)

    default_response = {
        "analysis": "",
        "strengths": [],
        "weaknesses": [],
        "improvements": [],
        "suggested_deadlines": []
    }

    if json_data:
        return {**default_response, **json_data}

    else:
        return {
            **default_response,
            "analysis": "Invalid JSON returned from AI"
        }


run_gemini_verification = run_ai_verification


def _extract_json(text):
    """Try multiple methods to extract JSON from AI response"""

    if not text:
        return None

    # Method 1: Direct JSON extraction
    start = text.find("{")
    end = text.rfind("}") + 1

    if start != -1 and end > start:

        try:
            return json.loads(text[start:end])

        except json.JSONDecodeError:
            pass

    # Method 2: Extract JSON from markdown code blocks
    code_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'

    matches = re.findall(
        code_block_pattern,
        text,
        re.DOTALL | re.IGNORECASE
    )

    for match in matches:

        try:
            return json.loads(match)

        except json.JSONDecodeError:
            continue

    # Method 3: Direct parsing
    try:
        return json.loads(text)

    except json.JSONDecodeError:
        return None
