import os
import re
import secrets
import time
from datetime import timedelta, date
from functools import wraps
from pathlib import Path
import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from flask_bcrypt import Bcrypt
from .db import close_db, execute, init_db, query

bcrypt = Bcrypt()


def validate_password(password):
    if not 12 <= len(password) <= 64 or len(password.encode('utf-8')) > 72:
        raise ValueError('A senha deve ter de 12 a 64 caracteres e até 72 bytes.')
    if not (re.search(r'[A-Z]', password) and re.search(r'[a-z]', password) and re.search(r'[0-9]', password) and re.search(r'[^\w\s]', password)):
        raise ValueError('Use maiúscula, minúscula, número e símbolo na senha.')


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
                      DATABASE=str(Path(app.instance_path) / 'biblioteca.db'),
                      DB_ENGINE=os.environ.get('DB_ENGINE', 'sqlite'),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
                      PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
                      MAX_CONTENT_LENGTH=64 * 1024, BCRYPT_LOG_ROUNDS=12)
    if config:
        app.config.update(config)
    if app.config['DB_ENGINE'] not in {'sqlite', 'firebird'}:
        raise ValueError('DB_ENGINE deve ser sqlite ou firebird.')
    bcrypt.init_app(app)
    app.teardown_appcontext(close_db)
    with app.app_context():
        dummy_hash = bcrypt.generate_password_hash(secrets.token_hex(16)).decode()

    def csrf_token():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def protect():
        g.user = None
        if session.get('user_id'):
            user = query('SELECT * FROM users WHERE id = ?', (session['user_id'],), one=True)
            if not user or user['blocked'] or user['session_version'] != session.get('version'):
                session.clear()
            else:
                g.user = user
        if request.method == 'POST':
            token = request.form.get('csrf_token', '')
            if not token or not secrets.compare_digest(token, session.get('csrf', '')):
                abort(400, description='Formulário expirado. Atualize a página e tente novamente.')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    def auth(admin=False):
        def decorate(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                if not g.user:
                    return redirect(url_for('login'))
                if admin and g.user['role'] != 'admin':
                    abort(403)
                return fn(*args, **kwargs)
            return wrapper
        return decorate

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            user = query('SELECT * FROM users WHERE email = ?', (email,), one=True)
            now = int(time.time())
            valid = False
            if len(password.encode('utf-8')) <= 72:
                valid = bcrypt.check_password_hash(user['password_hash'] if user else dummy_hash, password)
            if user and not user['blocked'] and user['locked_until'] <= now and valid:
                execute('UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE id = ?', (user['id'],))
                session.clear()
                session.update(user_id=user['id'], version=user['session_version'])
                session.permanent = True
                return redirect(url_for('books'))
            if user and not user['blocked'] and user['locked_until'] <= now:
                # Incremento no banco evita perder tentativas simultâneas.
                execute('UPDATE users SET failed_attempts = CASE WHEN locked_until > 0 THEN 1 ELSE failed_attempts + 1 END, locked_until = 0 WHERE id = ?', (user['id'],))
                execute('UPDATE users SET locked_until = ?, session_version = session_version + 1 WHERE id = ? AND failed_attempts >= 5 AND locked_until = 0', (now + 900, user['id']))
            flash('Não foi possível entrar. Confira os dados ou tente novamente em 15 minutos.', 'error')
        return render_template('login.html', title='Entrar')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @auth()
    def books():
        search = request.args.get('q', '').strip()[:200]
        rows = query('SELECT * FROM books WHERE LOWER(title) LIKE ? OR LOWER(author) LIKE ? ORDER BY title', ('%' + search.lower() + '%',) * 2)
        return render_template('books.html', title='Acervo de livros', books=rows, search=search)

    @app.route('/livros/novo', methods=['GET', 'POST'])
    @app.route('/livros/<int:book_id>/editar', methods=['GET', 'POST'])
    @auth(admin=True)
    def book_form(book_id=None):
        book = query('SELECT * FROM books WHERE id = ?', (book_id,), one=True) if book_id else None
        if book_id and not book:
            abort(404)
        if request.method == 'POST':
            values = request.form
            try:
                title, author = values.get('title', '').strip(), values.get('author', '').strip()
                year = int(values.get('publication_year', '0'))
                if not 1 <= len(title) <= 200 or not 1 <= len(author) <= 150 or not 1 <= year <= date.today().year + 1:
                    raise ValueError('Confira título, autor e ano de publicação.')
                duplicate = query('SELECT id FROM books WHERE LOWER(title) = ? AND id <> ?', (title.lower(), book_id or 0), one=True)
                if duplicate:
                    raise ValueError('Já existe um livro com esse título.')
                if book:
                    execute('UPDATE books SET title = ?, author = ?, publication_year = ? WHERE id = ?', (title, author, year, book_id))
                else:
                    execute('INSERT INTO books (title, author, publication_year) VALUES (?, ?, ?)', (title, author, year))
                flash('Livro salvo com sucesso.', 'success')
                return redirect(url_for('books'))
            except ValueError as error:
                flash(str(error), 'error')
                book = values
        return render_template('book_form.html', title='Editar livro' if book_id else 'Novo livro', book=book, max_year=date.today().year + 1)

    @app.post('/livros/<int:book_id>/excluir')
    @auth(admin=True)
    def book_delete(book_id):
        if not query('SELECT id FROM books WHERE id = ?', (book_id,), one=True):
            abort(404)
        execute('DELETE FROM books WHERE id = ?', (book_id,))
        flash('Livro excluído.', 'success')
        return redirect(url_for('books'))

    @app.get('/usuarios')
    @auth(admin=True)
    def users():
        return render_template('users.html', title='Gerenciar usuários', users=query('SELECT id, name, email, role, blocked, locked_until FROM users ORDER BY name'), now=int(time.time()))

    @app.route('/usuarios/novo', methods=['GET', 'POST'])
    @app.route('/usuarios/<int:user_id>/editar', methods=['GET', 'POST'])
    @auth(admin=True)
    def user_form(user_id=None):
        user = query('SELECT id, name, email, role FROM users WHERE id = ?', (user_id,), one=True) if user_id else None
        if user_id and not user:
            abort(404)
        if request.method == 'POST':
            values = request.form
            try:
                name, email, role = values.get('name', '').strip(), values.get('email', '').strip().lower(), values.get('role', 'user')
                password = values.get('password', '')
                if not 1 <= len(name) <= 100 or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or role not in ('admin', 'user'):
                    raise ValueError('Confira nome, e-mail e perfil.')
                if user_id == g.user['id'] and role != 'admin':
                    raise ValueError('Você não pode remover seu próprio perfil de administrador.')
                if query('SELECT id FROM users WHERE email = ? AND id <> ?', (email, user_id or 0), one=True):
                    raise ValueError('E-mail já cadastrado.')
                if password or not user:
                    validate_password(password)
                if user:
                    execute('UPDATE users SET name = ?, email = ?, role = ?, session_version = session_version + 1 WHERE id = ?', (name, email, role, user_id))
                    if password:
                        execute('UPDATE users SET password_hash = ? WHERE id = ?', (bcrypt.generate_password_hash(password).decode(), user_id))
                else:
                    execute('INSERT INTO users (name, email, role, password_hash) VALUES (?, ?, ?, ?)', (name, email, role, bcrypt.generate_password_hash(password).decode()))
                flash('Usuário salvo com sucesso.', 'success')
                return redirect(url_for('users'))
            except ValueError as error:
                flash(str(error), 'error')
                user = {k: values.get(k, '') for k in ('name', 'email', 'role')}
        return render_template('user_form.html', title='Editar usuário' if user_id else 'Novo usuário', user=user, editing=bool(user_id))

    @app.post('/usuarios/<int:user_id>/<action>')
    @auth(admin=True)
    def user_action(user_id, action):
        if action not in ('bloquear', 'desbloquear', 'excluir'):
            abort(404)
        if not query('SELECT id FROM users WHERE id = ?', (user_id,), one=True):
            abort(404)
        if user_id == g.user['id']:
            flash('Você não pode bloquear ou excluir sua própria conta.', 'error')
        elif action == 'excluir':
            execute('DELETE FROM users WHERE id = ?', (user_id,))
            flash('Usuário excluído.', 'success')
        else:
            execute('UPDATE users SET blocked = ?, failed_attempts = 0, locked_until = 0, session_version = session_version + 1 WHERE id = ?', (int(action == 'bloquear'), user_id))
            flash('Status do usuário atualizado.', 'success')
        return redirect(url_for('users'))

    @app.cli.command('init-db')
    def init_command():
        init_db()
        click.echo('Tabelas criadas. No Firebird execute apenas uma vez em um banco vazio.')

    @app.cli.command('create-admin')
    @click.option('--name', prompt='Nome')
    @click.option('--email', prompt='E-mail')
    @click.password_option()
    def create_admin(name, email, password):
        try:
            validate_password(password)
            email = email.strip().lower()
            if not 1 <= len(name.strip()) <= 100 or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                raise ValueError('Nome ou e-mail inválido.')
            if query('SELECT id FROM users WHERE email = ?', (email,), one=True):
                raise ValueError('E-mail já cadastrado.')
            execute('INSERT INTO users (name, email, role, password_hash) VALUES (?, ?, ?, ?)', (name.strip(), email, 'admin', bcrypt.generate_password_hash(password).decode()))
            click.echo('Administrador criado.')
        except ValueError as error:
            raise click.ClickException(str(error)) from error

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(error):
        return render_template('error.html', title=f'Erro {error.code}', error=error), error.code

    return app
