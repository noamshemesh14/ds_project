"""Test chat without RAG - just LLM"""
import sys
import asyncio
sys.stdout.reconfigure(encoding='utf-8')

from app.agents.executors.rag_chat import RAGChatExecutor
from app.agents.llm_client import LLMClient

async def test_chat_simple():
    print("=" * 60)
    print("Testing Chat (LLM only, no RAG)")
    print("=" * 60)
    
    # Initialize
    executor = RAGChatExecutor()
    llm = LLMClient()
    
    print(f"\n1. LLM client: {'✅' if llm.client else '❌'}")
    print(f"2. LLM model: {llm.model}")
    print(f"3. Embedding client: {'✅' if executor.embedding_client else '❌ (will use LLM only)'}")
    print(f"4. Pinecone index: {'✅' if executor.pinecone_index else '❌ (will use LLM only)'}")
    
    if not llm.client:
        print("\n❌ LLM client not initialized. Cannot test.")
        return
    
    # Test question
    question = "איך קוראים לי?"
    
    user_context = {
        "profile": {
            "name": "נועם שמש",
            "faculty": "הנדסת מחשבים",
            "current_semester": "א'",
            "current_year": 3
        },
        "courses": [
            {"course_name": "מבנה נתונים", "course_number": "234218"}
        ]
    }
    
    print(f"\n{'='*60}")
    print(f"Question: {question}")
    print(f"{'='*60}")
    
    try:
        result = await executor.execute(
            user_id="test_user",
            query=question,
            llm_client=llm,
            user_context=user_context,
            ui_context={"source": "free_text"}
        )
        
        print(f"\nStatus: {result.get('status')}")
        if result.get('error'):
            print(f"Error: {result.get('error')}")
        if result.get('response'):
            response = result.get('response')
            print(f"\nResponse:")
            print(response)
            print(f"\nResponse length: {len(response)} chars")
        print(f"Context used: {result.get('context_used', False)}")
        print(f"Web search used: {result.get('web_search_used', False)}")
        print(f"Steps: {len(result.get('steps', []))}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        print(traceback.format_exc())
    
    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_chat_simple())


