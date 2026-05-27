import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL')
OPENAI_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct"


class Image_Analyser:
    def __init__(
        self,
        query,
        doc_type,
        base64_data,
        required_elements=None,
        visual_reference=None,
        api_key=OPENAI_API_KEY
    ):
        self.query = query
        self.doc_type = doc_type
        self.base64_data = base64_data
        self.required_elements = required_elements or []
        self.visual_reference = visual_reference or {}
        self.api_key = api_key

        self.system_prompt = f"""
You are an expert document verification assistant for Indian legal documents.

Document Type: {self.doc_type}
Legal Query Context: {self.query}

Required Elements to Check:
{json.dumps(self.required_elements, indent=2)}

Visual Reference Standards:
{json.dumps(self.visual_reference, indent=2)}

Your tasks:
1. Verify if this is a genuine {self.doc_type}
2. Check if ALL required elements are present and clearly visible
3. Validate against the visual reference standards
4. Assess document quality and authenticity markers

Provide your analysis in this JSON format:

{{
  "document_type_match": true,
  "authenticity_score": 0,
  "required_elements_check": {{
    "all_present": true,
    "missing_elements": [],
    "present_elements": []
  }},
  "visual_compliance": {{
    "matches_standard": true,
    "compliance_issues": []
  }},
  "quality_assessment": {{
    "readability": "good",
    "image_quality": "high",
    "potential_tampering": false
  }},
  "overall_validity": "valid",
  "detailed_analysis": "analysis text",
  "recommendations": []
}}

Return ONLY valid JSON.
"""

    def analyze_legal_doc(self):
        try:

            client = OpenAI(
                api_key=self.api_key,
                base_url=OPENAI_BASE_URL
            )

            image_data = self.base64_data

            if "," in image_data:
                image_data = image_data.split(",")[-1]

            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": self.system_prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                temperature=0.2
            )

            output = response.choices[0].message.content.strip()

            try:
                return json.loads(output)

            except json.JSONDecodeError:
                return {
                    "overall_validity": "error",
                    "detailed_analysis": (
                        f"Could not parse analysis result: {output}"
                    ),
                    "error": True
                }

        except Exception as e:
            return {
                "overall_validity": "error",
                "detailed_analysis": f"Analysis failed: {str(e)}",
                "error": True
            }