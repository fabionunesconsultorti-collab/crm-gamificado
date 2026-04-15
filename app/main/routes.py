from flask import render_template, jsonify, abort
from flask_login import login_required, current_user
from app.main import bp
from app.models import Client, SystemLog, User
from app import db
from collections import defaultdict

@bp.route('/')
@bp.route('/index')
@login_required
def index():
    # Real stats from DB
    all_clients = Client.query.all()
    stats = {
        'total_clients': len(all_clients),
        'leads':     sum(1 for c in all_clients if c.status == 'lead'),
        'contatos':  sum(1 for c in all_clients if c.status == 'contato'),
        'propostas': sum(1 for c in all_clients if c.status == 'proposta'),
        'fechados':  sum(1 for c in all_clients if c.status == 'fechado'),
        'perdidos':  sum(1 for c in all_clients if c.status == 'perdido'),
    }
    recent_logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(10).all()
    return render_template('main/index.html', title='Dashboard', stats=stats, recent_logs=recent_logs)


@bp.route('/ranking')
@login_required
def ranking():
    users = User.query.order_by(User.performance_points.desc()).all()

    # Attach closed count to each user object
    for user in users:
        user.closed_count = Client.query.filter_by(
            assigned_to=user.id, status='fechado'
        ).count()

    # My rank
    my_rank = next((i + 1 for i, u in enumerate(users) if u.id == current_user.id), '-')
    my_closed = Client.query.filter_by(
        assigned_to=current_user.id, status='fechado'
    ).count()

    # Level system
    xp = current_user.performance_points
    levels = [
        (0,    'Aprendiz',    200),
        (200,  'Prospector',  500),
        (500,  'Closer',      1000),
        (1000, 'Ninja de Vendas', 2000),
        (2000, 'Lenda',       None),
    ]
    level_name, xp_to_next, progress = 'Aprendiz', 200, 0
    for min_xp, name, next_xp in levels:
        if next_xp is None or xp < next_xp:
            level_name = name
            if next_xp:
                xp_to_next = next_xp - xp
                progress = int((xp - min_xp) / (next_xp - min_xp) * 100)
            else:
                xp_to_next = 0
                progress = 100
            break

    level = {'name': level_name, 'xp_to_next': xp_to_next, 'progress': progress}
    return render_template('main/ranking.html', title='Ranking de Performance',
                           ranking=users, my_rank=my_rank, my_closed=my_closed, level=level)
