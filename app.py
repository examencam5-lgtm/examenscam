# app.py
# Application FLASK principale - examenscam
from flask import Flask,render_template,redirect,url_for, request, send_from_directory
import os
from database import get_connection

app = Flask(__name__)

@app.route('/')
def index():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM annales WHERE actif = 1")
    total = cursor.fetchone()[0]
    conn.close()
    return render_template('index.html' , total=total)

@app.route('/bepc')
def bepc():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT matiere FROM annales WHERE niveau='BEPC' AND actif=1")
    matieres = [row[0] for row in cursor.fetchall()]
    conn.close()
    return render_template('niveau.html' , niveau ='BEPC' , matieres=matieres)
@app.route('/bac')
def bac():
    return render_template('bac_series.html')
@app.route('/bac/<serie>')
def bac_serie(serie):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT matiere FROM annales WHERE niveau='BAC' AND serie=? AND actif=1", (serie,))
    matieres = [row[0] for row in cursor.fetchall()]
    conn.close()
    return render_template('niveau.html', niveau='BAC', serie=serie, matieres=matieres)

@app.route('/annales/bac/<niveau>/<matiere>')
def annales(niveau,matiere):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM annales WHERE niveau=? AND matiere=? AND actif=1 ORDER BY annee DESC", (niveau,matiere))
    annales = cursor.fetchall()
    conn.close()
    return render_template('annales.html', annales=annales, niveau=niveau, matiere=matiere)

@app.route('/annales/bac/<serie>/<matiere>')
def annales_bac(serie, matiere):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM annales WHERE niveau='BAC' AND serie=? AND matiere=? AND actif=1 ORDER BY annee DESC", (serie,matiere))
    annales = cursor.fetchall()
    conn.close()
    return render_template('annales.html' , annales=annales, niveau='BAC', serie=serie , matiere=matiere)
@app.route('/probatoire')
def probatoire():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT matiere FROM annales WHERE niveau='Probatoire' AND actif=1")
    matieres = [row[0] for row in cursor.fetchall()]
    conn.close()
    return render_template('niveau.html', niveau='Probatoire', matieres=matieres)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    conn = get_connection()
    cursor = conn.cursor()
    message = None

    if request.method == 'POST':
        niveau = request.form['niveau']
        serie = request.form.get('serie') or None
        matiere = request.form['matiere']
        annee = int(request.form['annee'])
        corrige_dispo = 1 if request.form.get('corrige_dispo') else 0

        fichier = request.files['pdf']
        if fichier:
            os.makedirs('data/pdfs', exist_ok=True)
            nom_fichier = f"{niveau}_{serie or 'NA'}_{matiere}_{annee}.pdf"
            fichier.save(f"data/pdfs/{nom_fichier}")

            cursor.execute("""
                INSERT INTO annales (niveau, serie, matiere, annee, chemin_fichier, corrige_dispo)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (niveau, serie, matiere, annee, nom_fichier, corrige_dispo))
            conn.commit()
            message = f"Annale ajoutee : {nom_fichier}"

    cursor.execute("SELECT * FROM annales ORDER BY id DESC LIMIT 20")
    annales = cursor.fetchall()
    conn.close()
    return render_template('admin.html', message=message, annales=annales)

@app.route('/pdf/<path:filename>')
def serve_pdf(filename):
    return send_from_directory('data/pdfs', filename)

@app.route('/annales/<niveau>/<serie>/<matiere>')
def annales_avec_serie(niveau, serie, matiere):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM annales WHERE niveau=? AND serie=? AND matiere=? AND actif=1 ORDER BY annee DESC", (niveau, serie, matiere))
    annales = cursor.fetchall()
    conn.close()
    return render_template('annales.html', annales=annales, niveau=niveau, serie=serie, matiere=matiere)

   
    


if __name__ == '__main__':
    app.run(debug=True)


    