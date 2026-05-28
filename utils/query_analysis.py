import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL')
OPENAI_MODEL = os.getenv('OPENAI_MODEL')


class Query_Analysis:
    def __init__(self, query, api_key=GROQ_API_KEY):
        self.query = query
        self.api_key = api_key

        self.system_prompt = """
You are an expert virtual legal advocate assistant.
Your ONLY task is to analyze if a legal query is solvable or not.

Rules:
1. If the query is clear and legally solvable → return:
{
  "status": "solvable",
  "message": "This legal query is solvable, please generate deadlines and documents required to keep track on your progress."
}

2. If it is solvable but very hard/complex → return:
{
  "status": "hard",
  "message": "This query is not easily solvable, but you can still try to solve it, please generate deadlines and documents required to keep track on your progress..Explore successful users with similar issues in our Find Users tab."
}

3. If it is irrelevant or not a legal issue → return:
{
  "status": "irrelevant",
  "message": "This query is not directly relevant. Explore successful users with similar issues in our Find Users tab."
}

⚠️ Important:
- Do NOT provide legal explanations, documents, or deadlines.
- Only return a JSON object with 'status' and 'message'.
"""

    def call_api(self):
        try:

            client = OpenAI(
                api_key=self.api_key,
                base_url=OPENAI_BASE_URL
            )

            full_prompt = (
                f"{self.system_prompt}\n\n"
                f"User Query: {self.query}"
            )

            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ],
                temperature=0.3
            )

            response = resp.choices[0].message.content.strip()

            start = response.find("{")
            end = response.rfind("}") + 1

            output = response[start:end]

            try:
                data = json.loads(output)
                return data

            except json.JSONDecodeError:
                return {
                    "status": "error",
                    "message": "Could not analyze query properly."
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"API call failed: {str(e)}"
            }
