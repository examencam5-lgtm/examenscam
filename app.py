# app.py
# Application FLASK principale - examenscam
from flask import Flask,render_template,redirect,url_for
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
@app.route('/bac/<series>')
def bac_serie(serie):
    conn = get_connection()
    cursor = conn,cursor()
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

if __name__ == '__main__':
    app.run(debug=True)


    