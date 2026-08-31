from flask import Flask, request, jsonify, session, render_template, redirect
import json, os, hashlib
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'promeni_ovo_123')

DATA_DIR   = os.path.join(os.path.dirname(__file__), 'data')
USERS_F    = os.path.join(DATA_DIR, 'users.json')
BOOKINGS_F = os.path.join(DATA_DIR, 'bookings.json')
KLIJENTI_F = os.path.join(DATA_DIR, 'klijenti.json')

KLUB_IME  = 'Byford Country Club'
TELEFON   = '063-3-6666-4'
START_SAT = 7
END_SAT   = 23

TERENI = {
    'p1': 'Padel 1',
    'p2': 'Padel 2',
    't1': '1',
    't2': '2',
    't3': '3 (balon)',
    't4': '4 (balon)',
    't5': '5 (hala)',
    't6': '6 (hala)',
    't7': '7',
    't8': '8',
    't9': '9',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def read(f):
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(f):
        return [] if f == USERS_F else {}
    with open(f, encoding='utf-8') as fp:
        return json.load(fp)

def write(f, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(f, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)

def hp(p):
    return hashlib.sha256(p.encode()).hexdigest()

def slot_key(d, court, hour):
    return f"{d}|{court}|{str(hour).zfill(2)}"

def current_user():
    return session.get('user')

def ok(data=None):
    r = {'ok': True}
    if data: r.update(data)
    return jsonify(r)

def err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code

# ── Seed admin user if missing ────────────────────────────────────────────────

def ensure_admin():
    users = read(USERS_F)
    emails = [u['email'].lower() for u in users]
    changed = False
    if 'admin@klub.rs' not in emails:
        users.append({
            'id': 1, 'email': 'admin@klub.rs',
            'password': hp('password'),
            'name': 'Administrator', 'role': 'admin'
        })
        changed = True
    if 'ivanajovanovicc07@gmail.com' not in emails:
        users.append({
            'id': 2, 'email': 'ivanajovanovicc07@gmail.com',
            'password': hp('Ivana07'),
            'name': 'Ivana Jovanovic', 'role': 'admin'
        })
        changed = True
    if changed:
        write(USERS_F, users)
# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    ensure_admin()
    return render_template('index.html',
        klub=KLUB_IME, tel=TELEFON,
        start=START_SAT, end=END_SAT,
        tereni=TERENI)

@app.route('/admin/')
def admin():
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect('/')
    return render_template('admin.html',
    klub=KLUB_IME, tereni=TERENI,
    start=START_SAT, end=END_SAT,
    slots=list(range(START_SAT, END_SAT)))

# ── API ───────────────────────────────────────────────────────────────────────

@app.route('/api/me')
def api_me():
    return ok({'user': current_user()})

@app.route('/api/login', methods=['POST'])
def api_login():
    d = request.json or {}
    email = (d.get('email') or '').strip().lower()
    pw    = d.get('password') or ''
    if not email or not pw:
        return err('Unesite email i lozinku.')
    for u in read(USERS_F):
        if u['email'].lower() == email and u['password'] == hp(pw):
            session['user'] = {'id':u['id'],'email':u['email'],'name':u['name'],'role':u['role']}
            return ok({'user': session['user']})
    return err('Pogrešan email ili lozinka.')

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return ok()

@app.route('/api/raspored')
def api_raspored():
    date_str = request.args.get('date', str(date.today()))
    bookings = read(BOOKINGS_F)
    now = datetime.now(ZoneInfo('Europe/Belgrade')).replace(tzinfo=None)    
    result = {}
    for cid, cname in TERENI.items():
        result[cid] = {'name': cname, 'slots': {}}
        for h in range(START_SAT, END_SAT):
            key = slot_key(date_str, cid, h)
            slot_dt = datetime.strptime(f"{date_str} {h:02d}:00", "%Y-%m-%d %H:%M")
            if slot_dt < now:
                status = 'past'
            elif key in bookings:
                status = bookings[key]['status']
            else:
                status = 'free'
            b = bookings.get(key, {})
            booked_by = None
            if b:
                u = current_user()
                if status == 'past':
                    booked_by = b.get('user_name')
                elif u and (u['role'] == 'admin' or u['email'] == b.get('user_email','')):
                    booked_by = b.get('user_name')
            result[cid]['slots'][h] = {'status': status, 'booked_by': booked_by}

@app.route('/api/rezervisi', methods=['POST'])
def api_rezervisi():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    date_str = d.get('date','')
    court    = d.get('court','')
    hour     = int(d.get('hour', 0))
    if court not in TERENI: return err('Neispravan teren.')
    if hour < START_SAT or hour >= END_SAT: return err('Neispravan sat.')
    slot_dt = datetime.strptime(f"{date_str} {hour:02d}:00", "%Y-%m-%d %H:%M")
    if slot_dt < datetime.now(): return err('Ne možete rezervisati prošli termin.')
    key = slot_key(date_str, court, hour)
    bookings = read(BOOKINGS_F)
    if key in bookings and bookings[key]['status'] in ('taken','sub'):
        return err('Termin je već zauzet.')
    ime = d.get('name', u['name'])
    status_rez = d.get('status', 'taken')
    if status_rez not in ('taken', 'sub'):
        status_rez = 'taken'
    bookings[key] = {
        'status': status_rez,
        'user_id': u['id'], 'user_name': ime,
        'user_email': u['email'],
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    write(BOOKINGS_F, bookings)
    return ok({'message': 'Termin uspješno rezervisan!'})

@app.route('/api/otkazi', methods=['POST'])
def api_otkazi():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    key = slot_key(d.get('date',''), d.get('court',''), int(d.get('hour',0)))
    bookings = read(BOOKINGS_F)
    if key not in bookings: return err('Termin nije pronađen.')
    if u['role'] != 'admin' and bookings[key].get('user_id') != u['id']:
        return err('Nemate dozvolu.')
    del bookings[key]
    write(BOOKINGS_F, bookings)
    return ok({'message': 'Rezervacija otkazana.'})

@app.route('/api/admin/rezervacije')
def api_admin_rez():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    bookings = read(BOOKINGS_F)
    lst = []
    for key, val in bookings.items():
        parts = key.split('|')
        if len(parts) != 3: continue
        dt, cid, hour = parts
        lst.append({
            'key': key, 'date': dt, 'court_id': cid,
            'court_name': TERENI.get(cid, cid),
            'hour': hour,
            'user_name':  val.get('user_name','?'),
            'user_email': val.get('user_email','?'),
            'status':     val.get('status','?'),
            'created_at': val.get('created_at',''),
        })
    lst.sort(key=lambda x: x['date']+x['hour'])
    return ok({'rezervacije': lst})

@app.route('/api/admin/set', methods=['POST'])
def api_admin_set():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    key    = slot_key(d.get('date',''), d.get('court',''), int(d.get('hour',0)))
    status = d.get('status','taken')
    bookings = read(BOOKINGS_F)
    if status == 'free':
        bookings.pop(key, None)
    else:
            name = d.get('name', 'Admin')
            bookings[key] = {
                'status': status, 'user_id': 1,
                'user_name': name, 'user_email': 'admin@klub.rs',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
    write(BOOKINGS_F, bookings)
    return ok()

@app.route('/api/admin/korisnici')
def api_korisnici():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    users = read(USERS_F)
    safe = [{'id':x['id'],'email':x['email'],'name':x['name'],'role':x['role']} for x in users]
    return ok({'korisnici': safe})

@app.route('/api/admin/dodaj_korisnika', methods=['POST'])
def api_dodaj():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    email = (d.get('email') or '').strip()
    pw    = d.get('password') or ''
    name  = (d.get('name') or '').strip()
    role  = d.get('role','user')
    if not email or not pw or not name: return err('Sva polja su obavezna.')
    if role not in ('user','admin'): return err('Neispravan role.')
    users = read(USERS_F)
    if any(x['email'].lower()==email.lower() for x in users):
        return err('Email već postoji.')
    new_id = max((x['id'] for x in users), default=0) + 1
    users.append({'id':new_id,'email':email,'password':hp(pw),'name':name,'role':role})
    write(USERS_F, users)
    return ok({'message': 'Korisnik dodat.'})

@app.route('/api/admin/brisi_korisnika', methods=['POST'])
def api_brisi():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    tid = int((request.json or {}).get('id', 0))
    if u['id'] == tid: return err('Ne možete obrisati sami sebe.')
    users = [x for x in read(USERS_F) if x['id'] != tid]
    write(USERS_F, users)
    return ok()

@app.route('/api/admin/promeni_lozinku', methods=['POST'])
def api_lozinka():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    tid = int(d.get('id', 0))
    pw  = d.get('password','')
    if not pw: return err('Unesite lozinku.')
    users = read(USERS_F)
    for x in users:
        if x['id'] == tid:
            x['password'] = hp(pw)
    write(USERS_F, users)
    return ok({'message': 'Lozinka promenjena.'})
    
@app.route('/api/rezervisi_pretplatu', methods=['POST'])
def api_rezervisi_pretplatu():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    date_od  = d.get('date_od','')
    date_do  = d.get('date_do','')
    court    = d.get('court','')
    hour     = int(d.get('hour', 0))
    ime      = d.get('name','')

    if court not in TERENI: return err('Neispravan teren.')
    if hour < START_SAT or hour >= END_SAT: return err('Neispravan sat.')
    if not date_od or not date_do: return err('Unesite period.')
    if not ime: return err('Unesite ime klijenta.')

    try:
        od = datetime.strptime(date_od, '%Y-%m-%d')
        do = datetime.strptime(date_do, '%Y-%m-%d')
    except:
        return err('Neispravan datum.')

    if do < od: return err('Krajnji datum mora biti nakon početnog.')

    bookings = read(BOOKINGS_F)
    kreirano = 0
    current = od
    while current <= do:
        slot_dt = current.replace(hour=hour, minute=0, second=0)
        if slot_dt >= datetime.now():
            key = slot_key(current.strftime('%Y-%m-%d'), court, hour)
            if key not in bookings:
                bookings[key] = {
                    'status': 'sub',
                    'user_id': u['id'],
                    'user_name': ime,
                    'user_email': u['email'],
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                kreirano += 1
        current = current + timedelta(days=7)

    write(BOOKINGS_F, bookings)
    return ok({'message': f'Kreirano {kreirano} rezervacija za pretplatu!'})
if __name__ == '__main__':
    app.run(debug=True)
    
# ── Klijenti ──────────────────────────────────────────────────────────────────

@app.route('/api/klijenti')
def api_klijenti():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    klijenti = read(KLIJENTI_F) if os.path.exists(KLIJENTI_F) else []
    q = request.args.get('q','').lower()
    if q:
        klijenti = [k for k in klijenti if q in k['ime'].lower() or q in k.get('telefon','').lower()]
    return ok({'klijenti': klijenti})

@app.route('/api/dodaj_klijenta', methods=['POST'])
def api_dodaj_klijenta():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    ime = (d.get('ime') or '').strip()
    telefon = (d.get('telefon') or '').strip()
    pretplatnik = bool(d.get('pretplatnik', False))
    if not ime: return err('Unesite ime.')
    klijenti = read(KLIJENTI_F) if os.path.exists(KLIJENTI_F) else []
    new_id = max((k['id'] for k in klijenti), default=0) + 1
    klijenti.append({'id': new_id, 'ime': ime, 'telefon': telefon, 'pretplatnik': pretplatnik})
    write(KLIJENTI_F, klijenti)
    return ok({'message': 'Klijent dodat.'})

@app.route('/api/brisi_klijenta', methods=['POST'])
def api_brisi_klijenta():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    kid = int((request.json or {}).get('id', 0))
    klijenti = read(KLIJENTI_F) if os.path.exists(KLIJENTI_F) else []
    klijenti = [k for k in klijenti if k['id'] != kid]
    write(KLIJENTI_F, klijenti)
    return ok()

@app.route('/api/promeni_klijenta', methods=['POST'])
def api_promeni_klijenta():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    kid = int(d.get('id', 0))
    klijenti = read(KLIJENTI_F) if os.path.exists(KLIJENTI_F) else []
    for k in klijenti:
        if k['id'] == kid:
            k['pretplatnik'] = not k['pretplatnik']
    write(KLIJENTI_F, klijenti)
    return ok()
