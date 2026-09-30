"""
Módulo de Processamento Multimodal (Áudio, Imagem, Vídeo e Documentos) para WhatsApp (WAHA).

Responsabilidades:
1. Download resiliente de mídias enviadas pelo contato via WAHA API.
2. Transcrição de Áudios (STT) via Gemini 2.0 Flash / Whisper com alta fidelidade ao português brasileiro.
3. Visão Computacional para Análise de Imagens, Comprovantes Pix/TED e Prints de Dúvidas.
4. Análise de Vídeos e Documentos anexos.
5. Injeção do conteúdo multimodal transcrito/analisado diretamente no pipeline de Debounce e RAG.
"""

import os
import io
import re
import json
import base64
import logging
import requests
from typing import Optional, Tuple, Dict, Any
from app.models import Setting

logger = logging.getLogger(__name__)

class MultimodalProcessor:
    """Processador de mensagens multimodais (áudio, fotos, comprovantes e vídeos)."""

    @classmethod
    def is_multimodal_message(cls, payload: dict) -> bool:
        """Verifica se o payload do WhatsApp/WAHA contém mídia anexa."""
        if not isinstance(payload, dict):
            return False

        has_media = payload.get('hasMedia', False) or payload.get('media') is not None
        msg_type = (
            payload.get('type') or 
            payload.get('_data', {}).get('type') or 
            ''
        ).lower()

        media_types = ['ptt', 'audio', 'voice', 'image', 'video', 'document', 'sticker']
        return bool(has_media or msg_type in media_types)

    @classmethod
    def get_media_type(cls, payload: dict) -> str:
        """Identifica a categoria da mídia: 'audio', 'image', 'video', 'document' ou 'unknown'."""
        msg_type = (
            payload.get('type') or 
            payload.get('_data', {}).get('type') or 
            ''
        ).lower()

        mimetype = (
            payload.get('media', {}).get('mimetype') if isinstance(payload.get('media'), dict) else None
        ) or payload.get('mimetype', '') or ''
        mimetype = mimetype.lower()

        if msg_type in ['ptt', 'audio', 'voice'] or 'audio' in mimetype or 'ogg' in mimetype:
            return 'audio'
        if msg_type in ['image', 'sticker'] or 'image' in mimetype:
            return 'image'
        if msg_type in ['video'] or 'video' in mimetype:
            return 'video'
        if msg_type in ['document'] or 'pdf' in mimetype or 'application' in mimetype:
            return 'document'

        return 'unknown'

    @classmethod
    def download_waha_media(cls, payload: dict, instance_id: Any = None) -> Tuple[Optional[bytes], str, str]:
        """
        Efetua o download dos bytes de mídia a partir do WAHA.
        Retorna (media_bytes, mimetype, filename).
        """
        from app.utils.waha import WahaAPI

        media_info = payload.get('media') if isinstance(payload.get('media'), dict) else {}
        mimetype = media_info.get('mimetype') or payload.get('mimetype') or 'application/octet-stream'
        filename = media_info.get('filename') or payload.get('filename') or 'media_file'

        # Caso 1: O payload já contém dados em base64 (WAHA_MEDIA_DATA=true)
        b64_data = media_info.get('data') or payload.get('data')
        if b64_data and isinstance(b64_data, str) and len(b64_data) > 30:
            try:
                # Remove header de data URI se presente (data:audio/ogg;base64,...)
                if ',' in b64_data:
                    b64_data = b64_data.split(',', 1)[1]
                media_bytes = base64.b64decode(b64_data)
                logger.info(f"[Multimodal] Mídia decodificada de base64 ({len(media_bytes)} bytes, {mimetype})")
                return media_bytes, mimetype, filename
            except Exception as e:
                logger.warning(f"[Multimodal] Erro ao decodificar base64 direto: {e}")

        # Caso 2: URL de download fornecida pelo WAHA
        raw_url = media_info.get('url') or payload.get('mediaUrl') or payload.get('url')
        if raw_url and isinstance(raw_url, str):
            waha_cfg = WahaAPI.get_settings(instance_id)
            headers = WahaAPI.get_headers(instance_id)

            download_url = raw_url
            # Se a URL aponta para localhost ou host interno do docker, ajusta para o endpoint configurado no CRM
            if 'localhost' in download_url or '127.0.0.1' in download_url or 'waha' in download_url:
                base_api = waha_cfg.get('api_url', '').rstrip('/')
                # Extrai o caminho relativo
                path_match = re.search(r'(/(?:api/)?files/.+)$', download_url)
                if path_match and base_api:
                    path = path_match.group(1)
                    if not path.startswith('/api/') and not base_api.endswith('/api'):
                        path = '/api' + path
                    download_url = f"{base_api}{path}"

            try:
                logger.info(f"[Multimodal] Baixando mídia do WAHA: {download_url}")
                resp = requests.get(download_url, headers=headers, timeout=20)
                if resp.status_code == 200 and len(resp.content) > 0:
                    detected_mime = resp.headers.get('Content-Type') or mimetype
                    logger.info(f"[Multimodal] Download de mídia bem-sucedido ({len(resp.content)} bytes, {detected_mime})")
                    return resp.content, detected_mime, filename
                else:
                    logger.warning(f"[Multimodal] Falha no download ({resp.status_code}): {resp.text[:100]}")
            except Exception as e:
                logger.error(f"[Multimodal] Exceção ao baixar mídia da URL {download_url}: {e}")

        # Caso 3: Consulta endpoint de download por ID da mensagem no WAHA
        msg_id = payload.get('id') or payload.get('message_id')
        if isinstance(msg_id, dict):
            msg_id = msg_id.get('_serialized') or msg_id.get('id')

        if msg_id:
            waha_cfg = WahaAPI.get_settings(instance_id)
            session = waha_cfg.get('session_name', 'default')
            base_api = waha_cfg.get('api_url', '').rstrip('/')
            headers = WahaAPI.get_headers(instance_id)

            candidate_endpoints = [
                f"{base_api}/api/{session}/files/{msg_id}",
                f"{base_api}/api/files/{session}/{msg_id}",
                f"{base_api}/api/{session}/chats/{payload.get('from', '')}/messages/{msg_id}/download"
            ]

            for ep in candidate_endpoints:
                try:
                    resp = requests.get(ep, headers=headers, timeout=15)
                    if resp.status_code == 200 and len(resp.content) > 0:
                        detected_mime = resp.headers.get('Content-Type') or mimetype
                        logger.info(f"[Multimodal] Download via endpoint {ep} concluído ({len(resp.content)} bytes)")
                        return resp.content, detected_mime, filename
                except Exception:
                    continue

        return None, mimetype, filename

    @classmethod
    def transcribe_audio(cls, audio_bytes: bytes, mimetype: str = "audio/ogg") -> Tuple[Optional[str], Optional[str]]:
        """
        Transcreve áudio curto ou longo (PTT/Voice/Audio) utilizando:
        1. Google Gemini 2.0 Flash (STT nativo ultra-rápido para português);
        2. Whisper local se instalado no ambiente.
        Retorna (transcription_text, error_message).
        """
        if not audio_bytes or len(audio_bytes) < 100:
            return None, "Áudio vazio ou corrompido."

        api_key = Setting.get_val('ai_api_key')
        
        # Tentativa 1: Google Gemini 2.0 Flash com áudio inline
        if api_key:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=api_key)
                
                # Normaliza mimetype para Gemini
                clean_mime = mimetype.split(';')[0].strip()
                if not clean_mime or clean_mime == 'application/octet-stream':
                    clean_mime = 'audio/ogg'

                prompt_stt = (
                    "Transcreva com máxima precisão todo o conteúdo falado deste áudio para texto em português do Brasil. "
                    "Retorne estritamente o texto transcrito, sem comentários, sem aspas e sem explicações."
                )

                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=clean_mime),
                        prompt_stt
                    ]
                )

                if response and response.text:
                    cleaned = response.text.strip()
                    logger.info(f"[Multimodal STT] Áudio transcrito com Gemini ({len(audio_bytes)} bytes): '{cleaned[:60]}...'")
                    return cleaned, None
            except Exception as e:
                logger.warning(f"[Multimodal STT] Falha ao transcrever via Gemini: {e}")

        # Tentativa 2: Whisper local se biblioteca disponível
        try:
            import whisper
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            try:
                model = whisper.load_model("base")
                result = model.transcribe(tmp_path, language="pt")
                text = (result.get("text") or "").strip()
                if text:
                    logger.info(f"[Multimodal STT] Áudio transcrito via Whisper local: '{text[:60]}...'")
                    return text, None
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[Multimodal STT] Falha no Whisper local: {e}")

        return None, "Serviço de transcrição STT não disponível ou sem chave de API configurada."

    @classmethod
    def analyze_image(cls, image_bytes: bytes, mimetype: str = "image/jpeg", caption: str = "") -> Tuple[Optional[str], Optional[str]]:
        """
        Analisa imagem enviada pelo cliente (comprovante Pix/TED, foto de produto, print de dúvida ou erro).
        Retorna (analysis_summary, error_message).
        """
        if not image_bytes or len(image_bytes) < 100:
            return None, "Imagem vazia ou corrompida."

        api_key = Setting.get_val('ai_api_key')
        if not api_key:
            return None, "API Key não configurada para análise visual de imagens."

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            clean_mime = mimetype.split(';')[0].strip()
            if not clean_mime or clean_mime == 'application/octet-stream':
                clean_mime = 'image/jpeg'

            prompt_vision = (
                "Você é um analista de atendimento ao cliente via WhatsApp. Analise detalhadamente a imagem enviada pelo contato:\n"
                "1. Se for um COMPROVANTE (Pix, TED, Boleto, Depósito): extraia o valor exato (R$), nome do favorecido/recebedor, "
                "banco de origem/destino, data/hora e se a transação consta como confirmada/efetivada.\n"
                "2. Se for um PRINT DE ERRO, DÚVIDA ou TELA DE SISTEMA: descreva o problema exato, mensagem de erro na tela e contexto.\n"
                "3. Se for FOTO DE PRODUTO ou DOCUMENTO: descreva o item e qualquer dado relevante visível.\n"
                f"Legenda enviada pelo cliente: '{caption}'\n"
                "Forneça um resumo objetivo e conciso (máximo 3 parágrafos) em português pronto para que o assistente de IA compreenda o contexto."
            )

            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=clean_mime),
                    prompt_vision
                ]
            )

            if response and response.text:
                cleaned = response.text.strip()
                logger.info(f"[Multimodal Vision] Imagem analisada ({len(image_bytes)} bytes): '{cleaned[:80]}...'")
                return cleaned, None

            return None, "Resposta visual vazia."
        except Exception as e:
            logger.error(f"[Multimodal Vision] Erro na análise de imagem: {e}")
            return None, str(e)

    @classmethod
    def process_inbound_multimodal(cls, payload: dict, instance_id: Any = None) -> Dict[str, Any]:
        """
        Pipeline unificado para recepção de qualquer mensagem multimodal do WAHA:
        - Detecta o tipo (áudio, foto, comprovante, vídeo, documento);
        - Baixa os bytes;
        - Transcreve áudio ou analisa imagem;
        - Devolve texto consolidado pronto para o buffer de debounce e RAG.
        """
        original_body = (payload.get('body') or '').strip()
        is_multimodal = cls.is_multimodal_message(payload)
        
        if not is_multimodal:
            return {
                'has_media': False,
                'media_type': 'text',
                'consolidated_text': original_body,
                'transcription': None,
                'visual_summary': None
            }

        media_type = cls.get_media_type(payload)
        logger.info(f"[Multimodal] Mensagem classificada como '{media_type}'. Iniciando extração de mídia...")

        media_bytes, mimetype, filename = cls.download_waha_media(payload, instance_id)

        if not media_bytes:
            logger.warning(f"[Multimodal] Não foi possível obter os bytes da mídia ({media_type}). Mantendo corpo original.")
            fallback_text = original_body or f"[{media_type.capitalize()} recebido, mas não foi possível processar o anexo]"
            return {
                'has_media': True,
                'media_type': media_type,
                'consolidated_text': fallback_text,
                'transcription': None,
                'visual_summary': None
            }

        transcription = None
        visual_summary = None

        if media_type == 'audio':
            stt_text, err = cls.transcribe_audio(audio_bytes=media_bytes, mimetype=mimetype)
            if stt_text:
                transcription = stt_text
                consolidated = f"[Áudio transcrito do cliente]: \"{stt_text}\""
                if original_body:
                    consolidated = f"{original_body}\n{consolidated}"
            else:
                consolidated = original_body or "[Áudio recebido, mas não foi possível transcrever no momento]"

        elif media_type == 'image':
            vision_text, err = cls.analyze_image(image_bytes=media_bytes, mimetype=mimetype, caption=original_body)
            if vision_text:
                visual_summary = vision_text
                caption_part = f"Legenda: \"{original_body}\"\n" if original_body else ""
                consolidated = f"{caption_part}[Análise visual da imagem/comprovante enviado pelo cliente]:\n{vision_text}"
            else:
                consolidated = original_body or "[Imagem/comprovante recebido pelo cliente]"

        elif media_type == 'video':
            consolidated = original_body or "[Vídeo recebido pelo cliente]"
            if original_body:
                consolidated = f"[Vídeo com legenda]: {original_body}"

        elif media_type == 'document':
            consolidated = original_body or f"[Documento anexo recebido: {filename}]"

        else:
            consolidated = original_body

        return {
            'has_media': True,
            'media_type': media_type,
            'consolidated_text': consolidated.strip(),
            'transcription': transcription,
            'visual_summary': visual_summary,
            'filename': filename,
            'mimetype': mimetype
        }
