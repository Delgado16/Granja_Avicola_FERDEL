from flask import Flask, flash, render_template, redirect, url_for, redirect, request,session, make_response
from cs50 import SQL
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

db = SQL("sqlite:///Data_Base.db")

app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)



@app.route('/')
def home():
    return redirect(url_for('login'))  # Redirige a la ruta '/login'

@app.route('/login')
def login():
    return render_template('login.html')  # Asegúrate de tener un archivo login.html

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirmacion = request.form.get('confirmacion')

        # Debug opcional:
        print("username:", username)
        print("password:", password)
        print("confirmacion:", confirmacion)

        if not username or not password or not confirmacion:
            flash("Todos los campos son obligatorios", "error")
            return render_template("register.html")

        if password != confirmacion:
            flash("Las contraseñas no coinciden", "error")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)

        try:
            db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, hashed_password)
            db.commit()  # Asegúrate de confirmar la transacción si usás SQLite/MySQL directo
            flash("Registro exitoso", "success")
            return redirect(url_for('login'))
        except Exception as e:
            print("Error al registrar:", e)
            flash("El nombre de usuario ya existe o hubo un error", "error")
            return render_template("register.html")

    return render_template("register.html")

if __name__ == '__main__':
    app.run(debug=True)