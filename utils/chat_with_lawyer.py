import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("GROQ_API_KEY")
BASE_URL = os.environ.get("OPENAI_BASE_URL")
MODEL_NAME = os.environ.get("OPENAI_MODEL")


class ChatWithLawyer:
    def __init__(self, query, user_progress, chat_till_now, api_key=API_KEY):
        self.api_key = api_key
        self.query = query
        self.user_progress = user_progress
        self.chat_till_now = chat_till_now

    def calculate_work_done_percentage(self):
        """Calculate percentage of work already completed by user"""
        progress_text = self.user_progress.lower()

        overall_match = re.search(r'overall progress: ([\d.]+)%', progress_text)
        if overall_match:
            return float(overall_match.group(1))

        queries = re.search(r'query analysis: (\d+)/(\d+)', progress_text)
        docs = re.search(r'documents processed: (\d+)/(\d+)', progress_text)
        deadlines = re.search(r'deadlines managed: (\d+)/(\d+)', progress_text)
        ai_tasks = re.search(r'ai tasks completed: (\d+)/(\d+)', progress_text)

        total_tasks = 0
        completed_tasks = 0

        if queries:
            completed_tasks += int(queries.group(1))
            total_tasks += int(queries.group(2))

        if docs:
            completed_tasks += int(docs.group(1))
            total_tasks += int(docs.group(2))

        if deadlines:
            completed_tasks += int(deadlines.group(1))
            total_tasks += int(deadlines.group(2))

        if ai_tasks:
            completed_tasks += int(ai_tasks.group(1))
            total_tasks += int(ai_tasks.group(2))

        return (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

    def detect_fee_discussion(self):
        """Detect if current conversation involves fee discussion"""
        chat_text = self.chat_till_now.lower()

        fee_keywords = [
            'fee',
            'cost',
            'price',
            'payment',
            'charge',
            'bill',
            'invoice',
            'amount',
            'money',
            'dollar',
            'thousand',
            'k usd',
            'rate',
            'hourly'
        ]

        return any(keyword in chat_text for keyword in fee_keywords)

    def extract_mentioned_fee(self):
        """Extract any fee amounts mentioned in the chat"""

        fee_patterns = [
            r'(\d+)k usd',
            r'(\d+) thousand',
            r'\$(\d+,?\d*)',
            r'(\d+) dollars'
        ]

        for pattern in fee_patterns:
            match = re.search(pattern, self.chat_till_now.lower())

            if match:
                fee_str = match.group(1).replace(',', '')

                try:
                    return int(fee_str) * (
                        1000 if 'k' in pattern or 'thousand' in pattern else 1
                    )

                except ValueError:
                    continue

        return None

    def generate_response(self):
        work_percentage = self.calculate_work_done_percentage()

        try:
            work_percentage = float(work_percentage)

        except (ValueError, TypeError):
            work_percentage = 0.0

        is_fee_discussion = self.detect_fee_discussion()
        mentioned_fee = self.extract_mentioned_fee()

        potential_savings = ""

        if mentioned_fee and work_percentage > 0:
            saved_amount = mentioned_fee * (work_percentage / 100)
            new_fee = mentioned_fee - saved_amount

            potential_savings = f"""

COST ANALYSIS:
- Standard fee mentioned: ${mentioned_fee:,}
- Your preparation completed: {work_percentage:.1f}%
- Potential savings: ${saved_amount:,.0f}
- Suggested fair fee: ${new_fee:,.0f}
"""

        negotiation_context = ""

        if is_fee_discussion:
            negotiation_context = """
You are in a FEE NEGOTIATION scenario. Your primary goals:
1. Advocate for fair pricing based on work already completed
2. Highlight the user's preparation and documentation efforts
3. Use data-driven arguments for fee reduction
4. Maintain professional but assertive tone
5. Suggest specific percentage-based reductions
"""

        full_prompt = f"""
You are an AI legal assistant helping a user negotiate with their lawyer. Your role is to:
1. Support the user's interests while maintaining professionalism
2. Help craft persuasive, data-driven arguments
3. Suggest fair fee negotiations based on work completed
4. Provide strategic communication advice

{negotiation_context}

CONTEXT:
- User's legal matter: {self.query}
- User's preparation progress: {self.user_progress}
- Current conversation: {self.chat_till_now}
- Work completed by user: {work_percentage:.1f}%

{potential_savings}

INSTRUCTIONS:
- Generate a helpful response for the user to send to their lawyer
- If discussing fees, emphasize the user's preparation work and suggest fair pricing
- Use specific percentages and amounts when relevant
- Be professional but advocate strongly for the user
- Focus on value delivered vs. standard rates
- If not fee-related, provide general legal communication assistance

Return ONLY a valid JSON object with the following format, and nothing else:
{{
  "assistant_reply": "string",
  "negotiation_strategy": "string",
  "potential_savings": "string"
}}
"""

        try:

            if not self.api_key:
                raise Exception(
                    "GROQ_API_KEY not found in environment variables"
                )

            print(f"==== API KEY CHECK ====")
            print(f"API Key exists: {bool(self.api_key)}")
            print(f"API Key length: {len(self.api_key) if self.api_key else 0}")

            client = OpenAI(
                api_key=self.api_key,
                base_url=BASE_URL
            )

            print("==== CLIENT INITIALIZED ====")

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ],
                temperature=0.7
            )

            print("==== API CALL COMPLETED ====")

            print("==== RAW OPENAI RESPONSE ====")
            print(response)

            try:
                response_text = response.choices[0].message.content.strip()

                print("==== EXTRACTED TEXT ====")
                print(response_text)

            except Exception as inner_e:
                print("==== TEXT EXTRACTION ERROR ====")
                print(inner_e)
                raise

            match = re.search(r"\{.*\}", response_text, re.DOTALL)

            if match:
                json_text = match.group(0)
                parsed = json.loads(json_text)

            else:
                raise json.JSONDecodeError(
                    "No JSON found",
                    response_text,
                    0
                )

        except (json.JSONDecodeError, Exception) as e:

            print(f"==== ERROR ====")
            print(str(e))

            if is_fee_discussion and work_percentage > 20:

                fallback_message = f"""Dear [Lawyer's Name],

I wanted to discuss the fee structure for my case. I've been quite proactive in preparing the groundwork:

• Completed {work_percentage:.1f}% of preliminary work through our legal platform
• Analyzed and organized all relevant documents
• Prepared comprehensive case timeline and deadlines
• Conducted initial legal research

Given this substantial preparation, I believe a fee adjustment reflecting the work already completed would be fair. Would you be open to discussing a rate that accounts for these efforts?

Best regards"""

            else:
                fallback_message = (
                    "I'd like to discuss this matter further. "
                    "Could you provide more details about your approach and timeline?"
                )

            parsed = {
                "assistant_reply": fallback_message,
                "negotiation_strategy": (
                    "Professional fee negotiation based on completed work"
                    if is_fee_discussion
                    else "General inquiry"
                ),
                "potential_savings": f"{work_percentage:.1f}% work completed"
            }

        return parsed
