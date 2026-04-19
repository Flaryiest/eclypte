import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
)

response = client.responses.create(model="gpt-5.2", instructions="Say hello", input="Say hello")
print(response)