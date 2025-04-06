from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
import string, random, io, base64
from datetime import datetime
import qrcode
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = 'your-secret-key-123'  # Change this in production!
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///urls.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# Setup Flask-Login
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# --------------------- Models ---------------------

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

class ShortURL(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_url = db.Column(db.String(500), nullable=False)
    short_code = db.Column(db.String(10), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    clicks = db.Column(db.Integer, default=0)
    qr_code = db.Column(db.Text)

# --------------------- Utility Functions ---------------------

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def generate_short_code(length=6):
    chars = string.ascii_letters + string.digits
    while True:
        code = ''.join(random.choice(chars) for _ in range(length))
        if not ShortURL.query.filter_by(short_code=code).first():
            return code

def generate_qr_code(url, fill_color="black", back_color="white"):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill_color, back_color=back_color)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{qr_base64}"

def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

# --------------------- Routes ---------------------

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        original_url = request.form.get('original_url', '').strip()

        if not original_url:
            flash('Please enter a URL', 'danger')
            return redirect(url_for('index'))

        if not original_url.startswith(('http://', 'https://')):
            original_url = 'http://' + original_url

        if not is_valid_url(original_url):
            flash('Invalid URL format.', 'danger')
            return redirect(url_for('index'))

        existing = ShortURL.query.filter_by(original_url=original_url).first()
        if existing:
            flash('URL already shortened!', 'info')
            return render_template('index.html',
                                   short_url=f"{request.host_url}{existing.short_code}",
                                   qr_code=existing.qr_code)

        short_code = generate_short_code()
        qr_image = generate_qr_code(f"{request.host_url}{short_code}")

        new_url = ShortURL(
            original_url=original_url,
            short_code=short_code,
            qr_code=qr_image
        )
        db.session.add(new_url)
        db.session.commit()

        return render_template('index.html',
                               short_url=f"{request.host_url}{short_code}",
                               qr_code=qr_image)

    return render_template('index.html')

@app.route('/<short_code>')
def redirect_short_url(short_code):
    url_entry = ShortURL.query.filter_by(short_code=short_code).first()
    if url_entry:
        url_entry.clicks += 1
        db.session.commit()
        return redirect(url_entry.original_url)
    flash('Invalid short URL', 'danger')
    return redirect(url_for('index'))

@app.route('/stats')
@login_required
def stats():
    urls = ShortURL.query.order_by(ShortURL.created_at.desc()).all()
    return render_template('stats.html', urls=urls)

# --------------------- Auth Routes ---------------------

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Please fill out all fields', 'danger')
            return redirect(url_for('signup'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('signup'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))

        flash('Invalid username or password', 'danger')
        return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

@app.route('/qr-generator', methods=['GET', 'POST'])
@login_required
def qr_generator():
    qr_code_data = None
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        fill_color = request.form.get('fill_color', 'black')
        back_color = request.form.get('back_color', 'white')

        if not url:
            flash('Please enter a URL', 'danger')
            return redirect(url_for('qr_generator'))

        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url

        if not is_valid_url(url):
            flash('Invalid URL format.', 'danger')
            return redirect(url_for('qr_generator'))

        qr_code_data = generate_qr_code(url, fill_color, back_color)

    return render_template('qr_generator.html', qr_code_data=qr_code_data)

# --------------------- Main ---------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
