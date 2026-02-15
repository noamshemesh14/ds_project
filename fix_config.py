"""
Script to check and fix configuration for LLMod.ai
"""
import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("Configuration Check and Fix for LLMod.ai")
print("=" * 60)

# Check current configuration
openai_key = os.getenv("OPENAI_API_KEY")
llmod_key = os.getenv("LLMOD_API_KEY") or os.getenv("LLM_API_KEY")
embedding_base_url = os.getenv("EMBEDDING_BASE_URL")
llmod_base_url = os.getenv("LLMOD_BASE_URL") or os.getenv("LLM_BASE_URL")
llmod_model = os.getenv("LLMOD_MODEL") or os.getenv("LLM_MODEL")

print("\nCurrent Configuration:")
print("-" * 60)
print(f"OPENAI_API_KEY: {'SET' if openai_key else 'NOT SET'}")
if openai_key:
    print(f"  Value: {openai_key[:10]}...{openai_key[-4:]} (length: {len(openai_key)})")

print(f"LLMOD_API_KEY: {'SET' if llmod_key else 'NOT SET'}")
if llmod_key:
    print(f"  Value: {llmod_key[:10]}...{llmod_key[-4:]} (length: {len(llmod_key)})")

print(f"LLM_API_KEY: {'SET' if os.getenv('LLM_API_KEY') else 'NOT SET'}")

print(f"EMBEDDING_BASE_URL: {embedding_base_url or 'NOT SET'}")
print(f"LLMOD_BASE_URL: {llmod_base_url or 'NOT SET (will use default: https://api.llmod.ai/v1)'}")
print(f"LLMOD_MODEL: {llmod_model or 'NOT SET (will use default: gpt-3.5-turbo)'}")

print("\n" + "=" * 60)
print("Analysis:")
print("=" * 60)

# Check if we should use LLMod.ai
should_use_llmod = embedding_base_url and "llmod" in embedding_base_url.lower()

if should_use_llmod:
    print("\n[INFO] EMBEDDING_BASE_URL points to LLMod.ai")
    if not llmod_key:
        print("[PROBLEM] LLMOD_API_KEY is not set!")
        if openai_key and len(openai_key) == 25:
            print(f"[SUGGESTION] Your OPENAI_API_KEY ({openai_key[:10]}...) looks like an LLMod.ai key (25 chars)")
            print("            You should move it to LLMOD_API_KEY")
            print("\nTo fix:")
            print("1. In .env file, add:")
            print(f"   LLMOD_API_KEY={openai_key}")
            print("2. Optionally, remove or comment out OPENAI_API_KEY")
            print("3. Set LLMOD_MODEL if needed (e.g., RPRTHPB-gpt-5-mini)")
        else:
            print("[ACTION] Please set LLMOD_API_KEY in .env file")
    else:
        print("[OK] LLMOD_API_KEY is set")
        
    if not llmod_model:
        print("[INFO] LLMOD_MODEL not set - will use default: gpt-3.5-turbo")
        print("       If you want to use GPT-5-Mini, set: LLMOD_MODEL=RPRTHPB-gpt-5-mini")
else:
    print("\n[INFO] EMBEDDING_BASE_URL is not set or doesn't point to LLMod.ai")
    print("       Will use standard OpenAI API")

print("\n" + "=" * 60)
print("Recommended .env configuration for LLMod.ai:")
print("=" * 60)
print("""
# LLMod.ai Configuration
LLMOD_API_KEY=sk-NaXQH1ceM3FDA638o5XV8Q
LLMOD_BASE_URL=https://api.llmod.ai
LLMOD_MODEL=RPRTHPB-gpt-5-mini

# Embedding Configuration (for RAG)
EMBEDDING_BASE_URL=https://api.llmod.ai
EMBEDDING_MODEL=RPRTHPB-text-embedding-3-small

# Pinecone (for RAG)
PINECONE_API_KEY=your_pinecone_key_here

# Optional: Remove or comment out OPENAI_API_KEY if not using OpenAI
# OPENAI_API_KEY=
""")

print("=" * 60)
print("After updating .env, restart the server and run test_api_keys.py")
print("=" * 60)

