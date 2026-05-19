import csv
import io
from fpdf import FPDF
from datetime import datetime

class ReportGenerator:
    @staticmethod
    def generate_csv(logs):
        """Gera um arquivo CSV a partir de uma lista de logs de mensagens."""
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        
        # Header
        writer.writerow(['ID', 'Data/Hora', 'Cliente', 'Telefone', 'Conteúdo', 'Canal', 'Status'])
        
        for log in logs:
            writer.writerow([
                log.id,
                log.timestamp.strftime('%d/%m/%Y %H:%M:%S'),
                log.client.name if log.client else 'N/A',
                log.client.phone if log.client else 'N/A',
                log.content.replace('\n', ' '),
                log.channel,
                "SUCESSO" if log.status == 'sent' else "FALHA"
            ])
        
        return output.getvalue()

    @staticmethod
    def generate_pdf(logs):
        """Gera um PDF refinado a partir de uma lista de logs de mensagens."""
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        
        # Configurar Fonte
        pdf.set_font("helvetica", "B", 16)
        
        # Título
        pdf.set_text_color(15, 23, 42) # Azul escuro
        pdf.cell(0, 10, "Relatório de Disparos WhatsApp - CRM Pro", ln=True, align='C')
        
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 10, f"Emitido em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", ln=True, align='R')
        pdf.ln(5)
        
        # Tabela Header
        pdf.set_font("helvetica", "B", 10)
        pdf.set_fill_color(241, 245, 249) # Cinza claro
        pdf.set_text_color(0, 0, 0)
        
        col_width = [15, 35, 45, 30, 110, 25, 20] # Total 280 para A4 Landscape
        headers = ['ID', 'Data/Hora', 'Cliente', 'Telefone', 'Mensagem', 'Canal', 'Status']
        
        for i in range(len(headers)):
            pdf.cell(col_width[i], 10, headers[i], border=1, align='C', fill=True)
        pdf.ln()
        
        # Dados
        pdf.set_font("helvetica", "", 9)
        fill = False
        for log in logs:
            pdf.set_fill_color(250, 250, 250)
            
            # Sanitizar conteúdo
            content = log.content.replace('\n', ' ')
            if len(content) > 60: content = content[:57] + "..."
            
            client_name = log.client.name if log.client else 'N/A'
            if len(client_name) > 20: client_name = client_name[:17] + "..."

            # Definir cores e texto por status
            status_text = "SUCESSO" if log.status == 'sent' else "FALHA"
            if log.status == 'sent':
                pdf.set_text_color(22, 101, 52) # Verde escuro
            else:
                pdf.set_text_color(185, 28, 28) # Vermelho escuro

            pdf.cell(col_width[0], 8, str(log.id), border=1, align='C', fill=fill)
            pdf.cell(col_width[1], 8, log.timestamp.strftime('%d/%m/%Y %H:%M'), border=1, align='C', fill=fill)
            pdf.cell(col_width[2], 8, client_name, border=1, align='L', fill=fill)
            pdf.cell(col_width[3], 8, log.client.phone if log.client else 'N/A', border=1, align='C', fill=fill)
            pdf.cell(col_width[4], 8, content, border=1, align='L', fill=fill)
            pdf.cell(col_width[5], 8, log.channel.replace('whatsapp_', ''), border=1, align='C', fill=fill)
            
            # Status com cor
            pdf.cell(col_width[6], 8, status_text, border=1, align='C', fill=fill)
            
            # Resetar cor do texto para o padrão
            pdf.set_text_color(0, 0, 0)
            
            pdf.ln()
            fill = not fill # Zebra stripes
            
        return pdf.output()
