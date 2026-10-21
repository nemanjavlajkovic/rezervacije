from flask import Flask, request, jsonify, session, render_template, redirect
import json, os, hashlib
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'promeni_ovo_123')

DATABASE_URL = os.environ.get('DATABASE_URL', '')

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

# ── Database ───────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    alias TEXT DEFAULT '',
                    oslovljavanje TEXT DEFAULT '-',
                    ulica TEXT DEFAULT '',
                    ptt TEXT DEFAULT '',
                    grad TEXT DEFAULT '',
                    telefon TEXT DEFAULT '',
                    rodjadan TEXT DEFAULT '',
                    beleske TEXT DEFAULT '',
                    created_at TEXT DEFAULT ''
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS bookings (
                    key TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'taken',
                    user_id INTEGER,
                    user_name TEXT,
                    user_email TEXT,
                    payment_status TEXT DEFAULT 'na_cekanju',
                    beleske TEXT DEFAULT '',
                    igraci INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT ''
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS klijenti (
                    id SERIAL PRIMARY KEY,
                    ime TEXT NOT NULL,
                    telefon TEXT DEFAULT '',
                    pretplatnik BOOLEAN DEFAULT FALSE
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS dogadjaji (
                    id SERIAL PRIMARY KEY,
                    naziv TEXT NOT NULL,
                    opis TEXT DEFAULT '',
                    datum_od TEXT DEFAULT '',
                    vreme_od TEXT DEFAULT '',
                    datum_do TEXT DEFAULT '',
                    vreme_do TEXT DEFAULT '',
                    teren TEXT DEFAULT '',
                    kapacitet INTEGER DEFAULT 0,
                    beleske TEXT DEFAULT '',
                    status TEXT DEFAULT 'aktivan',
                    created_at TEXT DEFAULT ''
                )
            ''')
        conn.commit()

# ── Helpers ───────────────────────────────────────────────────────────────────

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

def admin_required():
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect('/')
    return None

# ── Seed admin user if missing ────────────────────────────────────────────────

def ensure_admin():
    seed_users = [
        {'email': 'admin@klub.rs',               'password': hp('password'), 'name': 'Administrator',   'role': 'admin'},
        {'email': 'ivanajovanovicc07@gmail.com',  'password': hp('Ivana07'),  'name': 'Ivana Jovanovic', 'role': 'admin'},
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            for su in seed_users:
                cur.execute('SELECT id, role FROM users WHERE lower(email)=lower(%s)', (su['email'],))
                existing = cur.fetchone()
                if not existing:
                    cur.execute(
                        'INSERT INTO users (email, password, name, role) VALUES (%s,%s,%s,%s)',
                        (su['email'], su['password'], su['name'], su['role'])
                    )
                elif existing['role'] != 'admin':
                    cur.execute('UPDATE users SET role=%s WHERE id=%s', ('admin', existing['id']))
        conn.commit()

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

@app.route('/admin/korisnici')
def admin_korisnici():
    u = current_user()
    if not u or u['role'] != 'admin':
        return redirect('/')
    return render_template('admin_korisnici.html')

@app.route('/admin/rezervacije')
def admin_rezervacije_page():
    u = current_user()
    if not u or u['role'] not in ('admin', 'staff'):
        return redirect('/')
    return render_template('admin_rezervacije.html')

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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM users WHERE lower(email)=%s AND password=%s', (email, hp(pw)))
            u = cur.fetchone()
    if not u:
        return err('Pogrešan email ili lozinka.')
    session['user'] = {'id': u['id'], 'email': u['email'], 'name': u['name'], 'role': u['role']}
    return ok({'user': session['user']})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return ok()

@app.route('/api/raspored')
def api_raspored():
    date_str = request.args.get('date', str(date.today()))
    now = datetime.now(ZoneInfo('Europe/Belgrade')).replace(tzinfo=None)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bookings WHERE key LIKE %s', (date_str + '|%',))
            rows = cur.fetchall()
    bookings = {r['key']: dict(r) for r in rows}
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
                elif u and (u['role'] == 'admin' or u['email'] == b.get('user_email', '')):
                    booked_by = b.get('user_name')
            result[cid]['slots'][h] = {
                'status': status,
                'booked_by': booked_by,
                'payment_status': b.get('payment_status', 'na_cekanju')
            }
    return ok({'date': date_str, 'courts': result})

@app.route('/api/rezervisi', methods=['POST'])
def api_rezervisi():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    date_str = d.get('date', '')
    court    = d.get('court', '')
    hour     = int(d.get('hour', 0))
    if court not in TERENI: return err('Neispravan teren.')
    if hour < START_SAT or hour >= END_SAT: return err('Neispravan sat.')
    slot_dt = datetime.strptime(f"{date_str} {hour:02d}:00", "%Y-%m-%d %H:%M")
    if slot_dt < datetime.now(): return err('Ne možete rezervisati prošli termin.')
    key = slot_key(date_str, court, hour)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT status FROM bookings WHERE key=%s', (key,))
            existing = cur.fetchone()
            if existing and existing['status'] in ('taken', 'sub'):
                return err('Termin je već zauzet.')
            ime = d.get('name', u['name'])
            status_rez = d.get('status', 'taken')
            if status_rez not in ('taken', 'sub'):
                status_rez = 'taken'
            # Ako je prosleđen user_id (admin rezerviše na ime korisnika iz sistema)
            booking_user_id = u['id']
            booking_user_email = u['email']
            explicit_uid = d.get('user_id')
            if explicit_uid and (u['role'] == 'admin' or u['role'] == 'staff'):
                cur.execute('SELECT id, email, name, alias FROM users WHERE id=%s', (int(explicit_uid),))
                found = cur.fetchone()
                if found:
                    booking_user_id = found['id']
                    booking_user_email = found['email']
                    ime = found['alias'] or found['name']
            cur.execute('''
                INSERT INTO bookings (key, status, user_id, user_name, user_email, created_at)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (key) DO UPDATE SET
                    status=EXCLUDED.status, user_id=EXCLUDED.user_id,
                    user_name=EXCLUDED.user_name, user_email=EXCLUDED.user_email,
                    created_at=EXCLUDED.created_at
            ''', (key, status_rez, booking_user_id, ime, booking_user_email, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    return ok({'message': 'Termin uspješno rezervisan!'})

@app.route('/api/otkazi', methods=['POST'])
def api_otkazi():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    key = slot_key(d.get('date', ''), d.get('court', ''), int(d.get('hour', 0)))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bookings WHERE key=%s', (key,))
            b = cur.fetchone()
            if not b: return err('Termin nije pronađen.')
            if u['role'] != 'admin' and b['user_id'] != u['id']:
                return err('Nemate dozvolu.')
            cur.execute('DELETE FROM bookings WHERE key=%s', (key,))
        conn.commit()
    return ok({'message': 'Rezervacija otkazana.'})

@app.route('/api/edituj_rezervaciju', methods=['POST'])
def api_edituj_rezervaciju():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    old_key = d.get('old_key', '')
    new_date = d.get('new_date', '')
    new_court = d.get('new_court', '')
    new_hour = int(d.get('new_hour', 0))
    payment_status = d.get('payment_status', 'na_cekanju')
    if payment_status not in ('na_cekanju', 'placeno', 'nedolazak', 'otkazano'):
        return err('Neispravan status plaćanja.')
    new_key = slot_key(new_date, new_court, new_hour)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bookings WHERE key=%s', (old_key,))
            old_b = cur.fetchone()
            if not old_b: return err('Rezervacija nije pronađena.')
            if new_key != old_key:
                cur.execute('SELECT key FROM bookings WHERE key=%s', (new_key,))
                if cur.fetchone(): return err('Novi termin je već zauzet.')
                cur.execute('DELETE FROM bookings WHERE key=%s', (old_key,))
            cur.execute('''
                INSERT INTO bookings (key, status, user_id, user_name, user_email, payment_status, beleske, igraci, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (key) DO UPDATE SET
                    payment_status=EXCLUDED.payment_status
            ''', (new_key, old_b['status'], old_b['user_id'], old_b['user_name'],
                  old_b['user_email'], payment_status, old_b['beleske'],
                  old_b['igraci'], old_b['created_at']))
        conn.commit()
    return ok({'message': 'Rezervacija ažurirana!'})

@app.route('/api/admin/rezervacije')
def api_admin_rez():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bookings ORDER BY key')
            rows = cur.fetchall()
    lst = []
    for r in rows:
        parts = r['key'].split('|')
        if len(parts) != 3: continue
        dt, cid, hour = parts
        lst.append({
            'key': r['key'], 'date': dt, 'court_id': cid,
            'court_name': TERENI.get(cid, cid),
            'hour': hour,
            'user_name': r['user_name'] or '?',
            'user_email': r['user_email'] or '?',
            'status': r['status'] or '?',
            'created_at': r['created_at'] or '',
        })
    return ok({'rezervacije': lst})

@app.route('/api/admin/set', methods=['POST'])
def api_admin_set():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    key    = slot_key(d.get('date', ''), d.get('court', ''), int(d.get('hour', 0)))
    status = d.get('status', 'taken')
    with get_conn() as conn:
        with conn.cursor() as cur:
            if status == 'free':
                cur.execute('DELETE FROM bookings WHERE key=%s', (key,))
            else:
                name = d.get('name', 'Admin')
                cur.execute('''
                    INSERT INTO bookings (key, status, user_id, user_name, user_email, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (key) DO UPDATE SET
                        status=EXCLUDED.status, user_name=EXCLUDED.user_name
                ''', (key, status, 1, name, 'admin@klub.rs', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    return ok()

@app.route('/api/admin/korisnici')
def api_korisnici():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id,email,name,role,alias,oslovljavanje,ulica,ptt,grad,telefon,rodjadan,beleske,created_at FROM users ORDER BY id')
            users = cur.fetchall()
    return ok({'korisnici': [dict(u) for u in users]})

@app.route('/api/admin/dodaj_korisnika', methods=['POST'])
def api_dodaj():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    email = (d.get('email') or '').strip()
    pw    = d.get('password') or ''
    name  = (d.get('name') or '').strip()
    role  = d.get('role', 'user')
    if not email or not pw or not name: return err('Sva polja su obavezna.')
    if role not in ('user', 'admin', 'staff'): return err('Neispravan role.')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM users WHERE lower(email)=lower(%s)', (email,))
            if cur.fetchone(): return err('Email već postoji.')
            cur.execute('''
                INSERT INTO users (email, password, name, role, telefon, beleske)
                VALUES (%s,%s,%s,%s,%s,%s)
            ''', (email, hp(pw), name, role, d.get('telefon', ''), d.get('beleske', '')))
        conn.commit()
    return ok({'message': 'Korisnik dodat.'})

@app.route('/api/admin/brisi_korisnika', methods=['POST'])
def api_brisi():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    tid = int((request.json or {}).get('id', 0))
    if u['id'] == tid: return err('Ne možete obrisati sami sebe.')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM users WHERE id=%s', (tid,))
        conn.commit()
    return ok()

@app.route('/api/admin/uredi_korisnika', methods=['POST'])
def api_uredi_korisnika():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    tid = int(d.get('id', 0))
    fields = []
    vals = []
    for fld in ('name', 'email', 'alias', 'oslovljavanje', 'ulica', 'ptt', 'grad', 'telefon', 'rodjadan', 'beleske'):
        if fld in d:
            fields.append(f'{fld}=%s')
            vals.append(d[fld])
    if 'role' in d and d['role'] in ('user', 'admin', 'staff'):
        fields.append('role=%s')
        vals.append(d['role'])
    if d.get('password'):
        fields.append('password=%s')
        vals.append(hp(d['password']))
    if not fields: return err('Nema polja za ažuriranje.')
    vals.append(tid)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f'UPDATE users SET {",".join(fields)} WHERE id=%s', vals)
        conn.commit()
    return ok({'message': 'Korisnik sačuvan.'})

@app.route('/api/admin/promeni_lozinku', methods=['POST'])
def api_lozinka():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    tid = int(d.get('id', 0))
    pw  = d.get('password', '')
    if not pw: return err('Unesite lozinku.')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE users SET password=%s WHERE id=%s', (hp(pw), tid))
        conn.commit()
    return ok({'message': 'Lozinka promenjena.'})

@app.route('/api/promeni_lozinku', methods=['POST'])
def api_promeni_lozinku_self():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    stara = d.get('stara', '')
    nova  = d.get('nova', '')
    if not stara or not nova: return err('Unesite staru i novu lozinku.')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT password FROM users WHERE id=%s', (u['id'],))
            row = cur.fetchone()
            if not row or row['password'] != hp(stara):
                return err('Stara lozinka nije ispravna.')
            cur.execute('UPDATE users SET password=%s WHERE id=%s', (hp(nova), u['id']))
        conn.commit()
    return ok({'message': 'Lozinka promijenjena.'})

@app.route('/api/rezervisi_pretplatu', methods=['POST'])
def api_rezervisi_pretplatu():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    date_od  = d.get('date_od', '')
    date_do  = d.get('date_do', '')
    court    = d.get('court', '')
    hour     = int(d.get('hour', 0))
    ime           = d.get('name', '')
    interval_dana = int(d.get('interval_dana', 7))
    payment_status = d.get('payment_status', 'na_cekanju')
    beleske       = d.get('beleske', '')
    igraci        = int(d.get('igraci', 1))
    if court not in TERENI: return err('Neispravan teren.')
    if hour < START_SAT or hour >= END_SAT: return err('Neispravan sat.')
    if not date_od or not date_do: return err('Unesite period.')
    if not ime: return err('Unesite ime klijenta.')
    if interval_dana < 1: interval_dana = 1
    try:
        od = datetime.strptime(date_od, '%Y-%m-%d')
        do = datetime.strptime(date_do, '%Y-%m-%d')
    except:
        return err('Neispravan datum.')
    if do < od: return err('Krajnji datum mora biti nakon početnog.')
    # Ako je prosleđen user_id (admin rezerviše na ime korisnika iz sistema)
    booking_user_id = u['id']
    booking_user_email = u['email']
    explicit_uid = d.get('user_id')
    if explicit_uid and (u['role'] == 'admin' or u['role'] == 'staff'):
        with get_conn() as conn2:
            with conn2.cursor() as cur2:
                cur2.execute('SELECT id, email, name, alias FROM users WHERE id=%s', (int(explicit_uid),))
                found = cur2.fetchone()
                if found:
                    booking_user_id = found['id']
                    booking_user_email = found['email']
                    ime = found['alias'] or found['name']
    kreirano = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            current = od
            while current <= do:
                slot_dt = current.replace(hour=hour, minute=0, second=0)
                if slot_dt >= datetime.now():
                    key = slot_key(current.strftime('%Y-%m-%d'), court, hour)
                    cur.execute('SELECT key FROM bookings WHERE key=%s', (key,))
                    if not cur.fetchone():
                        cur.execute('''
                            INSERT INTO bookings (key, status, user_id, user_name, user_email, payment_status, beleske, igraci, created_at)
                            VALUES (%s,'sub',%s,%s,%s,%s,%s,%s,%s)
                        ''', (key, booking_user_id, ime, booking_user_email, payment_status, beleske, igraci,
                              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                        kreirano += 1
                current = current + timedelta(days=interval_dana)
        conn.commit()
    return ok({'message': f'Kreirano {kreirano} rezervacija!'})

# ── Klijenti ──────────────────────────────────────────────────────────────────

@app.route('/api/klijenti')
def api_klijenti():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    q = request.args.get('q', '').lower()
    with get_conn() as conn:
        with conn.cursor() as cur:
            if q:
                cur.execute('SELECT * FROM klijenti WHERE lower(ime) LIKE %s OR lower(telefon) LIKE %s ORDER BY ime', (f'%{q}%', f'%{q}%'))
            else:
                cur.execute('SELECT * FROM klijenti ORDER BY ime')
            klijenti = cur.fetchall()
    return ok({'klijenti': [dict(k) for k in klijenti]})

@app.route('/api/dodaj_klijenta', methods=['POST'])
def api_dodaj_klijenta():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    ime = (d.get('ime') or '').strip()
    telefon = (d.get('telefon') or '').strip()
    pretplatnik = bool(d.get('pretplatnik', False))
    if not ime: return err('Unesite ime.')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO klijenti (ime, telefon, pretplatnik) VALUES (%s,%s,%s)', (ime, telefon, pretplatnik))
        conn.commit()
    return ok({'message': 'Klijent dodat.'})

@app.route('/api/brisi_klijenta', methods=['POST'])
def api_brisi_klijenta():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    kid = int((request.json or {}).get('id', 0))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM klijenti WHERE id=%s', (kid,))
        conn.commit()
    return ok()

@app.route('/api/promeni_klijenta', methods=['POST'])
def api_promeni_klijenta():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    d = request.json or {}
    kid = int(d.get('id', 0))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE klijenti SET pretplatnik = NOT pretplatnik WHERE id=%s', (kid,))
        conn.commit()
    return ok()

# ── User pages ────────────────────────────────────────────────────────────────

@app.route('/user/bookings')
def user_bookings():
    u = current_user()
    if not u: return redirect('/')
    return render_template('user_bookings.html')

@app.route('/api/moje_rezervacije')
def api_moje_rezervacije():
    u = current_user()
    if not u: return err('Niste prijavljeni.', 401)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bookings WHERE user_id=%s ORDER BY key', (u['id'],))
            rows = cur.fetchall()
    lst = []
    for r in rows:
        parts = r['key'].split('|')
        if len(parts) != 3: continue
        dt, cid, hour = parts
        lst.append({
            'key': r['key'], 'date': dt, 'court_id': cid,
            'court_name': TERENI.get(cid, cid),
            'hour': hour,
            'status': r['status'] or 'taken',
            'payment_status': r['payment_status'] or 'na_cekanju',
            'created_at': r['created_at'] or '',
        })
    return ok({'rezervacije': lst})

# ── Događaji ──────────────────────────────────────────────────────────────────

@app.route('/admin/dogadjaji')
def admin_dogadjaji_page():
    u = current_user()
    if not u or u['role'] != 'admin': return redirect('/')
    return render_template('admin_dogadjaji.html')

@app.route('/api/admin/dogadjaji')
def api_admin_dogadjaji():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM dogadjaji ORDER BY datum_od')
            dogadjaji = cur.fetchall()
    return ok({'dogadjaji': [dict(d) for d in dogadjaji]})

@app.route('/api/admin/dodaj_dogadjaj', methods=['POST'])
def api_dodaj_dogadjaj():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    naziv = (d.get('naziv') or '').strip()
    datum = (d.get('datum_od') or d.get('datum') or '').strip()
    if not naziv or not datum: return err('Naziv i datum su obavezni.')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO dogadjaji (naziv, opis, datum_od, vreme_od, datum_do, vreme_do, teren, kapacitet, beleske, status, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ''', (naziv, d.get('opis', ''), datum, d.get('vreme_od', d.get('vreme', '10:00')),
                  d.get('datum_do', datum), d.get('vreme_do', ''),
                  d.get('teren', d.get('lokacija', '')),
                  d.get('kapacitet') or d.get('max_ucenika') or 0,
                  d.get('beleske', ''), 'aktivan',
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    return ok({'message': 'Događaj kreiran.'})

@app.route('/api/admin/uredi_dogadjaj', methods=['POST'])
def api_uredi_dogadjaj():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    d = request.json or {}
    tid = int(d.get('id', 0))
    fields = []
    vals = []
    for fld in ('naziv', 'opis', 'datum_od', 'vreme_od', 'datum_do', 'vreme_do', 'teren', 'status', 'beleske'):
        if fld in d:
            fields.append(f'{fld}=%s')
            vals.append(d[fld])
    if 'kapacitet' in d:
        fields.append('kapacitet=%s')
        vals.append(d['kapacitet'] or 0)
    if not fields: return err('Nema polja za ažuriranje.')
    vals.append(tid)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f'UPDATE dogadjaji SET {",".join(fields)} WHERE id=%s', vals)
        conn.commit()
    return ok({'message': 'Događaj sačuvan.'})

@app.route('/api/admin/brisi_dogadjaj', methods=['POST'])
def api_brisi_dogadjaj():
    u = current_user()
    if not u or u['role'] != 'admin': return err('Nemate dozvolu.', 403)
    tid = int((request.json or {}).get('id', 0))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM dogadjaji WHERE id=%s', (tid,))
        conn.commit()
    return ok({'message': 'Događaj obrisan.'})

# ── Admin statistika ──────────────────────────────────────────────────────────

@app.route('/admin/statistika')
def admin_statistika():
    u = current_user()
    if not u or u['role'] != 'admin': return redirect('/')
    return render_template('admin_statistika.html')

# ── Init ──────────────────────────────────────────────────────────────────────

init_db()

if __name__ == '__main__':
    app.run(debug=True)
