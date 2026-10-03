import os
import re
import yaml
import json
import logging
from typing import Dict, List, Optional, Tuple
from app import db
from app.models import BehaviorGuide, WahaInstance, Setting, KnowledgeDoc

logger = logging.getLogger(__name__)

MANDATORY_WHATSAPP_BREVITY_RULES = (
    "\n[DIRETRIZES FUNDAMENTAIS DE ATENDIMENTO WHATSAPP]:\n"
    "1. RESPOSTAS CURTAS E DIRETAS: Máximo de 1 a 2 frases diretas, padronizadas e profissionais (estilo WhatsApp comercial). "
    "Nunca faça introduções vazias ('Olá! Como posso te ajudar?', 'Com certeza!') ou respostas longas com vários parágrafos.\n"
    "2. POSTURA PROFISSIONAL: NUNCA aja como IA, robô ou ChatGPT. NUNCA cite termos técnicos internos como 'TensorFlow', 'Diretiva', 'RAG' ou 'Inteligência Artificial'.\n"
    "3. REGRA CRÍTICA DE FALTA DE CONTEXTO E PAUSA:\n"
    "Se você NÃO entender com precisão o que o cliente quis dizer, se a mensagem for ambígua, sem sentido, vaga, fora de contexto ou não respondida nas informações oficiais:\n"
    "NUNCA tente adivinhar, inventar ou responder genericamente.\n"
    "Você DEVE obrigatoriamente pausar o atendimento emitindo a tag [PAUSAR_ATENDIMENTO] seguida da mensagem de aviso:\n"
    "[PAUSAR_ATENDIMENTO] Não consegui compreender o contexto da sua mensagem. Vou pausar o atendimento automático para que nossa equipe humana dê continuidade por aqui em instantes."
)


class BehaviorParser:
    """
    Parser e Orquestrador de Guias de Comportamento (.md).
    Converte playbooks em Markdown em:
    1. Diretivas de Sistema (System Prompt para Ollama/LLM).
    2. Documentos e Skills prioritárias no RAG (ChromaDB).
    3. Metadados estruturados por nicho e instância de atendimento.
    """

    @classmethod
    def parse_markdown(cls, md_content: str, filename: Optional[str] = None) -> Dict:
        """Extrai metadados, prompt de sistema e seções de conhecimento a partir do Markdown."""
        lines = md_content.splitlines()

        # 1. Extração do Título
        title = None
        for line in lines:
            line_s = line.strip()
            if line_s.startswith("# "):
                title = line_s[2:].strip()
                break

        if not title:
            if filename:
                title = os.path.splitext(filename)[0].replace('_', ' ').replace('-', ' ').title()
            else:
                title = "Guia de Comportamento Personalizado"

        # 2. Extração de Metadados YAML (Frontmatter ou Bloco de Código ```yaml)
        metadata = {}
        # Tentativa A: Frontmatter no início do arquivo (--- ... ---)
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", md_content, re.DOTALL)
        if frontmatter_match:
            try:
                metadata = yaml.safe_load(frontmatter_match.group(1)) or {}
            except Exception as e:
                logger.warning(f"[BehaviorParser] Erro ao parsear frontmatter YAML: {e}")

        # Tentativa B: Bloco ```yaml ... ``` dentro de alguma seção
        if not metadata:
            yaml_code_blocks = re.findall(r"```ya?ml\s*\n(.*?)\n```", md_content, re.DOTALL | re.IGNORECASE)
            for block in yaml_code_blocks:
                try:
                    parsed = yaml.safe_load(block)
                    if isinstance(parsed, dict) and ('skill_id' in parsed or 'niche' in parsed or 'target_audience' in parsed):
                        metadata = parsed
                        break
                except Exception:
                    continue

        slug = metadata.get('skill_id')
        if not slug:
            slug = re.sub(r'[^a-z0-9_]+', '_', title.lower()).strip('_')[:64]

        niche = metadata.get('niche') or metadata.get('target_audience') or title
        version = str(metadata.get('version', '1.0.0'))
        target_audience = str(metadata.get('target_audience', ''))
        communication_style = str(metadata.get('communication_style', 'Consultivo, direto e objetivo'))
        persona_name = metadata.get('persona_name')
        company_name = metadata.get('company_name')

        # 3. Extração da Diretiva de Sistema (System Prompt)
        system_prompt = cls._extract_system_prompt(md_content, metadata, title)

        # 4. Extração de Seções Estruturadas para RAG (H2 / H3)
        sections = cls._extract_sections(md_content)

        return {
            'name': title,
            'slug': slug,
            'niche': niche,
            'version': version,
            'target_audience': target_audience,
            'communication_style': communication_style,
            'persona_name': persona_name,
            'company_name': company_name,
            'system_prompt': system_prompt,
            'metadata': metadata,
            'sections': sections,
            'content_md': md_content
        }

    @classmethod
    def _extract_system_prompt(cls, md_content: str, metadata: dict, title: str) -> str:
        """Localiza a seção de Diretiva de Sistema / System Prompt no Markdown."""
        prompt_extracted = None

        # Padrão 1: Seção contendo "SYSTEM DIRECTIVE" ou "Bloco de Contexto" ou "System Prompt"
        pattern = re.compile(
            r"##\s*.*?((?:System\s*Prompt|SYSTEM\s*DIRECTIVE|Bloco\s*de\s*Contexto|Diretiva\s*de\s*Sistema).*?)\n(.*?)(?=\n##\s|\Z)",
            re.IGNORECASE | re.DOTALL
        )
        match = pattern.search(md_content)
        if match:
            raw_section = match.group(2).strip()
            # Se houver um bloco de código markdown ou text dentro da seção, extrai seu miolo
            code_block_match = re.search(r"```(?:markdown|text)?\s*\n(.*?)\n```", raw_section, re.DOTALL | re.IGNORECASE)
            if code_block_match:
                prompt_extracted = code_block_match.group(1).strip()
            else:
                prompt_extracted = raw_section

        # Padrão 2: Bloco com tag explícita ### SYSTEM DIRECTIVE:
        if not prompt_extracted:
            directive_match = re.search(r"###\s*SYSTEM\s*DIRECTIVE:?[^\n]*\n(.*?)(?=\n##|\Z)", md_content, re.DOTALL | re.IGNORECASE)
            if directive_match:
                prompt_extracted = directive_match.group(1).strip()

        # Fallback: Se não encontrou seção de prompt dedicada, compila a partir dos metadados e objetivos do guia
        if not prompt_extracted:
            core_offerings = metadata.get('core_offerings', [])
            offerings_text = ""
            if isinstance(core_offerings, list) and core_offerings:
                offerings_text = "\n- Soluções principais: " + "; ".join(str(o) for o in core_offerings)

            prompt_extracted = (
                f"Você é o atendente comercial e consultor de vendas oficial da empresa, atuando no nicho de {metadata.get('niche', title)}.\n"
                f"Público-alvo: {metadata.get('target_audience', 'Clientes e prospects comerciais')}.\n"
                f"Estilo de Comunicação: {metadata.get('communication_style', 'Consultivo, direto e resolutivo')}.{offerings_text}\n\n"
                "Sua missão é atender, qualificar e conduzir os leads pelo WhatsApp com respostas estritamente objetivas e alinhadas às informações da empresa."
            )

        # Garante injeção das diretrizes fundamentais de WhatsApp (brevidade + pausa por falta de contexto)
        if "[PAUSAR_ATENDIMENTO]" not in prompt_extracted:
            prompt_extracted = prompt_extracted.strip() + "\n\n" + MANDATORY_WHATSAPP_BREVITY_RULES.strip()

        return prompt_extracted

    @classmethod
    def _extract_sections(cls, md_content: str) -> List[Dict[str, str]]:
        """Divide o markdown em seções semânticas por cabeçalhos H2 para indexação no RAG."""
        sections = []
        # Divide por '## '
        parts = re.split(r"\n##\s+", md_content)
        for idx, part in enumerate(parts):
            if idx == 0:
                continue # Introdução antes do primeiro H2
            lines = part.strip().splitlines()
            if not lines:
                continue
            section_title = lines[0].strip()
            section_body = "\n".join(lines[1:]).strip()

            # Ignora a seção de metadados brutos e a seção do system prompt que já vai para o prompt principal
            title_lower = section_title.lower()
            if any(k in title_lower for k in ['metadado', 'yaml', 'system directive', 'system prompt', 'bloco de contexto']):
                continue

            if len(section_body) >= 40:
                sections.append({
                    'title': section_title,
                    'content': f"## {section_title}\n\n{section_body}"
                })

        return sections

    @classmethod
    def save_guide_from_content(cls, md_content: str, filename: Optional[str] = None, is_active: bool = False, is_builtin: bool = False) -> BehaviorGuide:
        """Faz o parse, salva ou atualiza um BehaviorGuide no banco de dados."""
        parsed = cls.parse_markdown(md_content, filename=filename)

        slug = parsed['slug']
        guide = BehaviorGuide.query.filter_by(slug=slug).first()

        if not guide:
            guide = BehaviorGuide(
                name=parsed['name'],
                slug=slug,
                niche=parsed['niche'],
                version=parsed['version'],
                target_audience=parsed['target_audience'],
                communication_style=parsed['communication_style'],
                persona_name=parsed['persona_name'],
                company_name=parsed['company_name'],
                system_prompt=parsed['system_prompt'],
                content_md=parsed['content_md'],
                metadata_json=json.dumps(parsed['metadata'], ensure_ascii=False),
                is_active=is_active,
                is_builtin=is_builtin
            )
            db.session.add(guide)
        else:
            guide.name = parsed['name']
            guide.niche = parsed['niche']
            guide.version = parsed['version']
            guide.target_audience = parsed['target_audience']
            guide.communication_style = parsed['communication_style']
            if parsed['persona_name']:
                guide.persona_name = parsed['persona_name']
            if parsed['company_name']:
                guide.company_name = parsed['company_name']
            guide.system_prompt = parsed['system_prompt']
            guide.content_md = parsed['content_md']
            guide.metadata_json = json.dumps(parsed['metadata'], ensure_ascii=False)
            if is_builtin:
                guide.is_builtin = True
            if is_active:
                guide.is_active = True

        db.session.commit()

        if is_active:
            cls.activate_guide(guide.id, sync_rag=True)

        return guide, parsed

    @classmethod
    def activate_guide(cls, guide_id: int, instance_id: Optional[int] = None, sync_rag: bool = True) -> Dict:
        """
        Ativa um guia de comportamento.
        - Se instance_id for especificado, vincula à instância WhatsApp correspondente.
        - Se instance_id for None, ativa como Guia Global Padrão da instalação.
        """
        guide = BehaviorGuide.query.get(guide_id)
        if not guide:
            return {'success': False, 'error': f'Guia ID {guide_id} não encontrado.'}

        # Caso A: Ativação específica para uma instância WAHA
        if instance_id is not None:
            instance = WahaInstance.query.get(instance_id)
            if not instance:
                return {'success': False, 'error': f'Instância WAHA ID {instance_id} não encontrada.'}

            instance.behavior_guide_id = guide.id
            db.session.commit()
            logger.info(f"[BehaviorParser] Guia '{guide.name}' vinculado à instância WAHA '{instance.name}' (ID {instance.id}).")
            
            # Sincroniza seções no RAG
            if sync_rag:
                cls.sync_guide_to_rag(guide)

            return {
                'success': True,
                'message': f"Guia '{guide.name}' ativado com sucesso para a instância '{instance.name}'!",
                'mode': 'instance',
                'guide': guide.to_dict()
            }

        # Caso B: Ativação Global da Instalação
        # Desativa outros guias globais
        BehaviorGuide.query.filter(BehaviorGuide.id != guide.id).update({'is_active': False})
        guide.is_active = True

        # Atualiza configurações operacionais no banco
        Setting.set_val('whatsapp_bot_system_prompt', guide.system_prompt)
        if guide.persona_name:
            Setting.set_val('whatsapp_bot_persona_name', guide.persona_name)
        if guide.company_name:
            Setting.set_val('whatsapp_bot_company_name', guide.company_name)

        db.session.commit()
        logger.info(f"[BehaviorParser] Guia '{guide.name}' ativado globalmente como padrão da instalação.")

        # Sincroniza seções no RAG
        rag_stats = {'docs_indexed': 0}
        if sync_rag:
            rag_stats = cls.sync_guide_to_rag(guide)

        return {
            'success': True,
            'message': f"Guia '{guide.name}' ativado como padrão global da instalação com sucesso!",
            'mode': 'global',
            'guide': guide.to_dict(),
            'rag_stats': rag_stats
        }

    @classmethod
    def sync_guide_to_rag(cls, guide: BehaviorGuide) -> Dict:
        """
        Extrai as seções comportamentais do guia (funil, roteiros, objeções)
        e indexa no ChromaDB como KnowledgeDoc prioritário com boosting de skill.
        """
        parsed = cls.parse_markdown(guide.content_md)
        sections = parsed.get('sections', [])
        if not sections:
            return {'docs_indexed': 0}

        try:
            from app.utils.rag_engine import RAGEngine
        except Exception:
            RAGEngine = None

        prefix_tag = f"[Guia: {guide.slug}]"
        
        # 1. Remove documentos anteriores deste mesmo guia para não duplicar no RAG
        old_docs = KnowledgeDoc.query.filter(KnowledgeDoc.title.like(f"{prefix_tag}%")).all()
        for old in old_docs:
            if RAGEngine:
                try:
                    RAGEngine.delete_document(old.id)
                except Exception:
                    pass
            db.session.delete(old)
        db.session.commit()

        # 2. Cria novos KnowledgeDocs estruturados para cada seção do guia
        indexed_count = 0
        for sec in sections:
            doc_title = f"{prefix_tag} {sec['title']}"
            doc = KnowledgeDoc(
                title=doc_title,
                category='skill_behavior',
                doc_type='text',
                content=sec['content'],
                is_active=True
            )
            db.session.add(doc)
            db.session.commit()

            if RAGEngine:
                try:
                    chunks = RAGEngine.index_document(doc.id, doc.title, doc.content, doc.category)
                    doc.chunks_count = chunks
                    db.session.commit()
                except Exception as e:
                    logger.warning(f"[BehaviorParser] Aviso ao indexar seção '{doc_title}' no RAG: {e}")

            indexed_count += 1

        logger.info(f"[BehaviorParser] {indexed_count} seções do guia '{guide.name}' sincronizadas com a base vetorial RAG.")
        return {'docs_indexed': indexed_count}

    @classmethod
    def get_guide_for_context(cls, instance_id: Optional[int] = None, return_source: bool = False):
        """
        Retorna o Guia de Comportamento aplicável.
        Se return_source=True, retorna tupla (guide, source_str).
        Se return_source=False, retorna diretamente o objeto BehaviorGuide ou None.
        1. Se instance_id tiver um guia dedicado, usa ele.
        2. Caso contrário, retorna o guia ativo global.
        3. Se nenhum ativo, usa qualquer guia existente como fallback.
        """
        guide = None
        source = 'none'

        # 1. Instância específica
        if instance_id:
            try:
                inst = None
                if isinstance(instance_id, int) or (isinstance(instance_id, str) and str(instance_id).isdigit()):
                    inst = WahaInstance.query.get(int(instance_id))
                else:
                    inst = WahaInstance.query.filter_by(session_name=str(instance_id)).first()

                if inst and inst.behavior_guide:
                    guide = inst.behavior_guide
                    source = f"instance_{inst.id}"
            except Exception as e:
                logger.debug(f"[BehaviorParser] Erro ao buscar guia por instância: {e}")

        # 2. Guia ativo global
        if not guide:
            global_guide = BehaviorGuide.query.filter_by(is_active=True).first()
            if global_guide:
                guide = global_guide
                source = 'global'
            else:
                # 3. Qualquer guia existente como fallback
                any_guide = BehaviorGuide.query.first()
                if any_guide:
                    guide = any_guide
                    source = 'fallback'

        if return_source:
            return guide, source
        return guide

    @classmethod
    def seed_initial_guide_if_empty(cls, base_dir: Optional[str] = None):
        """Se o banco não tiver nenhum guia, importa o arquivo guia_de_comportamento_bot_de_vendas_ti_para_pmes.md."""
        try:
            if BehaviorGuide.query.count() > 0:
                return

            if not base_dir:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            default_file = os.path.join(base_dir, "guia_de_comportamento_bot_de_vendas_ti_para_pmes.md")
            if os.path.exists(default_file):
                with open(default_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                guide, _ = cls.save_guide_from_content(
                    content,
                    filename="guia_de_comportamento_bot_de_vendas_ti_para_pmes.md",
                    is_active=True,
                    is_builtin=True
                )
                logger.info(f"[BehaviorParser] Guia padrão inicial carregado com sucesso: '{guide.name}' (ID {guide.id}).")
        except Exception as e:
            logger.warning(f"[BehaviorParser] Aviso ao auto-inicializar guia padrão: {e}")
