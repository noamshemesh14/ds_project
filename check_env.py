"""Quick check of .env file settings"""
from dotenv import load_dotenv
import os

load_dotenv()

print("Current .env settings:")
print("-" * 60)
print(f"OPENAI_API_KEY: {'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET'}")
if os.getenv('OPENAI_API_KEY'):
    key = os.getenv('OPENAI_API_KEY')
    print(f"  Length: {len(key)}")
    print(f"  Starts with: {key[:10]}...")

print(f"LLMOD_API_KEY: {'SET' if os.getenv('LLMOD_API_KEY') else 'NOT SET'}")
if os.getenv('LLMOD_API_KEY'):
    key = os.getenv('LLMOD_API_KEY')
    print(f"  Length: {len(key)}")
    print(f"  Starts with: {key[:10]}...")

print(f"LLM_API_KEY: {'SET' if os.getenv('LLM_API_KEY') else 'NOT SET'}")
if os.getenv('LLM_API_KEY'):
    key = os.getenv('LLM_API_KEY')
    print(f"  Length: {len(key)}")
    print(f"  Starts with: {key[:10]}...")

print(f"EMBEDDING_BASE_URL: {os.getenv('EMBEDDING_BASE_URL', 'NOT SET')}")
print(f"EMBEDDING_MODEL: {os.getenv('EMBEDDING_MODEL', 'NOT SET')}")
print(f"PINECONE_API_KEY: {'SET' if os.getenv('PINECONE_API_KEY') else 'NOT SET'}")

