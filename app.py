import os, re, sqlite3, secrets, uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_file, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv('DATABASE_PATH', str(BASE / 'friends_village.sqlite3')))
UPLOAD_DIR = Path(os.getenv('RECEIPT_DIR', str(BASE / 'private_receipts')))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}
INVITE_URL = os.getenv('DISCORD_INVITE_URL', 'https://discord.com/oauth2/authorize?client_id=1570918671805718699&permissions=3156992&integration_type=0&scope=bot+applications.commands')
WA_NUMBER = re.sub(r'\D', '', os.getenv('WHATSAPP_NUMBER', '9647506045491'))
FIB_NUMBER = os.getenv('FIB_NUMBER', '0750 604 5491')
ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH', '')
APP_SECRET = os.getenv('SECRET_KEY', '')

app = Flask(__name__)
app.secret_key = APP_SECRET or 'dev-only-change-this-secret-before-deployment'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('COOKIE_SECURE', '0') == '1'


def now_utc():
    return datetime.now(timezone.utc)


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def init_db():
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_token TEXT NOT NULL UNIQUE,
            server_name TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            owner_discord_id TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            whatsapp TEXT NOT NULL,
            receipt_filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            reviewer_note TEXT
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL UNIQUE,
            server_name TEXT NOT NULL,
            owner_discord_id TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            application_id INTEGER,
            FOREIGN KEY(application_id) REFERENCES applications(id)
        );
        CREATE INDEX IF NOT EXISTS idx_subscriptions_guild ON subscriptions(guild_id);
        ''')


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin_ok'):
            return redirect(url_for('admin_login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED


@app.before_request
def protect_post_requests():
    if request.method == 'POST':
        expected = session.get('_csrf_token', '')
        supplied = request.form.get('_csrf_token', '')
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(400)


@app.context_processor
def inject_globals():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return {'fib_number': FIB_NUMBER, 'whatsapp_number': WA_NUMBER, 'whatsapp_link': f'https://wa.me/{WA_NUMBER}', 'year': now_utc().year, 'csrf_token': session['_csrf_token']}


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/apply', methods=['GET', 'POST'])
def apply():
    if request.method == 'POST':
        server_name = request.form.get('server_name', '').strip()[:100]
        guild_id = request.form.get('guild_id', '').strip()
        owner_id = request.form.get('owner_discord_id', '').strip()
        contact = request.form.get('contact_name', '').strip()[:80]
        whatsapp = request.form.get('whatsapp', '').strip()[:30]
        receipt = request.files.get('receipt')
        if not server_name or not contact or not whatsapp:
            flash('تکایە هەمی خانە پێدڤییەکان پڕ بکە.', 'error')
            return render_template('apply.html')
        if not guild_id.isdigit() or len(guild_id) < 15 or len(guild_id) > 22:
            flash('ژمارا سێرڤەرێ (Server ID) پێدڤییە دروست بیت.', 'error')
            return render_template('apply.html')
        if not owner_id.isdigit() or len(owner_id) < 15 or len(owner_id) > 22:
            flash('ژمارا Discord ID یا خاوەن سێرڤەرێ پێدڤییە دروست بیت.', 'error')
            return render_template('apply.html')
        if not receipt or not receipt.filename or not allowed_file(receipt.filename):
            flash('پسوولەی پارەدانێ وەک وێنە یان PDF بار بکە.', 'error')
            return render_template('apply.html')
        token = secrets.token_urlsafe(32)
        ext = secure_filename(receipt.filename).rsplit('.', 1)[1].lower()
        stored_name = f'{uuid.uuid4().hex}.{ext}'
        receipt.save(UPLOAD_DIR / stored_name)
        with connect() as con:
            existing = con.execute("SELECT id FROM applications WHERE guild_id=? AND status='pending'", (guild_id,)).fetchone()
            if existing:
                (UPLOAD_DIR / stored_name).unlink(missing_ok=True)
                flash('داواکارییەکا چاوەڕوانی بۆ ئەڤ سێرڤەرە هەیە. تکایە ل واتساپێ پەیوەندیێ بکە.', 'error')
                return render_template('apply.html')
            con.execute('''INSERT INTO applications(public_token,server_name,guild_id,owner_discord_id,contact_name,whatsapp,receipt_filename,created_at)
                           VALUES(?,?,?,?,?,?,?,?)''',
                        (token, server_name, guild_id, owner_id, contact, whatsapp, stored_name, now_utc().isoformat()))
        flash('داواکارییا تە گەهشت. پشتی پشکنینا پسوولەیێ، دێ پەیامەک وەرگری.', 'success')
        return redirect(url_for('application_status', token=token))
    return render_template('apply.html')


@app.route('/application/<token>')
def application_status(token):
    with connect() as con:
        item = con.execute('SELECT * FROM applications WHERE public_token=?', (token,)).fetchone()
        sub = con.execute('SELECT * FROM subscriptions WHERE application_id=?', (item['id'],)).fetchone() if item else None
    if not item:
        abort(404)
    return render_template('status.html', item=item, sub=sub, invite_url=INVITE_URL if item['status'] == 'approved' else None)


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if not ADMIN_PASSWORD_HASH:
        return render_template('setup_admin.html'), 503
    if request.method == 'POST':
        password = request.form.get('password', '')
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.clear(); session['admin_ok'] = True
            return redirect(request.args.get('next') or url_for('admin_dashboard'))
        flash('وشەی نهێنی دروست نینە.', 'error')
    return render_template('login.html')


@app.route('/admin/logout', methods=['POST'])
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    with connect() as con:
        apps = con.execute('SELECT * FROM applications ORDER BY created_at DESC LIMIT 200').fetchall()
        subs = con.execute('SELECT * FROM subscriptions ORDER BY expires_at ASC').fetchall()
    return render_template('admin.html', applications=apps, subscriptions=subs)


@app.route('/admin/receipt/<int:application_id>')
@admin_required
def admin_receipt(application_id):
    with connect() as con:
        item = con.execute('SELECT receipt_filename FROM applications WHERE id=?', (application_id,)).fetchone()
    if not item:
        abort(404)
    path = UPLOAD_DIR / item['receipt_filename']
    if not path.is_file(): abort(404)
    return send_file(path, as_attachment=False)


@app.route('/admin/review/<int:application_id>', methods=['POST'])
@admin_required
def admin_review(application_id):
    action = request.form.get('action')
    note = request.form.get('note', '').strip()[:300]
    with connect() as con:
        item = con.execute('SELECT * FROM applications WHERE id=?', (application_id,)).fetchone()
        if not item: abort(404)
        if action == 'approve':
            start = now_utc(); end = start + timedelta(days=365)
            con.execute("UPDATE applications SET status='approved', reviewed_at=?, reviewer_note=? WHERE id=?", (start.isoformat(), note, application_id))
            con.execute('''INSERT INTO subscriptions(guild_id,server_name,owner_discord_id,starts_at,expires_at,status,application_id)
                           VALUES(?,?,?,?,?,'active',?)
                           ON CONFLICT(guild_id) DO UPDATE SET server_name=excluded.server_name, owner_discord_id=excluded.owner_discord_id,
                           starts_at=excluded.starts_at, expires_at=excluded.expires_at, status='active', application_id=excluded.application_id''',
                        (item['guild_id'], item['server_name'], item['owner_discord_id'], start.isoformat(), end.isoformat(), application_id))
        elif action == 'reject':
            con.execute("UPDATE applications SET status='rejected', reviewed_at=?, reviewer_note=? WHERE id=?", (now_utc().isoformat(), note, application_id))
        else:
            abort(400)
    flash('داواکاری هاتە نوێکرن.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/subscription/<guild_id>/deactivate', methods=['POST'])
@admin_required
def deactivate(guild_id):
    with connect() as con:
        con.execute("UPDATE subscriptions SET status='inactive' WHERE guild_id=?", (guild_id,))
    flash('بەشداری هاتە ناچالاککرن.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/api/subscription/<guild_id>')
def api_subscription(guild_id):
    # Optional shared secret protects bot-to-site subscription lookups.
    expected = os.getenv('BOT_API_KEY', '')
    supplied = request.headers.get('X-Bot-API-Key', '')
    if not expected or not secrets.compare_digest(expected, supplied):
        return jsonify({'error': 'unauthorized'}), 401
    with connect() as con:
        sub = con.execute('SELECT * FROM subscriptions WHERE guild_id=?', (guild_id,)).fetchone()
    if not sub:
        return jsonify({'active': False, 'reason': 'not_found'})
    active = sub['status'] == 'active' and datetime.fromisoformat(sub['expires_at']) > now_utc()
    return jsonify({'active': active, 'server_name': sub['server_name'], 'expires_at': sub['expires_at'], 'reason': 'active' if active else 'expired_or_inactive'})


@app.errorhandler(413)
def too_large(_):
    return render_template('error.html', message='قەبارەیا پسوولەیێ نابیت ژ ٥ مێگابایت زێدەتر بیت.'), 413


@app.errorhandler(404)
def not_found(_):
    return render_template('error.html', message='ئەڤ پەڕە نەهاتە دیتن.'), 404


init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8000')), debug=False)
