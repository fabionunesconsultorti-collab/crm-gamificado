from flask import Blueprint, jsonify
from flask_login import login_required

bp = Blueprint('lead_notifier', __name__)

@bp.route('/status')
@login_required
def status():
    return jsonify({
        'plugin': 'lead_notifier',
        'status': 'active',
        'message': 'Plugin Lead Notifier respondendo normalmente!'
    })
