from flask import Blueprint

bp = Blueprint('crm', __name__)

from app.crm import routes
