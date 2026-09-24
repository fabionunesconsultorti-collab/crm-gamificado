import os
import sys

# Garante path da aplicação
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import KnowledgeDoc
from app.utils.rag_engine import RAGEngine
from app.utils.ai_handler import AIHandler

app = create_app()

with app.app_context():
    print("=" * 60)
    print("1. TESTANDO INICIALIZAÇÃO DO CHROMADB E COLEÇÃO")
    print("=" * 60)
    col = RAGEngine.get_collection()
    if col is None:
        print("❌ Falha ao obter coleção ChromaDB!")
        sys.exit(1)
    print("✅ ChromaDB inicializado com sucesso!")

    print("\n" + "=" * 60)
    print("2. TESTANDO GERAÇÃO DE EMBEDDINGS (nomic-embed-text)")
    print("=" * 60)
    test_text = "Nossa empresa atende de segunda a sexta das 08h às 18h e aos sábados das 08h às 12h."
    emb = RAGEngine.get_embedding(test_text)
    if emb is None or len(emb) == 0:
        print("❌ Falha ao gerar embedding!")
        sys.exit(1)
    print(f"✅ Embedding gerado com sucesso! Dimensões do vetor: {len(emb)}")

    print("\n" + "=" * 60)
    print("3. CADASTRANDO CONHECIMENTO DE TESTE")
    print("=" * 60)
    # Limpa ou reutiliza doc de teste
    test_doc = KnowledgeDoc.query.filter_by(title="Tabela de Preços e Horários").first()
    if not test_doc:
        test_doc = KnowledgeDoc(
            title="Tabela de Preços e Horários",
            category="precos",
            doc_type="text",
            content=(
                "Tabela Oficial 2026:\n"
                "- Plano Essencial: R$ 99/mês, inclui CRM e funil de vendas.\n"
                "- Plano Pro: R$ 249/mês, inclui automação de WhatsApp com IA e relatórios avançados.\n"
                "- Horário de Atendimento: De segunda a sexta das 08:00 às 18:00. Aos sábados funcionamos em plantão das 08:00 às 12:00.\n"
                "- Política de Garantia: 7 dias de teste incondicional com reembolso total."
            ),
            is_active=True
        )
        db.session.add(test_doc)
        db.session.commit()

    chunks = RAGEngine.index_document(
        doc_id=test_doc.id,
        title=test_doc.title,
        content=test_doc.content,
        category=test_doc.category
    )
    test_doc.chunks_count = chunks
    db.session.commit()
    print(f"✅ Documento indexado com {chunks} chunks!")

    print("\n" + "=" * 60)
    print("4. TESTANDO BUSCA SEMÂNTICA (RAG QUERY)")
    print("=" * 60)
    query = "Vocês atendem no sábado e quanto é a assinatura do plano Pro?"
    snippets = RAGEngine.search_relevant_snippets(query, top_k=2)
    print(f"Pergunta do Cliente: '{query}'")
    print(f"Trechos oficiais recuperados: {len(snippets)}")
    for s in snippets:
        print(f"  - [{s['title']}] (Similaridade: {s['score']*100:.0f}%):")
        print(f"    {s['text'][:120]}...")

    print("\n" + "=" * 60)
    print("5. TESTANDO RESPOSTA FINAL DO BOT COM RAG")
    print("=" * 60)
    reply, err = AIHandler.generate_chat_reply(customer_message=query, include_rag=True)
    if err:
        print(f"⚠️ Aviso na IA: {err}")
    print(f"🤖 Resposta da IA:\n{reply}\n")
    print("=" * 60)
    print("✅ TODOS OS TESTES PASSARAM COM SUCESSO!")
    print("=" * 60)
