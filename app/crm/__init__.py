from flask import Blueprint

bp = Blueprint('crm', __name__)

from app.crm import routes
from app.crm import file_routes
