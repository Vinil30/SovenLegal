import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL')
OPENAI_MODEL = os.getenv('OPENAI_MODEL')


class Generate_Documents:
    def __init__(self, query, api_key=GROQ_API_KEY):
        self.query = query
        self.api_key = api_key

        self.system_prompt = """
You are an expert virtual legal advocate assistant.
Your task is to generate comprehensive document information for solving a legal query.

Rules:
1. Output must be a valid JSON.
2. Structure:
   {
     "documents": [
       {
         "name": "Document Name",
         "required_elements": [
           "Element 1",
           "Element 2",
           ...
         ],
         "visual_reference": {
           "document_type": "ID Card/Certificate/Form",
           "layout_description": "Brief description of how the document should look",
           "key_visual_features": [
             "Feature 1",
             "Feature 2"
           ],
           "typical_sections": [
             "Section 1",
             "Section 2",
             "Reference_Link"
           ]
         }
       }
     ]
   }

3. Focus on Indian legal documents and requirements.
4. Be specific about what elements must be present in each document.
5. Provide clear visual references to help identify authentic documents.
6. Provide a visual reference link via image link or any direct navigation link available on the internet as a part of typical_sections itself.
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
                    "documents": [
                        "Error: Could not generate documents properly."
                    ]
                }

        except Exception as e:
            return {
                "documents": [
                    f"API call failed: {str(e)}"
                ]
            }
