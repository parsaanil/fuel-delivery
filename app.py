from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_socketio import SocketIO, emit, join_room
import json, os, uuid, hashlib, csv
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2

app = Flask(__name__)
app.secret_key = 'fuelaid_secret_key_2024'
socketio = SocketIO(app, cors_allowed_origins="*")

DB_FILE = 'db.json'
CUSTOMERS_CSV = 'customers.csv'
AGENTS_CSV    = 'agents.csv'
MECHANICS_CSV = 'mechanics.csv'

CUSTOMER_FIELDS  = ['id','name','email','phone','vehicle','lat','lon','joined']
AGENT_FIELDS     = ['id','name','email','phone','lat','lon','verified','joined','total_deliveries']
MECHANIC_FIELDS  = ['id','name','email','phone','lat','lon','verified','joined','total_jobs']

FUEL_PRICES = {'petrol': 102.63, 'diesel': 88.74, 'cng': 76.00}
DELIVERY_RATE_PER_KM = 8.0
BASE_DELIVERY_CHARGE = 30.0
MECHANIC_RATE        = 250.0
SPEED_KMH            = 35.0

def _ensure_csv(path, fields):
    if not os.path.exists(path):
        with open(path, 'w', newline='') as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()

def _upsert_csv(path, fields, row_dict):
    _ensure_csv(path, fields)
    rows = []
    found = False
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            if row['id'] == row_dict['id']:
                rows.append({k: row_dict.get(k, row.get(k,'')) for k in fields})
                found = True
            else:
                rows.append(row)
    if not found:
        rows.append({k: row_dict.get(k,'') for k in fields})
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

def sync_user_to_csv(user):
    db = load_db()
    role = user.get('role')
    if role == 'customer':
        _upsert_csv(CUSTOMERS_CSV, CUSTOMER_FIELDS, {k: user.get(k,'') for k in CUSTOMER_FIELDS})
    elif role == 'fuel_boy':
        completed = len([r for r in db['requests'] if r.get('fuel_boy_id') == user['id'] and r['status']=='completed'])
        d = {k: user.get(k,'') for k in AGENT_FIELDS}; d['total_deliveries'] = completed
        _upsert_csv(AGENTS_CSV, AGENT_FIELDS, d)
    elif role == 'mechanic':
        completed = len([r for r in db['requests'] if r.get('mechanic_id') == user['id'] and r['status']=='completed'])
        d = {k: user.get(k,'') for k in MECHANIC_FIELDS}; d['total_jobs'] = completed
        _upsert_csv(MECHANICS_CSV, MECHANIC_FIELDS, d)

def load_db():
    if not os.path.exists(DB_FILE):
        return {'users': [], 'requests': [], 'feedback': []}
    with open(DB_FILE) as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=2)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2-lat1); dlon = radians(lon2-lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def compute_quote(req_type, fuel_type, liters, distance_km):
    if req_type == 'fuel':
        price = FUEL_PRICES.get(fuel_type, FUEL_PRICES['petrol'])
        fuel_cost = round(price * liters, 2)
        delivery_charge = round(BASE_DELIVERY_CHARGE + distance_km * DELIVERY_RATE_PER_KM, 2)
        total = round(fuel_cost + delivery_charge, 2)
        breakdown = {'fuel_cost': fuel_cost, 'delivery_charge': delivery_charge, 'total': total}
    else:
        svc = round(MECHANIC_RATE + distance_km * DELIVERY_RATE_PER_KM, 2)
        breakdown = {'service_cost': MECHANIC_RATE, 'travel_charge': round(distance_km*DELIVERY_RATE_PER_KM,2), 'total': svc}
    breakdown['eta_minutes'] = round((distance_km / SPEED_KMH) * 60 + 5)
    return breakdown

def seed():
    db = load_db()
    if not any(u['role']=='admin' for u in db['users']):
        db['users'].append({'id':str(uuid.uuid4()),'name':'Admin','email':'admin@fuelaid.com',
                            'password':hash_pw('admin123'),'role':'admin','verified':True,'lat':17.385,'lon':78.4867})
        save_db(db)
    _ensure_csv(CUSTOMERS_CSV, CUSTOMER_FIELDS)
    _ensure_csv(AGENTS_CSV, AGENT_FIELDS)
    _ensure_csv(MECHANICS_CSV, MECHANIC_FIELDS)
seed()

@app.route('/')
def index():
    return render_template('index.html', fuel_prices=FUEL_PRICES)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        db = load_db()
        role = request.form.get('role','customer')
        email = request.form.get('email')
        if any(u['email']==email for u in db['users']):
            flash('Email already registered.','error'); return redirect(url_for('register'))
        user = {'id':str(uuid.uuid4()),'name':request.form.get('name'),'email':email,
                'password':hash_pw(request.form.get('password')),'role':role,
                'verified': role=='customer','lat':float(request.form.get('lat',17.385)),
                'lon':float(request.form.get('lon',78.4867)),'phone':request.form.get('phone',''),
                'vehicle':request.form.get('vehicle',''),'joined':datetime.now().isoformat()}
        db['users'].append(user); save_db(db)
        sync_user_to_csv(user)
        flash('Registered! Please login.','success'); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        db = load_db()
        email, pw = request.form.get('email'), request.form.get('password')
        user = next((u for u in db['users'] if u['email']==email and u['password']==hash_pw(pw)), None)
        if not user: flash('Invalid credentials.','error'); return redirect(url_for('login'))
        if not user['verified']: flash('Account pending admin verification.','error'); return redirect(url_for('login'))
        session['user_id'] = user['id']; session['role'] = user['role']; session['name'] = user['name']
        return redirect(url_for(f"dashboard_{user['role'].replace('-','_')}"))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

def get_current_user():
    db = load_db()
    return next((u for u in db['users'] if u['id']==session.get('user_id')), None)

@app.route('/dashboard/customer')
def dashboard_customer():
    if session.get('role') != 'customer': return redirect(url_for('login'))
    db = load_db()
    my_reqs = [r for r in db['requests'] if r['customer_id']==session['user_id']]
    rated_ids = {fb['request_id'] for fb in db['feedback'] if fb['customer_id']==session['user_id']}
    return render_template('dashboard_customer.html', requests=my_reqs, user=get_current_user(),
                           rated_ids=rated_ids, fuel_prices=FUEL_PRICES)

@app.route('/dashboard/mechanic')
def dashboard_mechanic():
    if session.get('role') != 'mechanic': return redirect(url_for('login'))
    db = load_db(); user = get_current_user(); nearby = []
    for r in db['requests']:
        if r['status']=='pending' and r.get('type') in ['roadside','maintenance']:
            dist = haversine(user['lat'],user['lon'],r['lat'],r['lon'])
            if dist <= 100:
                r2 = dict(r); r2['distance'] = round(dist,1)
                r2['eta_minutes'] = round((dist/SPEED_KMH)*60+5)
                nearby.append(r2)
    my_jobs = [r for r in db['requests'] if r.get('mechanic_id')==session['user_id']]
    return render_template('dashboard_mechanic.html', nearby=nearby, my_jobs=my_jobs, user=user)

@app.route('/dashboard/fuel_boy')
def dashboard_fuel_boy():
    if session.get('role') != 'fuel_boy': return redirect(url_for('login'))
    db = load_db(); user = get_current_user()
    my_deliveries = [r for r in db['requests'] if r.get('fuel_boy_id')==session['user_id']]
    for r in my_deliveries:
        if r['status'] in ('ongoing','awaiting_confirmation'):
            dist = haversine(user['lat'],user['lon'],r['lat'],r['lon'])
            r['distance'] = round(dist,1); r['eta_minutes'] = round((dist/SPEED_KMH)*60+5)
    return render_template('dashboard_fuelboy.html', deliveries=my_deliveries, user=user, fuel_prices=FUEL_PRICES)

@app.route('/dashboard/admin')
def dashboard_admin():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    db = load_db()
    pending_users = [u for u in db['users'] if not u['verified'] and u['role']!='customer']
    return render_template('dashboard_admin.html', db=db, pending_users=pending_users,
                           user=get_current_user(), fuel_prices=FUEL_PRICES)

@app.route('/api/fuel_prices')
def api_fuel_prices():
    return jsonify(FUEL_PRICES)

@app.route('/api/quote', methods=['POST'])
def api_quote():
    data = request.json
    db = load_db()
    admin = next((u for u in db['users'] if u['role']=='admin'), None)
    cust_lat = float(data.get('lat',17.385)); cust_lon = float(data.get('lon',78.4867))
    dist = haversine(cust_lat, cust_lon, admin['lat'], admin['lon']) if admin else 5.0
    quote = compute_quote(data.get('type','fuel'), data.get('fuel_type','petrol'),
                          float(data.get('liters',0)), dist)
    quote['distance_km'] = round(dist,2)
    return jsonify(quote)

@app.route('/api/request', methods=['POST'])
def create_request():
    if 'user_id' not in session: return jsonify({'error':'Unauthorized'}),401
    db = load_db(); data = request.json
    fuel_type = data.get('fuel_type',''); liters = float(data.get('liters',0))
    cust_lat = float(data.get('lat',17.385)); cust_lon = float(data.get('lon',78.4867))
    req_type = data.get('type','fuel')
    admin = next((u for u in db['users'] if u['role']=='admin'), None)
    dist = haversine(cust_lat, cust_lon, admin['lat'], admin['lon']) if admin else 5.0
    quote = compute_quote(req_type, fuel_type, liters, dist)
    req = {'id':str(uuid.uuid4()),'customer_id':session['user_id'],'customer_name':session['name'],
           'type':req_type,'description':data.get('description',''),'lat':cust_lat,'lon':cust_lon,
           'address':data.get('address','Unknown'),'fuel_type':fuel_type,'liters':liters,
           'status':'pending','created_at':datetime.now().isoformat(),'mechanic_id':None,
           'fuel_boy_id':None,'notes':'','quoted_total':quote.get('total',0),
           'quoted_eta_minutes':quote.get('eta_minutes',30),'quote_breakdown':quote,
           'customer_confirmed':False,'confirmation_time':None,'feedback_rating':None,
           'feedback_comment':None,'feedback_at':None}
    db['requests'].append(req); save_db(db)
    socketio.emit('new_request', req, room='providers')
    return jsonify({'success':True,'request_id':req['id'],'quote':quote})

@app.route('/api/accept/<req_id>', methods=['POST'])
def accept_request(req_id):
    db = load_db(); user = get_current_user()
    for r in db['requests']:
        if r['id']==req_id and r['status']=='pending':
            dist = haversine(user['lat'],user['lon'],r['lat'],r['lon'])
            eta = round((dist/SPEED_KMH)*60+5)
            if user['role']=='mechanic':
                r['mechanic_id']=user['id']; r['mechanic_name']=user['name']
            elif user['role']=='fuel_boy':
                r['fuel_boy_id']=user['id']; r['fuel_boy_name']=user['name']
            r['provider_distance_km']=round(dist,1); r['quoted_eta_minutes']=eta
            r['status']='ongoing'; r['accepted_at']=datetime.now().isoformat()
            save_db(db); socketio.emit('request_updated', r, room=r['customer_id'])
            return jsonify({'success':True,'eta_minutes':eta})
    return jsonify({'error':'Not found'}),404

@app.route('/api/complete/<req_id>', methods=['POST'])
def complete_request(req_id):
    db = load_db(); data = request.json or {}
    for r in db['requests']:
        if r['id']==req_id:
            r['status']='awaiting_confirmation'; r['notes']=data.get('notes','')
            r['completed_at']=datetime.now().isoformat()
            save_db(db); socketio.emit('request_updated', r, room=r['customer_id'])
            provider_id = r.get('fuel_boy_id') or r.get('mechanic_id')
            if provider_id:
                prov = next((u for u in db['users'] if u['id']==provider_id), None)
                if prov: sync_user_to_csv(prov)
            return jsonify({'success':True})
    return jsonify({'error':'Not found'}),404

@app.route('/api/confirm/<req_id>', methods=['POST'])
def confirm_delivery(req_id):
    if 'user_id' not in session: return jsonify({'error':'Unauthorized'}),401
    db = load_db()
    for r in db['requests']:
        if r['id']==req_id and r['customer_id']==session['user_id']:
            r['status']='completed'; r['customer_confirmed']=True
            r['confirmation_time']=datetime.now().isoformat()
            save_db(db)
            prov_id = r.get('fuel_boy_id') or r.get('mechanic_id')
            socketio.emit('request_updated', r, room=prov_id or 'providers')
            return jsonify({'success':True})
    return jsonify({'error':'Not found or not authorized'}),404

@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    if 'user_id' not in session: return jsonify({'error':'Unauthorized'}),401
    db = load_db(); data = request.json; req_id = data.get('request_id')
    for r in db['requests']:
        if r['id']==req_id:
            if r['status']!='completed':
                return jsonify({'error':'Confirm delivery first'}),400
            r['feedback_rating']=data.get('rating'); r['feedback_comment']=data.get('comment','')
            r['feedback_at']=datetime.now().isoformat(); break
    fb = {'id':str(uuid.uuid4()),'request_id':req_id,'customer_id':session['user_id'],
          'customer_name':session['name'],'rating':data.get('rating'),
          'comment':data.get('comment',''),'created_at':datetime.now().isoformat()}
    db['feedback'].append(fb); save_db(db)
    return jsonify({'success':True})

@app.route('/api/admin/verify/<user_id>', methods=['POST'])
def verify_user(user_id):
    if session.get('role')!='admin': return jsonify({'error':'Unauthorized'}),401
    db = load_db()
    for u in db['users']:
        if u['id']==user_id:
            u['verified']=True; save_db(db); sync_user_to_csv(u)
            return jsonify({'success':True})
    return jsonify({'error':'Not found'}),404

@app.route('/api/admin/assign', methods=['POST'])
def admin_assign():
    if session.get('role')!='admin': return jsonify({'error':'Unauthorized'}),401
    db = load_db(); data = request.json
    for r in db['requests']:
        if r['id']==data.get('request_id'):
            worker = next((u for u in db['users'] if u['id']==data.get('worker_id')), None)
            if data.get('role')=='mechanic':
                r['mechanic_id']=data['worker_id']; r['mechanic_name']=worker['name'] if worker else ''
            else:
                r['fuel_boy_id']=data['worker_id']; r['fuel_boy_name']=worker['name'] if worker else ''
            if worker:
                dist=haversine(worker['lat'],worker['lon'],r['lat'],r['lon'])
                r['provider_distance_km']=round(dist,1); r['quoted_eta_minutes']=round((dist/SPEED_KMH)*60+5)
            r['status']='ongoing'; r['accepted_at']=datetime.now().isoformat()
            save_db(db); return jsonify({'success':True})
    return jsonify({'error':'Not found'}),404

@app.route('/api/requests')
def get_requests():
    db = load_db(); uid = session.get('user_id'); role = session.get('role')
    if role=='customer': reqs=[r for r in db['requests'] if r['customer_id']==uid]
    elif role=='mechanic': reqs=[r for r in db['requests'] if r.get('mechanic_id')==uid]
    elif role=='fuel_boy': reqs=[r for r in db['requests'] if r.get('fuel_boy_id')==uid]
    else: reqs=db['requests']
    return jsonify(reqs)

@app.route('/api/workers')
def get_workers():
    if session.get('role')!='admin': return jsonify([])
    db = load_db()
    workers=[u for u in db['users'] if u['role'] in ('mechanic','fuel_boy') and u['verified']]
    return jsonify([{'id':w['id'],'name':w['name'],'role':w['role']} for w in workers])

@app.route('/admin/csv/<kind>')
def download_csv(kind):
    if session.get('role')!='admin': return redirect(url_for('login'))
    from flask import send_file
    mapping={'customers':CUSTOMERS_CSV,'agents':AGENTS_CSV,'mechanics':MECHANICS_CSV}
    path=mapping.get(kind)
    if not path or not os.path.exists(path):
        flash(f'No {kind} CSV found.','error'); return redirect(url_for('dashboard_admin'))
    return send_file(path, as_attachment=True, download_name=f'fuelaid_{kind}.csv')

@socketio.on('join')
def on_join(data):
    room = data.get('room', session.get('user_id'))
    join_room(room)
    if data.get('role') in ('mechanic','fuel_boy','admin'):
        join_room('providers')

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
