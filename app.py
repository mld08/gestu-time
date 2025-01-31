from datetime import datetime
from functools import wraps
import hashlib
import io
from flask import Flask, Response, flash, render_template, request, jsonify, send_file, redirect, session, url_for
import sqlite3
import os
import pandas as pd
import qrcode
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Dossier pour stocker les QR codes
QR_FOLDER = "qr_codes"
os.makedirs(QR_FOLDER, exist_ok=True)

# Fichier de la base de données SQLite
DB_FILE = "database.db"

# Login Required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id' not in session:
            flash('Veuillez vous connecter pour accéder à cette page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def create_badge(emp_id, first_name, last_name):
    """Génère un badge avec QR Code, nom et prénom"""
    qr_data = f"{emp_id},{first_name},{last_name}"
    qr = qrcode.make(qr_data)
    
    # Créer une image pour le badge
    badge_width, badge_height = 400, 600
    badge = Image.new("RGB", (badge_width, badge_height), "white")
    draw = ImageDraw.Draw(badge)

    # Charger une police (Assurez-vous d'avoir une police ttf dans le projet)
    font_path = "arial.ttf"  # Remplace par le chemin de ta police
    font_large = ImageFont.truetype(font_path, 30)
    font_small = ImageFont.truetype(font_path, 20)

    # Fonction pour centrer un texte
    def draw_centered_text(text, y_position, font):
        text_width = draw.textbbox((0, 0), text, font=font)[2]  # Largeur du texte
        x_position = (badge_width - text_width) // 2  # Calcul du centrage
        draw.text((x_position, y_position), text, fill="black", font=font)

    # Ajouter le Nom et Prénom centré
    draw_centered_text(f"{first_name} {last_name}", 50, font_large)

    # Redimensionner et placer le QR Code
    qr = qr.resize((250, 250)) # type: ignore
    badge.paste(qr, ((badge_width - 250) // 2, 150))

    # Ajouter le titre "Badge Employé" centré
    draw_centered_text("Badge Employé", 420, font_small)

    # Sauvegarder le badge
    badge_path = os.path.join(QR_FOLDER, f"{emp_id}.png")
    badge.save(badge_path)

def get_db_connection():
    """Connexion à la base SQLite"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Création des tables si elles n'existent pas
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT UNIQUE,
        first_name TEXT,
        last_name TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pointages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT,
        first_name TEXT,
        last_name TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(25),
        password VARCHAR(100)
    )
    """)
    cursor.execute("SELECT * FROM users WHERE username='admin' ")
    existing_admin = cursor.fetchone()
    if not existing_admin:
        password = hash_password("Admin@2025")
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('admin', password))

    conn.commit()
    return conn, cursor

@app.route('/')
@login_required
def index():
    """Page principale avec l'affichage des pointages"""
    conn, cursor = get_db_connection()
    # Récupérer la date sélectionnée (par défaut aujourd'hui)
    selected_date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    pointages = conn.execute("""
        SELECT employee_id, first_name, last_name, timestamp FROM pointages 
        WHERE DATE(timestamp) = ? ORDER BY timestamp DESC
    """, (selected_date,)).fetchall()
    conn.close()
    # Formater les dates pour un affichage lisible
    formatted_pointages = []
    for p in pointages:
        date_obj = datetime.strptime(p[3], "%Y-%m-%d %H:%M:%S")
        formatted_date = date_obj.strftime("%d %B %Y à %H:%M")
        formatted_pointages.append((p[0], p[1], p[2], formatted_date))
    return render_template("index.html", pointages=formatted_pointages, selected_date=selected_date)

@app.route('/employees', methods=['GET', 'POST'])
@login_required
def employees():
    """Page pour ajouter un employé et générer son QR Code"""
    conn, cursor = get_db_connection()
    
    if request.method == 'POST':
        emp_id = request.form['emp_id']
        first_name = request.form['first_name']
        last_name = request.form['last_name']

        try:
            cursor.execute("INSERT INTO employees (emp_id, first_name, last_name) VALUES (?, ?, ?)", 
                           (emp_id, first_name, last_name))
            conn.commit()

            create_badge(emp_id, first_name, last_name)
            return redirect(url_for('employees'))

            # Générer le QR Code
            """qr_data = f"{emp_id},{first_name},{last_name}"
            qr_path = os.path.join(QR_FOLDER, f"{emp_id}.png")
            qr = qrcode.make(qr_data)
            qr.save(qr_path) # type: ignore

            return redirect(url_for('employees'))"""

        except sqlite3.IntegrityError:
            return "Erreur : Cet ID employé existe déjà !", 400
        
    cursor.execute("SELECT * FROM employees")
    employees = cursor.fetchall()
    conn.close()
    return render_template("generate_qr.html", employees=employees)

@app.route('/download_qr/<emp_id>')
def download_qr(emp_id):
    """Permet de télécharger le QR Code"""
    qr_path = os.path.join(QR_FOLDER, f"{emp_id}.png")
    return send_file(qr_path, as_attachment=True)

@app.route('/download_db')
def download_db():
    """Permet de télécharger le QR Code"""
    db_path = os.path.join("database.db")
    return send_file(db_path, as_attachment=True)

@app.route('/scan', methods=['POST'])
def scan_qr():
    """Enregistrement du pointage après scan du QR Code"""
    data = request.json.get("data", "") # type: ignore

    if data:
        try:
            emp_id, first_name, last_name = data.split(',')
        except ValueError:
            return jsonify({"success": False, "message": "Format de QR Code invalide"})

        conn, cursor = get_db_connection()
        cursor.execute(
            "INSERT INTO pointages (employee_id, first_name, last_name) VALUES (?, ?, ?)", 
            (emp_id, first_name, last_name)
        )
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": f"Pointage enregistré pour {first_name} {last_name}"})
    
    return jsonify({"success": False, "message": "Aucun QR code détecté"})

@app.route('/login', methods=['GET', 'POST'])
def login():
    conn, cursor = get_db_connection()
    conn.commit()
    conn.close()
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        hashed_password = hash_password(password)
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (username, hashed_password))
        user = cursor.fetchone()
        conn.commit()
        conn.close()        
        if user:
            session['id'] = user[0] # type: ignore
            session['username'] = user[1] # type: ignore
            return redirect(url_for('index'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Vous êtes déconnecté', 'success')
    return redirect(url_for('login'))

import pandas as pd
import io
from flask import Response, request
from datetime import datetime

@app.route('/export-pointage')
@login_required
def export_pointage():
    conn, cursor = get_db_connection()
    
    # Récupérer la date sélectionnée (par défaut aujourd'hui)
    selected_date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    # Charger les données depuis la base de données dans un DataFrame
    df = pd.read_sql_query("""
        SELECT employee_id, first_name, last_name, timestamp 
        FROM pointages 
        WHERE DATE(timestamp) = ? 
        ORDER BY timestamp DESC
    """, conn, params=(selected_date,))  # Correction de l'utilisation des paramètres

    cursor.close()
    conn.close()  # Fermeture propre de la connexion

    # Vérifier si le DataFrame est vide
    if df.empty:
        return "Aucun pointage trouvé pour cette date.", 404

    # Créer un fichier Excel en mémoire
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Pointages')
    output.seek(0)  # Revenir au début du fichier mémoire

    # Retourner le fichier pour téléchargement
    return Response(
        output.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': f'attachment; filename=pointages-{selected_date}.xlsx'
        }
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
