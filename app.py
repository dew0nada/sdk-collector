from flask import Flask, request, jsonify, g
from models import Event, db
import os
import secrets
from datetime import datetime
from dotenv import load_dotenv
from prometheus_client import Counter, Histogram, generate_latest


load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
db.init_app(app)

# Prometheus metrics
events_counter = Counter('events_total', 'Total events received', ['event_type', 'client'])
request_duration = Histogram('request_duration_seconds', 'Request duration', ['endpoint'])
error_counter = Counter('errors_total', 'Total errors', ['type'])

def generate_api_key():
    return "sk_" + secrets.token_urlsafe(32)

@app.route('/')
def home():
    return "Collector is running"

@app.route('/health')
def health():
    return {'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()}

@app.route('/metrics')
def metrics():
    return generate_latest()

@app.route('/api/register', methods=['POST'])
def register_client():
    from models import Client
    
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': 'Client name required'}), 400
    
    api_key = generate_api_key()
    client = Client(api_key=api_key, name=data['name'])
    
    db.session.add(client)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'api_key': api_key,
        'message': 'Save this API key'
    }), 201

@app.before_request
def authenticate():
    if request.path in ['/health', '/api/register', '/', '/metrics']:
        return
    
    data = request.get_json(silent=True) or {}
    api_key = data.get('api_key')
    
    if not api_key:
        api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        error_counter.labels(type='auth_missing').inc()
        return jsonify({'error': 'Missing api_key'}), 401
    
    from models import Client
    client = Client.query.filter_by(api_key=api_key, is_active=True).first()
    
    if not client:
        error_counter.labels(type='auth_invalid').inc()
        return jsonify({'error': 'Invalid API key'}), 401
    
    g.client = client

@app.route('/api/events', methods=['POST'])
def track_event():
    from models import Event
    import time
    
    start_time = time.time()
    
    client = g.client
    data = request.get_json()
    
    required = ['event_type', 'sent_at', 'identifiers', 'page_info']
    for field in required:
        if field not in data:
            error_counter.labels(type='validation').inc()
            return jsonify({'error': f'Missing {field}'}), 400
    
    try:
        event = Event(
            client_id=client.id,
            visitor_id=data['identifiers']['visitor_id'],
            session_id=data['identifiers']['session_id'],
            page_url=data['page_info']['url'],
            event_type=data['event_type'],
            sdk_version=data.get('sdk_version'),
            sent_at=datetime.fromisoformat(data['sent_at'].replace('Z', '+00:00')),
            raw_data=data
        )
        
        db.session.add(event)
        db.session.commit()
        
        # Update Prometheus metrics
        events_counter.labels(
            event_type=data['event_type'],
            client=client.name
        ).inc()
        
        request_duration.labels(endpoint='/api/events').observe(time.time() - start_time)
        
        return jsonify({
            'success': True,
            'event_id': event.id,
            'received_at': datetime.utcnow().isoformat()
        }), 201
        
    except Exception as e:
        error_counter.labels(type='processing').inc()
        db.session.rollback()
        return jsonify({'error': 'Failed to process event'}), 500

@app.route('/api/analytics/summary')
def analytics_summary():
    from sqlalchemy import func
    
    client_id = g.client.id
    
    # Get total events
    total = Event.query.filter_by(client_id=client_id).count()
    
    # Group by event type
    by_type = db.session.query(
        Event.event_type,
        func.count(Event.id)
    ).filter_by(client_id=client_id).group_by(Event.event_type).all()
    
    # Unique visitors
    unique_visitors = db.session.query(
        func.count(func.distinct(Event.visitor_id))
    ).filter_by(client_id=client_id).scalar() or 0
    
    return jsonify({
        'client': g.client.name,
        'total_events': total,
        'by_type': dict(by_type),
        'unique_visitors': unique_visitors,
        'first_event': Event.query.filter_by(client_id=client_id)
                      .order_by(Event.sent_at.asc()).first().sent_at.isoformat() 
                      if total > 0 else None
    })

@app.route('/api/analytics/recent')
def recent_events():
    events = Event.query.filter_by(
        client_id=g.client.id
    ).order_by(Event.sent_at.desc()).limit(50).all()
    
    return jsonify([{
        'id': e.id,
        'type': e.event_type,
        'visitor': e.visitor_id,
        'page': e.page_url,
        'time': e.sent_at.isoformat(),
        'details': {
            'error': e.raw_data.get('error_info', {}).get('message') if e.event_type == 'error' else None,
            'click': e.raw_data.get('click_info', {}).get('element') if e.event_type == 'click' else None,
            'load_time': e.raw_data.get('performance', {}).get('load_time') if e.event_type == 'page_view' else None
        }
    } for e in events])

@app.route('/api/analytics/errors')
def error_analytics():
    errors = Event.query.filter_by(
        client_id=g.client.id,
        event_type='error'
    ).order_by(Event.sent_at.desc()).limit(100).all()
    
    # Group by error message
    error_counts = {}
    for e in errors:
        msg = e.raw_data.get('error_info', {}).get('message', 'Unknown')
        error_counts[msg] = error_counts.get(msg, 0) + 1
    
    return jsonify({
        'total_errors': len(errors),
        'recent_errors': [{
            'message': e.raw_data.get('error_info', {}).get('message'),
            'file': e.raw_data.get('error_info', {}).get('file'),
            'line': e.raw_data.get('error_info', {}).get('line'),
            'page': e.page_url,
            'time': e.sent_at.isoformat()
        } for e in errors[:10]],
        'error_frequency': error_counts
    })

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)