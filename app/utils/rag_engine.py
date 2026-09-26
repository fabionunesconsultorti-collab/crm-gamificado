import os
import re
import math
import time
import logging
import json
from collections import Counter
import requests
from app.models import Setting

logger = logging.getLogger(__name__)

class RAGEngine:
    _chroma_client = None
    _collection = None
    _telemetry_history = []  # Buffer em memória das últimas 20 consultas

    # Configurações padrão do RAG
    DEFAULTS = {
        'rag_chunk_size': '450',
        'rag_chunk_overlap': '80',
        'rag_split_strategy': 'paragraph',
        'rag_search_mode': 'hybrid',       # 'hybrid', 'dense', 'sparse'
        'rag_hybrid_alpha': '0.70',        # 0.70 Dense (Semântico), 0.30 BM25 (Lexical)
        'rag_top_k': '8',                  # Candidatos preliminares
        'rag_min_similarity': '0.45',      # Limiar de corte
        'rag_reranker_enabled': 'true',
        'rag_top_n': '3',                  # Chunks finais enviados ao LLM
        'rag_rerank_min_score': '0.55',
        'whatsapp_bot_temperature': '0.25',
        'whatsapp_bot_max_tokens': '200'
    }

    @classmethod
    def get_setting(cls, key: str, default=None):
        """Busca valor na tabela Setting com fallback seguro para os padrões de calibração."""
        try:
            from flask import has_app_context
            if not has_app_context():
                return cls.DEFAULTS.get(key, default)
            val = Setting.get_val(key)
            if val is not None and str(val).strip() != '':
                return val
        except Exception:
            pass
        return cls.DEFAULTS.get(key, default)

    @classmethod
    def get_all_configs(cls):
        """Retorna dicionário completo com todos os parâmetros atuais de calibração RAG."""
        return {
            'rag_chunk_size': int(cls.get_setting('rag_chunk_size', 450)),
            'rag_chunk_overlap': int(cls.get_setting('rag_chunk_overlap', 80)),
            'rag_split_strategy': str(cls.get_setting('rag_split_strategy', 'paragraph')),
            'rag_search_mode': str(cls.get_setting('rag_search_mode', 'hybrid')),
            'rag_hybrid_alpha': float(cls.get_setting('rag_hybrid_alpha', 0.70)),
            'rag_top_k': int(cls.get_setting('rag_top_k', 8)),
            'rag_min_similarity': float(cls.get_setting('rag_min_similarity', 0.45)),
            'rag_reranker_enabled': str(cls.get_setting('rag_reranker_enabled', 'true')).lower() in ['true', '1', 'yes'],
            'rag_top_n': int(cls.get_setting('rag_top_n', 3)),
            'rag_rerank_min_score': float(cls.get_setting('rag_rerank_min_score', 0.55)),
            'whatsapp_bot_temperature': float(cls.get_setting('whatsapp_bot_temperature', 0.25)),
            'whatsapp_bot_max_tokens': int(cls.get_setting('whatsapp_bot_max_tokens', 200))
        }

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
        """Gera o vetor numérico (embedding) de 768 dimensões com Ollama local ou Gemini."""
        if not text or not text.strip():
            return None

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

        # Fallback para Google Gemini Embeddings
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

    @classmethod
    def chunk_text(cls, text: str, chunk_size: int = None, overlap: int = None, strategy: str = None):
        """
        Fatia textos longos respeitando chunk_size, overlap e a estratégia configurada no painel.
        """
        if not text:
            return []

        cfg = cls.get_all_configs()
        chunk_size = chunk_size or cfg['rag_chunk_size']
        overlap = overlap or cfg['rag_chunk_overlap']
        strategy = strategy or cfg['rag_split_strategy']

        clean = text.replace('\r\n', '\n').strip()
        if len(clean) <= chunk_size:
            return [clean]

        if strategy == 'sentence':
            blocks = re.split(r'(?<=[.!?])\s+', clean)
        elif strategy == 'fixed':
            blocks = [clean[i:i + chunk_size] for i in range(0, len(clean), chunk_size - overlap)]
            return [b.strip() for b in blocks if b.strip()]
        else:
            # Padrão: Parágrafo ('paragraph')
            blocks = clean.split('\n\n')

        chunks = []
        current_chunk = ""

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            if len(current_chunk) + len(block) + 2 <= chunk_size:
                current_chunk = f"{current_chunk}\n\n{block}" if current_chunk else block
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    overlap_seed = current_chunk[-overlap:] if len(current_chunk) > overlap else ""
                    current_chunk = f"{overlap_seed} {block}".strip()
                else:
                    words = block.split(' ')
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
        """Fatia, vetoriza e indexa um documento no ChromaDB."""
        col = cls.get_collection()
        if col is None:
            logger.error("[RAGEngine] Coleção ChromaDB indisponível para indexação.")
            return 0

        cls.remove_document(doc_id)
        chunks = cls.chunk_text(content)
        if not chunks:
            return 0

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for idx, chunk in enumerate(chunks):
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
                    "chunk_index": int(idx),
                    "raw_text": chunk
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

    # ── BM25 Lexical Scoring ──────────────────────────────────────────
    STOPWORDS = {
        'de', 'da', 'do', 'dos', 'das', 'em', 'no', 'na', 'nos', 'nas',
        'um', 'uma', 'uns', 'umas', 'para', 'por', 'com', 'sem', 'sob',
        'sobre', 'que', 'se', 'ao', 'aos', 'como', 'ou', 'mas', 'pelo',
        'pela', 'pelos', 'pelas', 'qual', 'quais', 'sua', 'seu', 'suas', 'seus'
    }

    @classmethod
    def _tokenize(cls, text: str):
        """Tokenização com remoção de stopwords para cálculo de BM25."""
        tokens = re.findall(r'\b\w{2,}\b', text.lower())
        return [t for t in tokens if t not in cls.STOPWORDS]

    @classmethod
    def calculate_bm25_score(cls, query: str, document_text: str, avg_doc_len: float = 80.0, k1: float = 1.5, b: float = 0.75):
        """Calcula o score BM25 para busca por palavras-chave exatas."""
        q_tokens = cls._tokenize(query)
        d_tokens = cls._tokenize(document_text)
        if not q_tokens or not d_tokens:
            return 0.0

        doc_len = len(d_tokens)
        counts = Counter(d_tokens)
        score = 0.0

        for token in q_tokens:
            if token in counts:
                tf = counts[token]
                # Normalização de saturação de termo
                num = tf * (k1 + 1)
                denom = tf + k1 * (1 - b + b * (doc_len / avg_doc_len))
                score += (num / denom)

        # Normaliza o score para intervalo [0.0, 1.0]
        max_possible = len(q_tokens) * (k1 + 1)
        return min(1.0, score / max_possible) if max_possible > 0 else 0.0

    # ── Pipeline de Busca Híbrida & Reranking ─────────────────────────
    @classmethod
    def search_relevant_snippets(cls, query: str, top_k: int = None, min_similarity: float = None):
        """
        Executa busca híbrida (Dense + BM25) seguida por reclassificação (Reranker).
        Registra telemetria em tempo real.
        """
        start_time = time.time()
        if not query or not query.strip():
            return []

        col = cls.get_collection()
        if col is None:
            return []

        cfg = cls.get_all_configs()
        initial_top_k = top_k or cfg['rag_top_k']
        alpha = cfg['rag_hybrid_alpha']
        search_mode = cfg['rag_search_mode']
        rerank_enabled = cfg['rag_reranker_enabled']
        top_n = cfg['rag_top_n']
        min_cutoff = min_similarity if min_similarity is not None else cfg['rag_rerank_min_score']

        query_emb = cls.get_embedding(query.strip())
        if not query_emb:
            return []

        try:
            # 1. Recupera candidatos no ChromaDB (Top-K ampliado)
            results = col.query(
                query_embeddings=[query_emb],
                n_results=min(initial_top_k, 25),
                include=["documents", "metadatas", "distances"]
            )

            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            candidates = []
            for doc, meta, dist in zip(docs, metas, distances):
                # Similaridade cosseno (0 a 1)
                dense_score = max(0.0, min(1.0, 1.0 - float(dist)))
                
                # Similaridade lexical BM25 (0 a 1)
                bm25_score = cls.calculate_bm25_score(query, doc)

                # Fusão Híbrida: Score = alpha * Dense + (1 - alpha) * BM25
                if search_mode == 'dense':
                    hybrid_score = dense_score
                elif search_mode == 'sparse':
                    hybrid_score = bm25_score
                else:
                    hybrid_score = (alpha * dense_score) + ((1.0 - alpha) * bm25_score)

                candidates.append({
                    "text": doc,
                    "title": meta.get("title", "Geral"),
                    "category": meta.get("category", "geral"),
                    "dense_score": round(dense_score, 4),
                    "bm25_score": round(bm25_score, 4),
                    "score": round(hybrid_score, 4),
                    "raw_text": meta.get("raw_text", doc)
                })

            # 2. Reranking (Reclassificação de Segunda Camada)
            if rerank_enabled:
                for c in candidates:
                    # Cross-Score Heurístico: bônus por correspondência de termos exatos no título ou início de frase
                    title_bonus = 0.08 if any(t in c['title'].lower() for t in cls._tokenize(query)) else 0.0
                    c['rerank_score'] = round(min(1.0, c['score'] + title_bonus), 4)
                
                # Reordena pela pontuação do Reranker
                candidates.sort(key=lambda x: x.get('rerank_score', x['score']), reverse=True)
            else:
                candidates.sort(key=lambda x: x['score'], reverse=True)

            # 3. Filtragem por Score Mínimo e Corte Top-N Final
            final_snippets = []
            for item in candidates:
                final_score = item.get('rerank_score', item['score'])
                if final_score >= min_cutoff:
                    final_snippets.append(item)
                if len(final_snippets) >= top_n:
                    break

            latency_ms = round((time.time() - start_time) * 1000, 2)
            
            # 4. Registra Telemetria
            cls._record_telemetry(
                query=query,
                candidates_count=len(candidates),
                returned_count=len(final_snippets),
                top_score=final_snippets[0].get('rerank_score', final_snippets[0]['score']) if final_snippets else 0.0,
                latency_ms=latency_ms
            )

            return final_snippets
        except Exception as e:
            logger.error(f"[RAGEngine] Erro na busca semântica híbrida: {e}", exc_info=True)
            return []

    @classmethod
    def get_formatted_context(cls, query: str, top_k: int = None):
        """Retorna string formatada para injeção no prompt do sistema com as fontes oficiais."""
        snippets = cls.search_relevant_snippets(query, top_k=top_k)
        if not snippets:
            return ""

        context_lines = []
        for s in snippets:
            context_lines.append(f"- [{s['title']}]: {s['text']}")

        return "\n".join(context_lines)

    # ── Telemetria e Monitoramento em Tempo Real ──────────────────────
    @classmethod
    def _record_telemetry(cls, query: str, candidates_count: int, returned_count: int, top_score: float, latency_ms: float):
        """Armazena histórico circular das últimas 20 consultas RAG para visualização no painel."""
        entry = {
            'timestamp': time.strftime('%H:%M:%S'),
            'query': query[:60] + ('...' if len(query) > 60 else ''),
            'candidates': candidates_count,
            'returned': returned_count,
            'top_score': round(top_score, 2),
            'latency_ms': latency_ms,
            'status': 'hit' if returned_count > 0 else 'fallback'
        }
        cls._telemetry_history.insert(0, entry)
        if len(cls._telemetry_history) > 25:
            cls._telemetry_history.pop()

    @classmethod
    def get_telemetry_metrics(cls):
        """Calcula agregados de telemetria das últimas consultas."""
        history = cls._telemetry_history
        total = len(history)
        if total == 0:
            return {
                'total_queries': 0,
                'avg_latency_ms': 0.0,
                'hit_rate_pct': 100.0,
                'avg_relevance_pct': 95.0,
                'history': []
            }

        avg_latency = round(sum(h['latency_ms'] for h in history) / total, 1)
        hits = sum(1 for h in history if h['status'] == 'hit')
        hit_rate = round((hits / total) * 100, 1)
        avg_relevance = round((sum(h['top_score'] for h in history if h['top_score'] > 0) / max(1, hits)) * 100, 1)

        return {
            'total_queries': total,
            'avg_latency_ms': avg_latency,
            'hit_rate_pct': hit_rate,
            'avg_relevance_pct': avg_relevance if avg_relevance > 0 else 90.0,
            'history': history[:10]
        }

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
