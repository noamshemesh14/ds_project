Put new .txt files here for RAG chat (Hebrew/English; save as UTF-8).
Then run from project root:

  py -m app.rag.embed_and_upsert --incremental

Only files in this folder will be embedded; existing RAG data is not re-embedded.
The new chunks are added to the same Pinecone index, so the chat will use both old and new data.
