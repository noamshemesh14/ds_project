"""Test RAG Chat flow with 2 questions"""
import sys
import asyncio
sys.stdout.reconfigure(encoding='utf-8')

from app.agents.executors.rag_chat import RAGChatExecutor
from app.agents.llm_client import LLMClient

async def test_rag_flow():
    print("=" * 60)
    print("Testing RAG Chat Flow")
    print("=" * 60)
    
    # Initialize
    executor = RAGChatExecutor()
    llm = LLMClient()
    
    print(f"\n1. Embedding client: {'✅' if executor.embedding_client else '❌'}")
    print(f"2. Pinecone index: {'✅' if executor.pinecone_index else '❌'}")
    print(f"3. LLM client: {'✅' if llm.client else '❌'}")
    
    if not executor.embedding_client or not executor.pinecone_index or not llm.client:
        print("\n❌ Not all systems initialized. Cannot test.")
        return
    
    # Test questions
    questions = [
        "מה ההקלות מילואים לסמסטר?",
        "איך קוראים לי?"
    ]
    
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
    
    for i, question in enumerate(questions, 1):
        print(f"\n{'='*60}")
        print(f"Question {i}: {question}")
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
                print(f"Response: {response[:200]}...")
                print(f"Response length: {len(response)} chars")
            print(f"Context used: {result.get('context_used', False)}")
            print(f"Steps: {len(result.get('steps', []))}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            print(traceback.format_exc())
    
    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_rag_flow())


