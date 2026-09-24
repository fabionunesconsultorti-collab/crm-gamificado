import unittest
import io
import pandas as pd
from app.utils.encoding import sanitize_encoding
from app.utils.maps_scraper import MapsScraperClient
from app.crm.file_routes import get_file_dataframe
from werkzeug.datastructures import FileStorage

class TestEncodingSanitization(unittest.TestCase):
    def test_sanitize_encoding_direct_cases(self):
        """Testa o reparo de padrões clássicos de mojibake (UTF-8 decodificado como Latin1)."""
        cases = {
            'Bem Me Quer Modas e AcessÃ³rios': 'Bem Me Quer Modas e Acessórios',
            'Reds CalÃ§ados': 'Reds Calçados',
            'PÃ© Direito': 'Pé Direito',
            'BaniwÃ¡ Moda Jovem': 'Baniwá Moda Jovem',
            'Av. JoÃ£o Pessoa': 'Av. João Pessoa',
            'Av. AmpÃ©lio Gazzetta': 'Av. Ampélio Gazzetta',
            'Jardim Ã‰den': 'Jardim Éden',
            'Loja do BrÃ¡s': 'Loja do Brás',
            'SalÃ£o de Beleza': 'Salão de Beleza',
            'Padaria & CafÃ© LÃ¡ Da Esquina': 'Padaria & Café Lá Da Esquina',
            'Texto sem caracteres especiais': 'Texto sem caracteres especiais',
            '': '',
            None: None
        }

        for corrupted, expected in cases.items():
            self.assertEqual(sanitize_encoding(corrupted), expected)

    def test_maps_scraper_sanitizes_mojibake_items(self):
        """Valida que o MapsScraperClient limpa automaticamente qualquer mojibake recebido."""
        client_api = MapsScraperClient()
        raw_row = {
            "title": "Padaria & CafÃ© LÃ¡ Da Esquina",
            "phone": "(19) 3883-2542",
            "category": "Padaria e ConfeitariÃ¡",
            "address": "Av. SÃ£o GonÃ§alo, 123",
            "website": "https://www.instagram.com/padariacafe/"
        }
        normalized = client_api._normalize_item(raw_row)
        self.assertEqual(normalized["name"], "Padaria & Café Lá Da Esquina")
        self.assertEqual(normalized["category"], "Padaria e Confeitariá")
        self.assertEqual(normalized["address"], "Av. São Gonçalo, 123")

    def test_get_file_dataframe_sanitizes_csv(self):
        """Valida que a importação de CSV detecta e higieniza colunas e células com mojibake."""
        csv_content = "Nome;EndereÃ§o;Segmento;Telefone\nPadaria do JoÃ£o;Rua das MaÃ§Ã£s, 10;PanificaÃ§Ã£o;1999999999\n"
        csv_bytes = io.BytesIO(csv_content.encode('utf-8'))
        file_storage = FileStorage(stream=csv_bytes, filename="teste_contatos.csv", content_type="text/csv")
        
        df = get_file_dataframe(file_storage)
        self.assertIn("Endereço", df.columns)
        self.assertEqual(df.iloc[0]["Nome"], "Padaria do João")
        self.assertEqual(df.iloc[0]["Endereço"], "Rua das Maçãs, 10")
        self.assertEqual(df.iloc[0]["Segmento"], "Panificação")

if __name__ == '__main__':
    unittest.main()
