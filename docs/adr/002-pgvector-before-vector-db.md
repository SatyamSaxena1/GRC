# ADR-002: pgvector before any external vector database

## Context
Evidence chunks will eventually need semantic retrieval. Dedicated vector databases
(Pinecone, Weaviate, Qdrant) are the reflex choice.

## Decision
When embeddings are needed, use pgvector inside the PostgreSQL we already run. Do not
add a second datastore for the slice.

## Alternatives considered
- **Dedicated vector DB.** Better at billion-scale ANN; irrelevant at our volume.
- **In-process FAISS.** No persistence story, no multi-node story.

## Consequences
- One datastore to back up, secure, and apply RLS to — vectors inherit tenant isolation
  instead of needing a parallel implementation.
- Revisit if recall at scale degrades; the retrieval interface stays swappable.
- **Not yet built**: no embeddings or chunk table exist. Deterministic attribute
  extraction has not needed retrieval, so building it now would be speculative.
