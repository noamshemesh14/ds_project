"""
RAG Chat Executor
Handles informational questions using RAG (Retrieval-Augmented Generation) over academy data
RAG-only mode: requires embedding client and Pinecone index to function
"""
import logging
import os
import json
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("CHAT")

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("OpenAI library not installed. Install with: pip install openai")

try:
    from pinecone import Pinecone
    HAS_PINECONE = True
except ImportError:
    HAS_PINECONE = False
    logger.warning("Pinecone library not installed. Install with: pip install pinecone-client")

from app.rag.config import (
    EMBEDDING_BASE_URL,
    EMBEDDING_MODEL,
    PINECONE_INDEX_NAME,
    TOP_K,
    MAX_CONTEXT_LENGTH,
)


class RAGChatExecutor:
    def __init__(self):
        self.module_name = "rag_chat"
        self.embedding_client = None
        self.pinecone_index = None
        self.llm_client = None
        self._initialize_clients()

    def _initialize_clients(self):
        """Initialize OpenAI embedding client and Pinecone index"""
        logger.info("CHAT: 🔧 Initializing RAG Chat Executor...")

        if not HAS_OPENAI:
            logger.warning("CHAT: ❌ OpenAI library not available. RAG chat will be disabled.")
            return

        if not HAS_PINECONE:
            logger.warning("CHAT: ❌ Pinecone library not available. RAG chat will be disabled.")
            return

        # Initialize OpenAI client for embeddings
        # Check for LLMOD_API_KEY first if EMBEDDING_BASE_URL is set (for llmod.ai)
        embedding_api_key = None
        use_base_url = False
        embedding_model = EMBEDDING_MODEL
        
        if EMBEDDING_BASE_URL:
            embedding_api_key = os.getenv("LLMOD_API_KEY") or os.getenv("LLM_API_KEY")
            if embedding_api_key:
                logger.info(f"CHAT: ✅ Using LLMOD_API_KEY for embeddings (base_url: {EMBEDDING_BASE_URL})")
                use_base_url = True
                # For llmod.ai, use the model from config (should be RPRTHPB-text-embedding-3-small)
            else:
                # If EMBEDDING_BASE_URL points to llmod.ai, try using OPENAI_API_KEY with llmod base_url
                if "llmod" in EMBEDDING_BASE_URL.lower():
                    openai_key_temp = os.getenv("OPENAI_API_KEY")
                    if openai_key_temp:
                        logger.info(f"CHAT: ✅ EMBEDDING_BASE_URL points to LLMod.ai, using OPENAI_API_KEY with LLMod base_url")
                        embedding_api_key = openai_key_temp
                        use_base_url = True
                    else:
                        logger.warning("CHAT: ⚠️ EMBEDDING_BASE_URL is set to LLMod.ai but no LLMOD_API_KEY or OPENAI_API_KEY found")
                        logger.warning("CHAT: Please set LLMOD_API_KEY or OPENAI_API_KEY in .env file")
                        return
                else:
                    logger.warning("CHAT: ⚠️ EMBEDDING_BASE_URL is set but LLMOD_API_KEY/LLM_API_KEY not found")
                    logger.warning("CHAT: Will use OPENAI_API_KEY without base_url (standard OpenAI)")
                    # Override model to standard OpenAI model if not using llmod
                    embedding_model = "text-embedding-3-small"
        
        # Fallback to OPENAI_API_KEY if not using llmod.ai
        if not embedding_api_key:
            embedding_api_key = os.getenv("OPENAI_API_KEY")
            if not embedding_api_key:
                logger.warning("CHAT: ⚠️ No embedding API key found (checked LLMOD_API_KEY, LLM_API_KEY, OPENAI_API_KEY)")
                logger.warning("CHAT: Please set one of these keys in .env file")
                return
            # Use standard OpenAI model
            embedding_model = "text-embedding-3-small"
        
        logger.info(f"CHAT: ✅ Embedding API key found (length: {len(embedding_api_key)}, starts with: {embedding_api_key[:10]}...)")

        client_kw = {"api_key": embedding_api_key}
        if use_base_url and EMBEDDING_BASE_URL:
            # Ensure base_url ends with /v1 for OpenAI-compatible APIs
            base_url = EMBEDDING_BASE_URL
            if not base_url.endswith("/v1"):
                base_url = base_url + "/v1" if base_url.endswith("/") else base_url + "/v1"
            client_kw["base_url"] = base_url
            logger.info(f"CHAT: Using embedding base_url: {base_url}")
        else:
            logger.info("CHAT: Using standard OpenAI API (no base_url)")
        
        self.embedding_client = OpenAI(**client_kw)
        self.embedding_model = embedding_model  # Store model to use
        logger.info(f"CHAT: ✅ Initialized embedding client with model: {embedding_model}")

        # Initialize Pinecone
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        if not pinecone_api_key:
            logger.warning("CHAT: ⚠️ PINECONE_API_KEY not found. RAG chat will be disabled.")
            logger.warning("CHAT: Please set PINECONE_API_KEY in .env file")
            return
        
        logger.info(f"CHAT: ✅ PINECONE_API_KEY found (length: {len(pinecone_api_key)}, starts with: {pinecone_api_key[:10]}...)")

        try:
            pc = Pinecone(api_key=pinecone_api_key)
            self.pinecone_index = pc.Index(PINECONE_INDEX_NAME)
            logger.info(f"CHAT: ✅ Initialized Pinecone index: {PINECONE_INDEX_NAME}")
        except Exception as e:
            logger.error(f"CHAT: ❌ Failed to initialize Pinecone: {e}")
            self.pinecone_index = None

    def _embed_query(self, query: str) -> Optional[List[float]]:
        """Embed a query string using OpenAI embeddings"""
        if not self.embedding_client:
            logger.error("CHAT: ❌ Embedding client not initialized")
            return None

        try:
            # Use the model that was set during initialization
            model_to_use = getattr(self, 'embedding_model', EMBEDDING_MODEL)
            logger.info(f"CHAT: 🔍 Embedding query with model: {model_to_use}")
            response = self.embedding_client.embeddings.create(
                input=[query],
                model=model_to_use
            )
            embedding = response.data[0].embedding
            logger.info(f"CHAT: ✅ Query embedded successfully (dimension: {len(embedding)})")
            return embedding
        except Exception as e:
            error_msg = str(e)
            logger.error(f"CHAT: ❌ Error embedding query: {error_msg}")
            # Check if it's an authentication error
            if "401" in error_msg or "invalid_api_key" in error_msg or "Incorrect API key" in error_msg:
                logger.error("CHAT: ❌ API key authentication failed. Please check your OPENAI_API_KEY or LLMOD_API_KEY in .env file")
                logger.error("CHAT: For embeddings, you need either:")
                logger.error("CHAT:   1. OPENAI_API_KEY (for standard OpenAI)")
                logger.error("CHAT:   2. LLMOD_API_KEY + EMBEDDING_BASE_URL (for llmod.ai)")
            return None

    def _retrieve_context(self, query_embedding: List[float], top_k: int = None) -> List[Dict[str, Any]]:
        """Retrieve top_k most relevant chunks from Pinecone (no score filtering)"""
        if not self.pinecone_index:
            logger.warning("CHAT: ⚠️ Pinecone index not initialized")
            return []

        top_k = top_k or TOP_K
        try:
            logger.info(f"CHAT: 🔍 Querying Pinecone with top_k={top_k} (no score filtering)")
            results = self.pinecone_index.query(
                vector=query_embedding,
                top_k=top_k,
                include_metadata=True
            )
            logger.info(f"CHAT: 📊 Pinecone returned {len(results.matches)} matches")
            
            chunks = []
            for match in results.matches:
                # Include all chunks - no score filtering
                chunk_data = {
                    "text": match.metadata.get("text", ""),
                    "source_file": match.metadata.get("source_file", ""),
                    "source_type": match.metadata.get("source_type", ""),
                    "score": match.score,
                    "id": match.id
                }
                chunks.append(chunk_data)
                logger.debug(f"CHAT: 📄 Chunk {match.id}: score={match.score:.3f}, source={chunk_data['source_type']}, text_length={len(chunk_data['text'])}")
            
            # Log summary
            if chunks:
                scores = [c["score"] for c in chunks]
                logger.info(f"CHAT: ✅ Retrieved {len(chunks)} chunks from Pinecone")
                logger.info(f"CHAT: 📊 Score range: min={min(scores):.3f}, max={max(scores):.3f}, avg={sum(scores)/len(scores):.3f}")
            else:
                logger.warning(f"CHAT: ⚠️ No chunks retrieved from Pinecone!")
            
            return chunks
        except Exception as e:
            logger.error(f"CHAT: ❌ Error querying Pinecone: {e}")
            import traceback
            logger.error(f"CHAT: Pinecone error traceback: {traceback.format_exc()}")
            return []

    def _format_user_context(self, user_context: Optional[Dict[str, Any]]) -> str:
        """Format user context for LLM prompt"""
        if not user_context:
            return "No user context available."
        
        context_parts = []
        
        # Profile info
        if user_context.get("profile"):
            profile = user_context["profile"]
            if profile.get("name"):
                context_parts.append(f"Student name: {profile['name']}")
            if profile.get("faculty"):
                context_parts.append(f"Faculty: {profile['faculty']}")
            if profile.get("study_track"):
                context_parts.append(f"Study track: {profile['study_track']}")
            if profile.get("current_semester"):
                context_parts.append(f"Current semester: {profile['current_semester']}")
            if profile.get("current_year"):
                context_parts.append(f"Current year: {profile['current_year']}")
        
        # Courses
        if user_context.get("courses") and len(user_context["courses"]) > 0:
            courses = user_context["courses"][:10]  # Limit to 10 courses
            course_list = ", ".join([
                f"{c.get('course_name', '')} ({c.get('course_number', '')})"
                for c in courses
            ])
            context_parts.append(f"Current courses: {course_list}")
        
        # Preferences
        if user_context.get("preferences"):
            prefs = user_context["preferences"]
            if prefs.get("study_preferences_raw"):
                context_parts.append(f"Study preferences: {prefs['study_preferences_raw'][:200]}")
        
        return "\n".join(context_parts) if context_parts else "No user context available."

    async def execute(
        self,
        user_id: str,
        query: str,
        llm_client=None,
        user_context: Optional[Dict[str, Any]] = None,
        ui_context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute RAG chat: retrieve context and generate response
        
        Args:
            user_id: User ID
            query: User's question/query
            llm_client: LLMClient instance for generating responses
            user_context: Optional user context for personalization
            ui_context: Optional UI context (source, action_id, etc.)
        """
        logger.info(f"CHAT: 📨 Received query from user {user_id}: {query[:100]}...")
        logger.info(f"CHAT: Has llm_client: {llm_client is not None}, Has user_context: {user_context is not None}, Has ui_context: {ui_context is not None}")
        
        steps = []

        try:
            # Check LLM client first - this is required
            if not llm_client or not llm_client.client:
                logger.error("CHAT: ❌ LLM client not available for generating responses")
                return {
                    "status": "error",
                    "error": "LLM client not available for generating responses",
                    "response": "מצטער, אבל אני לא יכול ליצור תשובה כרגע. אנא נסה שוב מאוחר יותר.",
                    "steps": steps
                }

            self.llm_client = llm_client
            logger.info(f"CHAT: ✅ LLM client initialized (model: {llm_client.model})")
            
            # Check if RAG is available - RAG is required
            if not self.embedding_client or not self.pinecone_index:
                logger.error("CHAT: ❌ RAG system not initialized (embedding or Pinecone not available)")
                return {
                    "status": "error",
                    "error": "RAG system not available",
                    "response": "מצטער, אבל מערכת ה-RAG לא זמינה כרגע. אנא ודא שהמערכת מוגדרת כראוי (OPENAI_API_KEY, PINECONE_API_KEY).",
                    "steps": steps
                }

            # Step 1: Embed query
            logger.info(f"CHAT: 🔍 Step 1: Embedding query: {query[:100]}...")
            query_embedding = self._embed_query(query)
            if not query_embedding:
                logger.error("CHAT: ❌ Embedding failed - RAG cannot continue")
                return {
                    "status": "error",
                    "error": "Failed to embed query",
                    "response": "מצטער, אבל לא הצלחתי לעבד את השאלה שלך. אנא נסה שוב מאוחר יותר.",
                    "steps": steps
                }

            # Step 2: Retrieve relevant context from Pinecone
            logger.info(f"CHAT: 🔍 Step 2: Retrieving context from Pinecone (top_k={TOP_K}, no score filtering)...")
            context_chunks = self._retrieve_context(query_embedding, top_k=TOP_K)
            
            logger.info(f"CHAT: 📊 Retrieval results: {len(context_chunks)} chunks retrieved")
            if context_chunks:
                scores = [c.get("score", 0) for c in context_chunks]
                logger.info(f"CHAT: 📊 Score range: min={min(scores):.3f}, max={max(scores):.3f}, avg={sum(scores)/len(scores):.3f}")
                logger.info(f"CHAT: 📊 Scores: {[f'{s:.3f}' for s in scores]}")
                sources = list(set([c.get("source_type", "unknown") for c in context_chunks]))
                logger.info(f"CHAT: 📊 Sources found: {sources}")
            else:
                logger.warning(f"CHAT: ⚠️ No chunks retrieved from Pinecone!")
            
            retrieval_step = {
                "module": "rag_retrieval",
                "prompt": {
                    "query": query,
                    "top_k": TOP_K
                },
                "response": {
                    "chunks_retrieved": len(context_chunks),
                    "scores": [c.get("score", 0) for c in context_chunks],
                    "sources": list(set([c.get("source_type", "unknown") for c in context_chunks])),
                    "chunks": [{"source_type": c.get("source_type", "unknown"), "text": c.get("text", ""), "score": c.get("score", 0)} for c in context_chunks]
                }
            }
            steps.append(retrieval_step)

            # Step 3: Generate response - RAG only, chunks are required
            if not context_chunks:
                logger.warning(f"CHAT: ⚠️ No chunks retrieved from Pinecone")
                return {
                    "status": "error",
                    "error": "No context chunks retrieved",
                    "response": "מצטער, אבל לא מצאתי מידע רלוונטי במסמכי הטכניון כדי לענות על השאלה שלך. אנא נסה לנסח את השאלה מחדש או פנה למזכירות האקדמית לקבלת סיוע.",
                    "steps": steps
                }
            
            logger.info(f"CHAT: ✅ Step 3: Using {len(context_chunks)} context chunks from documents")
            response_text = await self._generate_response_with_fallback(
                query, context_chunks, user_context, steps
            )

            return {
                "status": "success",
                "response": response_text,
                "steps": steps,
                "context_used": len(context_chunks) > 0
            }

        except Exception as e:
            logger.error(f"CHAT: ❌ Error in RAG chat executor: {e}")
            import traceback
            logger.error(f"CHAT: Traceback: {traceback.format_exc()}")
            return {
                "status": "error",
                "error": f"RAG chat error: {str(e)}",
                "response": "מצטער, אבל נתקלתי בשגיאה. אנא נסה שוב.",
                "steps": steps
            }

    async def _generate_response_with_fallback(
        self,
        query: str,
        context_chunks: List[Dict[str, Any]],
        user_context: Optional[Dict[str, Any]],
        steps: List[Dict[str, Any]]
    ) -> str:
        """Generate response based on retrieved documents from RAG (RAG-only mode)"""
        # Combine context chunks (respecting MAX_CONTEXT_LENGTH)
        context_text = ""
        total_length = 0
        for chunk in context_chunks:
            chunk_text = f"[Source: {chunk.get('source_type', 'unknown')}]\n{chunk.get('text', '')}\n\n"
            if total_length + len(chunk_text) <= MAX_CONTEXT_LENGTH:
                context_text += chunk_text
                total_length += len(chunk_text)
            else:
                break

        system_prompt = """You are SemesterOS Agent, a smart academic advisor for Technion students.

Your role is to help with academic information, regulations, procedures, courses, and academic guidance based ONLY on the provided Technion documents.

LANGUAGE RULE:
Always respond in English unless the user explicitly asks for a different language in their question (e.g. "answer in Hebrew", "בעברית", "in Hebrew"). If they do not specify a language, use English.

KNOWLEDGE RULE (RAG ONLY):
You must base your answer strictly and exclusively on the Retrieved Context from official Technion documents provided below.

- Do NOT mention "provided documents", "uploaded files", or "context".
- Do NOT refer to the existence of internal files or sources.
- Simply present the information as official Technion policy.
- Begin with ONE short institutional opening sentence directly related to the topic.
- Do NOT use meta phrases (e.g., "Briefly", "In short", "Summary").

If the Retrieved Context does not contain a clear answer to the question:
- State briefly: "There is no official Technion information on this in the available regulations."
- Do NOT guess or add external knowledge.
- You may suggest contacting the relevant academic office if appropriate.

FORBIDDEN:
- Using phrases like "the documents specify" or "the retrieved rules"
- Explaining what the documents do not cover
- Listing missing details

STYLE:
- Be clear, structured, and professional.
- Use bullet points when helpful.
- Answer ONLY what is explicitly asked.
- Do NOT add sections about what is not specified unless the user explicitly asks.
- Be concise and to the point.
- Maintain a natural advisor tone.
- Never hallucinate.
"""

        user_prompt = f"""Context from Technion academy documents:

{context_text if context_text else "No specific context found in the knowledge base."}

User question: {query}

IMPORTANT: Answer in English unless the user explicitly asked for another language (e.g. Hebrew) in their question.

Please answer the user's question based ONLY on the Technion documents context provided. If the context doesn't contain sufficient information, say so honestly and suggest what they might ask instead or where to find the information."""

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            
            # gpt-5 models only support temperature=1
            model_name = self.llm_client.model.lower()
            temperature = 1.0 if "gpt-5" in model_name else 0.7

            response = await loop.run_in_executor(
                None,
                lambda: self.llm_client.client.chat.completions.create(
                    model=self.llm_client.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temperature
                )
            )

            llm_response_text = response.choices[0].message.content or ""

            steps.append({
                "module": "rag_answer_generator",
                "prompt": {
                    "query": query,
                    "has_context": bool(context_text),
                    "context_length": len(context_text),
                    "chunks_used": len(context_chunks),
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt
                },
                "response": {
                    "full_response": llm_response_text,
                    "response_length": len(llm_response_text),
                    "model": self.llm_client.model
                }
            })

            logger.info(f"CHAT: ✅ Generated response: {llm_response_text[:100]}...")
            return llm_response_text

        except Exception as e:
            error_msg = str(e)
            logger.error(f"CHAT: ❌ Error generating LLM response: {error_msg}")
            import traceback
            logger.error(f"CHAT: Traceback: {traceback.format_exc()}")
            
            # Check if it's an authentication error
            if "401" in error_msg or "invalid_api_key" in error_msg or "Incorrect API key" in error_msg or "AuthenticationError" in str(type(e)):
                logger.error("CHAT: ❌ API key authentication failed for LLM")
                return (
                    "מצטער, אבל יש בעיה עם מפתח ה-API. "
                    "אנא בדוק את הגדרות ה-OPENAI_API_KEY או LLMOD_API_KEY בקובץ .env. "
                    "אם הבעיה נמשכת, אנא פנה למנהל המערכת."
                )
            else:
                return "מצטער, אבל נתקלתי בשגיאה בעת יצירת התשובה. אנא נסה שוב."

    def get_step_log(
        self,
        prompt: Dict[str, Any],
        response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get step log for this executor"""
        return {
            "module": self.module_name,
            "prompt": prompt,
            "response": response
        }

