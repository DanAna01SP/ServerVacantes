"""
Servidor de Vacantes — Cooperativa San Pedro
================================================================
Proyecto aparte de la página pública (Paginaweb-main).

    /admin           -> gestión de usuarios (solo rol "admin")
    /talento-humano  -> crea / edita / publica / elimina vacantes
    /api/listar      -> vacantes publicadas; la lee empleo.html del sitio público
    /uploads/...     -> imágenes de las convocatorias

Cómo correrlo con Docker (en esta carpeta):
    docker compose up -d --build
    http://localhost:5001/admin
    http://localhost:5001/talento-humano

Cómo correrlo sin Docker:
    pip install -r requirements.txt
    python app.py

El primer administrador se crea solo la primera vez que arranca el servidor,
con ADMIN_USUARIO / ADMIN_CLAVE del .env (por defecto Administrador / 123456).
Después los usuarios se administran desde /admin.
================================================================
"""
import json
import os
import re
import tempfile
import threading
import time
import uuid
from functools import wraps

from flask import Flask, request, jsonify, session, send_from_directory, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')

# En Docker se montan como volúmenes para que los datos no se pierdan
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(BASE_DIR, 'data'))
RUTA_DATOS = os.path.join(DATA_DIR, 'vacantes.json')
RUTA_USUARIOS = os.path.join(DATA_DIR, 'usuarios.json')
RUTA_UPLOADS_DISCO = os.environ.get('UPLOADS_DIR', os.path.join(BASE_DIR, 'uploads'))

RUTA_UPLOADS_WEB = '/uploads/'

# Solo se usan para crear el primer administrador
ADMIN_USUARIO = os.environ.get('ADMIN_USUARIO', 'Administrador').strip()
ADMIN_CLAVE_HASH = os.environ.get('ADMIN_CLAVE_HASH') or generate_password_hash(os.environ.get('ADMIN_CLAVE', '123456'))

SECRET_KEY = os.environ.get('SECRET_KEY') or uuid.uuid4().hex
DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
COOKIES_SEGURAS = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'

# Sitios que pueden leer las vacantes publicadas (el sitio público y, en local, Live Server).
# Ej: SITIOS_PERMITIDOS=https://sanpedroesmicoope.com.gt,http://127.0.0.1:5500
SITIOS_PERMITIDOS = {o.strip().rstrip('/') for o in os.environ.get('SITIOS_PERMITIDOS', '').split(',') if o.strip()}

ROLES = {'admin': 'Administrador', 'talento': 'Talento Humano'}
CLAVE_MINIMA = 8
# Letras, números, punto, guion y guion bajo. Se compara sin distinguir mayúsculas.
PATRON_USUARIO = re.compile(r'^[A-Za-z0-9._-]{3,50}$')

EXTENSIONES_PERMITIDAS = {'jpg', 'jpeg', 'png', 'webp'}
TAMANO_MAXIMO_MB = 8

_candado_datos = threading.Lock()


app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='')
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = TAMANO_MAXIMO_MB * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = COOKIES_SEGURAS


# ---------- Utilidades de archivos ----------
def leer_json(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, 'r', encoding='utf-8') as f:
        try:
            datos = json.load(f)
            return datos if isinstance(datos, list) else []
        except json.JSONDecodeError:
            return []

def guardar_json(ruta, datos):
    # Escritura atómica: si el proceso se corta a mitad, el archivo anterior queda intacto
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, ruta_tmp = tempfile.mkstemp(dir=DATA_DIR, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(ruta_tmp, ruta)

def leer_vacantes():
    return leer_json(RUTA_DATOS)

def guardar_vacantes(vacantes):
    guardar_json(RUTA_DATOS, vacantes)

def leer_usuarios():
    return leer_json(RUTA_USUARIOS)

def guardar_usuarios(usuarios):
    guardar_json(RUTA_USUARIOS, usuarios)

def borrar_imagen(imagen_url):
    if not imagen_url:
        return
    ruta = os.path.join(RUTA_UPLOADS_DISCO, os.path.basename(imagen_url))
    if os.path.exists(ruta):
        os.remove(ruta)

def extension_permitida(nombre_archivo):
    return '.' in nombre_archivo and nombre_archivo.rsplit('.', 1)[1].lower() in EXTENSIONES_PERMITIDAS

def inicializar_almacenamiento():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RUTA_UPLOADS_DISCO, exist_ok=True)
    if not os.path.exists(RUTA_DATOS):
        guardar_vacantes([])
    with _candado_datos:
        usuarios = leer_usuarios()
        if not any(u.get('rol') == 'admin' and u.get('activo') for u in usuarios):
            usuarios.append({
                'id': uuid.uuid4().hex,
                'usuario': ADMIN_USUARIO,
                'nombre': 'Administrador',
                'rol': 'admin',
                'activo': True,
                'claveHash': ADMIN_CLAVE_HASH,
                'creado': int(time.time()),
            })
            guardar_usuarios(usuarios)


# ---------- Sesión y permisos ----------
def usuario_publico(u):
    return {k: v for k, v in u.items() if k != 'claveHash'}

def usuario_actual():
    """Relee el usuario en cada petición: si lo desactivan o borran, pierde el acceso al instante."""
    id_usuario = session.get('usuario_id')
    if not id_usuario:
        return None
    u = next((u for u in leer_usuarios() if u.get('id') == id_usuario), None)
    return u if u and u.get('activo') else None

def requiere_rol(*roles):
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            u = usuario_actual()
            if u is None:
                return jsonify({'error': 'No autorizado. Inicia sesión de nuevo.'}), 401
            if u.get('rol') not in roles:
                return jsonify({'error': 'Tu usuario no tiene permiso para esta acción.'}), 403
            return vista(*args, **kwargs)
        return envoltura
    return decorador

def admins_activos(usuarios):
    return [u for u in usuarios if u.get('rol') == 'admin' and u.get('activo')]


@app.after_request
def permitir_sitio_publico(respuesta):
    # Solo la lista pública y las imágenes; nunca el login ni la gestión (sin cookies)
    origen = request.headers.get('Origin', '').rstrip('/')
    es_publico = request.path == '/api/listar' and request.args.get('todas') != '1'
    if origen in SITIOS_PERMITIDOS and (es_publico or request.path.startswith('/uploads/')):
        respuesta.headers['Access-Control-Allow-Origin'] = origen
        respuesta.headers['Vary'] = 'Origin'
    return respuesta


# ---------- Páginas ----------
@app.route('/')
def inicio():
    return redirect('/talento-humano')

@app.route('/admin')
def pagina_admin():
    return send_from_directory(STATIC_DIR, 'admin.html')

@app.route('/talento-humano')
def pagina_talento():
    return send_from_directory(STATIC_DIR, 'talento-humano.html')

@app.route('/uploads/<path:filename>')
def servir_imagen(filename):
    return send_from_directory(RUTA_UPLOADS_DISCO, filename)

@app.route('/salud')
def salud():
    return jsonify({'ok': True})


# ---------- API: sesión ----------
@app.route('/api/login', methods=['POST'])
def login():
    usuario = request.form.get('usuario', '').strip().lower()
    clave = request.form.get('clave', '')
    u = next((u for u in leer_usuarios() if u.get('usuario', '').lower() == usuario), None)
    if u and u.get('activo') and check_password_hash(u.get('claveHash', ''), clave):
        session.clear()
        session['usuario_id'] = u['id']
        return jsonify({'ok': True, 'usuario': usuario_publico(u)})
    return jsonify({'ok': False, 'error': 'Correo o contraseña incorrectos'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/sesion')
def sesion():
    u = usuario_actual()
    if u is None:
        return jsonify({'logueado': False})
    return jsonify({'logueado': True, 'usuario': usuario_publico(u)})


# ---------- API: usuarios (solo admin) ----------
@app.route('/api/usuarios')
@requiere_rol('admin')
def listar_usuarios():
    usuarios = sorted(leer_usuarios(), key=lambda u: u.get('creado', 0))
    return jsonify({'usuarios': [usuario_publico(u) for u in usuarios], 'roles': ROLES})

@app.route('/api/usuarios/guardar', methods=['POST'])
@requiere_rol('admin')
def guardar_usuario():
    id_usuario = request.form.get('id', '').strip()
    nombre_usuario = request.form.get('usuario', '').strip()
    nombre = request.form.get('nombre', '').strip()
    rol = request.form.get('rol', '').strip()
    activo = request.form.get('activo', '1') == '1'
    clave = request.form.get('clave', '')

    if not PATRON_USUARIO.match(nombre_usuario):
        return jsonify({'error': 'El usuario debe tener de 3 a 50 caracteres: letras, números, punto, guion o guion bajo (sin espacios)'}), 400
    if not nombre or len(nombre) > 200:
        return jsonify({'error': 'El nombre es obligatorio'}), 400
    if rol not in ROLES:
        return jsonify({'error': 'Rol no válido'}), 400
    if clave and len(clave) < CLAVE_MINIMA:
        return jsonify({'error': f'La contraseña debe tener al menos {CLAVE_MINIMA} caracteres'}), 400

    with _candado_datos:
        usuarios = leer_usuarios()
        indice = next((i for i, u in enumerate(usuarios) if id_usuario and u.get('id') == id_usuario), None)
        if id_usuario and indice is None:
            return jsonify({'error': 'No se encontró ese usuario'}), 404
        if indice is None and not clave:
            return jsonify({'error': 'La contraseña es obligatoria para un usuario nuevo'}), 400
        if any(u.get('usuario', '').lower() == nombre_usuario.lower() and u.get('id') != id_usuario for u in usuarios):
            return jsonify({'error': 'Ya existe ese nombre de usuario'}), 400

        anterior = usuarios[indice] if indice is not None else {}
        datos = {
            'id': id_usuario or uuid.uuid4().hex,
            'usuario': nombre_usuario,
            'nombre': nombre,
            'rol': rol,
            'activo': activo,
            'claveHash': generate_password_hash(clave) if clave else anterior.get('claveHash'),
            'creado': anterior.get('creado', int(time.time())),
        }

        nueva_lista = list(usuarios)
        if indice is not None:
            nueva_lista[indice] = datos
        else:
            nueva_lista.append(datos)
        if not admins_activos(nueva_lista):
            return jsonify({'error': 'Debe quedar al menos un administrador activo'}), 400

        guardar_usuarios(nueva_lista)
    return jsonify({'ok': True, 'usuario': usuario_publico(datos)})

@app.route('/api/usuarios/eliminar', methods=['POST'])
@requiere_rol('admin')
def eliminar_usuario():
    id_usuario = request.form.get('id', '').strip()
    if id_usuario == session.get('usuario_id'):
        return jsonify({'error': 'No puedes eliminar tu propio usuario'}), 400

    with _candado_datos:
        usuarios = leer_usuarios()
        if not any(u.get('id') == id_usuario for u in usuarios):
            return jsonify({'error': 'No se encontró ese usuario'}), 404
        nueva_lista = [u for u in usuarios if u.get('id') != id_usuario]
        if not admins_activos(nueva_lista):
            return jsonify({'error': 'Debe quedar al menos un administrador activo'}), 400
        guardar_usuarios(nueva_lista)
    return jsonify({'ok': True})


# ---------- API: vacantes ----------
@app.route('/api/listar')
def listar():
    todas = request.args.get('todas') == '1'
    if todas:
        u = usuario_actual()
        if u is None:
            return jsonify({'error': 'No autorizado. Inicia sesión de nuevo.'}), 401
        if u.get('rol') not in ('talento', 'admin'):
            return jsonify({'error': 'Tu usuario no tiene permiso para esta acción.'}), 403

    vacantes = leer_vacantes()
    if not todas:
        vacantes = [v for v in vacantes if v.get('activa')]

    vacantes.sort(key=lambda v: v.get('creado', 0), reverse=True)
    respuesta = jsonify({'vacantes': vacantes})
    respuesta.headers['Cache-Control'] = 'no-store'
    return respuesta

@app.route('/api/guardar', methods=['POST'])
@requiere_rol('talento', 'admin')
def guardar():
    id_vacante = request.form.get('id', '').strip()
    titulo = request.form.get('titulo', '').strip()
    agencia = request.form.get('agencia', '').strip()
    fecha_limite = request.form.get('fechaLimite', '').strip()
    activa = request.form.get('activa', '0') == '1'

    if not titulo:
        return jsonify({'error': 'El puesto es obligatorio'}), 400
    if len(titulo) > 200 or len(agencia) > 200:
        return jsonify({'error': 'El texto de puesto/agencia es demasiado largo'}), 400

    archivo = request.files.get('imagen')
    if archivo and archivo.filename and not extension_permitida(secure_filename(archivo.filename)):
        return jsonify({'error': 'Formato de imagen no permitido. Usa JPG, PNG o WEBP.'}), 400

    with _candado_datos:
        vacantes = leer_vacantes()
        indice_existente = next((i for i, v in enumerate(vacantes) if id_vacante and v.get('id') == id_vacante), None)
        if id_vacante and indice_existente is None:
            return jsonify({'error': 'No se encontró esa vacante'}), 404
        anterior = vacantes[indice_existente] if indice_existente is not None else {}

        imagen_url = anterior.get('imagenUrl', '')
        if archivo and archivo.filename:
            os.makedirs(RUTA_UPLOADS_DISCO, exist_ok=True)
            extension = secure_filename(archivo.filename).rsplit('.', 1)[1].lower()
            nombre_archivo = f"vacante_{uuid.uuid4().hex}.{extension}"
            archivo.save(os.path.join(RUTA_UPLOADS_DISCO, nombre_archivo))
            borrar_imagen(anterior.get('imagenUrl'))
            imagen_url = RUTA_UPLOADS_WEB + nombre_archivo

        if not imagen_url:
            return jsonify({'error': 'La imagen de la convocatoria es obligatoria'}), 400

        datos_vacante = {
            'id': id_vacante or uuid.uuid4().hex,
            'titulo': titulo,
            'agencia': agencia,
            'fechaLimite': fecha_limite,
            'activa': activa,
            'imagenUrl': imagen_url,
            'creado': anterior.get('creado', int(time.time())),
        }

        if indice_existente is not None:
            vacantes[indice_existente] = datos_vacante
        else:
            vacantes.append(datos_vacante)

        guardar_vacantes(vacantes)
    return jsonify({'ok': True, 'vacante': datos_vacante})

@app.route('/api/eliminar', methods=['POST'])
@requiere_rol('talento', 'admin')
def eliminar():
    id_vacante = request.form.get('id', '').strip()
    if not id_vacante:
        return jsonify({'error': 'Falta el id de la vacante'}), 400

    with _candado_datos:
        vacantes = leer_vacantes()
        eliminada = next((v for v in vacantes if v.get('id') == id_vacante), None)
        if eliminada is None:
            return jsonify({'error': 'No se encontró esa vacante'}), 404

        guardar_vacantes([v for v in vacantes if v.get('id') != id_vacante])
        borrar_imagen(eliminada.get('imagenUrl'))
    return jsonify({'ok': True})


# ---------- Errores ----------
@app.errorhandler(413)
def archivo_muy_grande(e):
    return jsonify({'error': f'La imagen supera el límite de {TAMANO_MAXIMO_MB} MB.'}), 413

@app.errorhandler(404)
def no_encontrado(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Recurso no encontrado'}), 404
    return 'Página no encontrada', 404

@app.errorhandler(500)
def error_interno(e):
    return jsonify({'error': 'Ocurrió un error interno en el servidor'}), 500


inicializar_almacenamiento()

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=DEBUG, port=int(os.environ.get('PORT', 5001)))
