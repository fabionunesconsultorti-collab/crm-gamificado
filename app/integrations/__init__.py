from flask import Blueprint

bp = Blueprint('integrations', __name__, url_prefix='/integrations')

from app.integrations import routes

# Importa adaptadores para que se registrem no IntegrationManager na inicialização
import app.integrations.bling.adapter
