import re

def sanitize_encoding(text: str) -> str:
    """
    Higieniza e repara strings com problemas comuns de codificação (mojibake),
    especialmente quando texto UTF-8 é incorretamente decodificado como Latin-1 (ISO-8859-1) ou Windows-1252.
    Exemplos:
      - 'CalÃ§ados' -> 'Calçados'
      - 'AcessÃ³rios' -> 'Acessórios'
      - 'JoÃ£o' -> 'João'
      - 'PÃ©' -> 'Pé'
      - 'SumarÃ©' -> 'Sumaré'
    """
    if not isinstance(text, str) or not text:
        return text

    # Se não houver nenhum caractere típico de corrupção UTF-8/Latin1, retorna direto para máxima performance
    mojibake_chars = ('Ã', 'Â', 'â€', 'Ã©', 'Ã¡', 'Ã³', 'Ã£', 'Ã§', 'Ãº', 'Ã\x89', 'Ã\x81', 'Ã\x8d', 'Ã\x93', 'Ã\x9a', 'Ã\x95')
    if not any(c in text for c in mojibake_chars):
        return text

    current = text
    # Tenta até 2 iterações caso haja dupla decodificação incorreta
    for _ in range(2):
        has_mojibake = any(c in current for c in mojibake_chars)
        if not has_mojibake:
            break

        try:
            fixed = current.encode('latin1').decode('utf-8')
            current = fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            try:
                fixed = current.encode('cp1252').decode('utf-8')
                current = fixed
            except (UnicodeEncodeError, UnicodeDecodeError):
                break

    return current
