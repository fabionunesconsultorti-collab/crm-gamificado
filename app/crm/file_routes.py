import os
import json
import pandas as pd
from flask import request, jsonify
from flask_login import login_required, current_user
from app import db
from app.crm import bp
from app.models import FileMappingTemplate

def get_file_dataframe(file):
    from app.utils.encoding import sanitize_encoding

    if file.filename.endswith('.csv'):
        df = None
        for enc in ('utf-8-sig', 'utf-8', 'latin1', 'cp1252'):
            for sep in [None, ';', ',']:
                try:
                    file.seek(0)
                    if sep:
                        df = pd.read_csv(file, dtype=str, encoding=enc, sep=sep)
                    else:
                        df = pd.read_csv(file, dtype=str, encoding=enc, sep=None, engine='python')
                    if df is not None and (len(df.columns) > 1 or len(df) > 0):
                        break
                except Exception:
                    continue
            if df is not None and len(df.columns) > 1:
                break

        if df is None:
            file.seek(0)
            df = pd.read_csv(file, dtype=str, encoding='latin1')

        # Sanitiza colunas de texto para evitar mojibake
        for col in df.select_dtypes(include='object').columns:
            df[col] = df[col].apply(sanitize_encoding)
        # Sanitiza também os nomes das colunas
        df.columns = [sanitize_encoding(str(c)) for c in df.columns]
        return df
    elif file.filename.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(file, dtype=str)
        for col in df.select_dtypes(include='object').columns:
            df[col] = df[col].apply(sanitize_encoding)
        df.columns = [sanitize_encoding(str(c)) for c in df.columns]
        return df
    else:
        raise ValueError("Formato de arquivo não suportado. Use .csv ou .xlsx")

@bp.route('/api/file/preview', methods=['POST'])
@login_required
def file_preview():
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'Nenhum arquivo enviado'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'ok': False, 'error': 'Nome de arquivo vazio'}), 400
        
    try:
        df = get_file_dataframe(file)
        # Drop empty columns
        df = df.dropna(axis=1, how='all')
        columns = df.columns.tolist()
        
        # Optionally, get a few sample rows
        sample_data = df.head(3).fillna("").to_dict('records')
        
        return jsonify({
            'ok': True,
            'columns': columns,
            'sample': sample_data
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@bp.route('/api/mapping/templates', methods=['GET', 'POST'])
@login_required
def mapping_templates():
    if request.method == 'GET':
        module = request.args.get('module', 'clients')
        templates = FileMappingTemplate.query.filter_by(target_module=module).order_by(FileMappingTemplate.name).all()
        return jsonify({
            'ok': True,
            'templates': [{
                'id': t.id,
                'name': t.name,
                'mapping': json.loads(t.mapping_data)
            } for t in templates]
        })
        
    elif request.method == 'POST':
        data = request.json
        name = data.get('name')
        module = data.get('module', 'clients')
        mapping = data.get('mapping')
        
        if not name or not mapping:
            return jsonify({'ok': False, 'error': 'Nome e mapeamento são obrigatórios'}), 400
            
        # Check if already exists with same name for this module
        t = FileMappingTemplate.query.filter_by(name=name, target_module=module).first()
        if t:
            t.mapping_data = json.dumps(mapping)
        else:
            t = FileMappingTemplate(
                name=name,
                target_module=module,
                mapping_data=json.dumps(mapping),
                user_id=current_user.id
            )
            db.session.add(t)
            
        db.session.commit()
        return jsonify({'ok': True, 'id': t.id})

@bp.route('/api/file/process', methods=['POST'])
@login_required
def process_file():
    if 'file' not in request.files or 'mapping' not in request.form:
        return jsonify({'ok': False, 'error': 'Arquivo e mapeamento são obrigatórios'}), 400
        
    file = request.files['file']
    try:
        mapping = json.loads(request.form['mapping'])
    except:
        return jsonify({'ok': False, 'error': 'Mapeamento inválido'}), 400
        
    try:
        df = get_file_dataframe(file)
        
        results = []
        for index, row in df.iterrows():
            processed_row = {}
            for sys_field, file_col in mapping.items():
                if file_col and file_col in df.columns:
                    val = row[file_col]
                    if pd.isna(val):
                        val = ""
                    processed_row[sys_field] = str(val).strip()
            
            # Basic validation
            if processed_row.get('name') or processed_row.get('phone'):
                results.append(processed_row)
                
        return jsonify({
            'ok': True,
            'count': len(results),
            'data': results
        })
        
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
