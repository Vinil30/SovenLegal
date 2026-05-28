from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()


class Chatbot:
    def __init__(self, api_key=None, user_message="", query=""):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.base_url = os.environ.get("OPENAI_BASE_URL")
        self.model_name = os.environ.get("OPENAI_MODEL")

        self.messages = []
        self.query = query
        self.user_message = user_message

    def chat(self):
        self.messages.append({
            "role": "system",
            "content": f"You are a legal AI assistant helping in solving a legal query. The query is: {self.query}"
        })

        self.messages.append({
            "role": "user",
            "content": self.user_message
        })

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

        response = client.chat.completions.create(
            model=self.model_name,
            messages=self.messages
        )

        assistant_reply = response.choices[0].message.content

        self.messages.append({
            "role": "assistant",
            "content": assistant_reply
        })

        return assistant_reply
