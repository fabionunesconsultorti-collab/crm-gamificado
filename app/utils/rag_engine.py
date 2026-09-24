import os
import re
import logging
import requests
from app.models import Setting

logger = logging.getLogger(__name__)

class RAGEngine:
    _chroma_client = None
    _collection = None

    @classmethod
    def get_collection(cls):
        """Retorna a coleção persistente do ChromaDB inicializada de forma singleton e resiliente."""
        if cls._collection is None:
            try:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                persist_dir = os.path.join(os.getcwd(), 'chroma_data')
                os.makedirs(persist_dir, exist_ok=True)

                cls._chroma_client = chromadb.PersistentClient(
                    path=persist_dir,
                    settings=ChromaSettings(anonymized_telemetry=False)
                )
                cls._collection = cls._chroma_client.get_or_create_collection(
                    name="crm_business_knowledge",
                    metadata={"hnsw:space": "cosine"}
                )
                logger.info(f"[RAGEngine] ChromaDB inicializado com sucesso em '{persist_dir}'.")
            except Exception as e:
                logger.error(f"[RAGEngine] Erro ao inicializar ChromaDB: {e}", exc_info=True)
                return None
        return cls._collection

    @staticmethod
    def get_embedding(text: str, ollama_url: str = None, model: str = "nomic-embed-text"):
        """
        Gera o vetor numérico (embedding) para um texto.
        Prioriza o Ollama local (nomic-embed-text) e faz fallback transparente para Gemini se configurado.
        """
        if not text or not text.strip():
            return None

        # 1. Tenta obter via Ollama local
        base_url = ollama_url or Setting.get_val('ai_ollama_url') or os.environ.get('OLLAMA_URL', 'http://localhost:11434')
        base_url = base_url.rstrip('/')

        try:
            resp = requests.post(
                f"{base_url}/api/embeddings",
                json={"model": model, "prompt": text.strip()},
                timeout=12
            )
            if resp.status_code == 200:
                data = resp.json()
                emb = data.get("embedding")
                if emb:
                    return emb
        except Exception as e:
            logger.debug(f"[RAGEngine] Ollama embedding indisponível ({base_url}): {e}")

        # 2. Fallback: Google Gemini Embeddings se houver API Key
        gemini_key = Setting.get_val('ai_api_key')
        if gemini_key:
            try:
                from google import genai
                client = genai.Client(api_key=gemini_key)
                response = client.models.embed_content(
                    model='text-embedding-004',
                    contents=text
                )
                if response and hasattr(response, 'embedding') and hasattr(response.embedding, 'values'):
                    return response.embedding.values
            except Exception as e:
                logger.warning(f"[RAGEngine] Falha no fallback de embedding Gemini: {e}")

        return None

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80):
        """
        Fatia textos longos preservando fronteiras de sentenças/parágrafos e aplicando sobreposição (overlap).
        """
        if not text:
            return []
        
        # Normaliza quebras de linha
        clean = text.replace('\r\n', '\n').strip()
        if len(clean) <= chunk_size:
            return [clean]

        paragraphs = clean.split('\n\n')
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    # Inicia próximo com os últimos caracteres de overlap
                    overlap_seed = current_chunk[-overlap:] if len(current_chunk) > overlap else ""
                    current_chunk = f"{overlap_seed} {para}".strip()
                else:
                    # Parágrafo maior que chunk_size: divide por frases ou blocos
                    words = para.split(' ')
                    temp_chunk = ""
                    for w in words:
                        if len(temp_chunk) + len(w) + 1 <= chunk_size:
                            temp_chunk = f"{temp_chunk} {w}".strip()
                        else:
                            if temp_chunk:
                                chunks.append(temp_chunk.strip())
                            temp_chunk = w
                    if temp_chunk:
                        current_chunk = temp_chunk

        if current_chunk and current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    @classmethod
    def index_document(cls, doc_id: int, title: str, content: str, category: str = "geral"):
        """
        Fatia, vetoriza e indexa um documento no ChromaDB.
        Remove versões anteriores do mesmo doc_id antes de reindexar.
        """
        col = cls.get_collection()
        if col is None:
            logger.error("[RAGEngine] Coleção ChromaDB indisponível para indexação.")
            return 0

        # Remove trechos antigos deste documento
        cls.remove_document(doc_id)

        chunks = cls.chunk_text(content, chunk_size=450, overlap=70)
        if not chunks:
            return 0

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for idx, chunk in enumerate(chunks):
            # Enriquece o trecho com o título do documento para guiar a busca semântica
            full_text = f"Fonte: {title} ({category})\n{chunk}"
            emb = cls.get_embedding(full_text)
            if emb:
                chunk_id = f"doc_{doc_id}_chunk_{idx}"
                ids.append(chunk_id)
                embeddings.append(emb)
                documents.append(full_text)
                metadatas.append({
                    "doc_id": int(doc_id),
                    "title": str(title),
                    "category": str(category),
                    "chunk_index": int(idx)
                })

        if ids and embeddings:
            try:
                col.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas
                )
                logger.info(f"[RAGEngine] Documento {doc_id} ('{title}') indexado com {len(ids)} chunks.")
                return len(ids)
            except Exception as e:
                logger.error(f"[RAGEngine] Erro ao salvar chunks no ChromaDB: {e}", exc_info=True)
                return 0

        return 0

    @classmethod
    def remove_document(cls, doc_id: int):
        """Remove todos os chunks associados a um doc_id no ChromaDB."""
        col = cls.get_collection()
        if col is None:
            return False
        try:
            col.delete(where={"doc_id": int(doc_id)})
            return True
        except Exception as e:
            logger.warning(f"[RAGEngine] Aviso ao deletar chunks do doc {doc_id}: {e}")
            return False

    @classmethod
    def search_relevant_snippets(cls, query: str, top_k: int = 3, max_distance: float = 0.55):
        """
        Realiza busca semântica no ChromaDB para a pergunta do cliente.
        Retorna lista de dicionários com 'text', 'title', 'category' e 'score'.
        """
        if not query or not query.strip():
            return []

        col = cls.get_collection()
        if col is None:
            return []

        query_emb = cls.get_embedding(query.strip())
        if not query_emb:
            return []

        try:
            results = col.query(
                query_embeddings=[query_emb],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )
            
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            snippets = []
            for doc, meta, dist in zip(docs, metas, distances):
                # Distância cosseno: 0 = idêntico, 1 = oposto.
                if dist <= max_distance:
                    snippets.append({
                        "text": doc,
                        "title": meta.get("title", "Geral"),
                        "category": meta.get("category", "geral"),
                        "distance": round(float(dist), 4),
                        "score": round(1.0 - float(dist), 2)
                    })
            return snippets
        except Exception as e:
            logger.error(f"[RAGEngine] Erro na busca semântica: {e}", exc_info=True)
            return []

    @classmethod
    def get_formatted_context(cls, query: str, top_k: int = 3):
        """
        Retorna string pronta para injeção no prompt do sistema com as informações oficiais.
        """
        snippets = cls.search_relevant_snippets(query, top_k=top_k)
        if not snippets:
            return ""

        context_lines = []
        for s in snippets:
            context_lines.append(f"- [{s['title']}]: {s['text']}")

        return "\n".join(context_lines)

    @staticmethod
    def extract_text_from_pdf(file_stream):
        """Extrai texto de um arquivo PDF carregado pelo usuário."""
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_stream)
            extracted = []
            for page_idx, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                if txt.strip():
                    extracted.append(f"--- Página {page_idx + 1} ---\n{txt.strip()}")
            return "\n\n".join(extracted)
        except Exception as e:
            logger.error(f"[RAGEngine] Erro ao extrair texto do PDF: {e}")
            return ""
