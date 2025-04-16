from flask import Flask, flash, render_template, redirect, url_for, request, session, make_response
from cs50 import SQL
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin

app = Flask(__name__)

# Configuración básica
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"  # Necesaria para sesiones y Flask-Login
Session(app)

# Configuración base de datos
db = SQL("sqlite:///Data_Base.db")

# Configuración de Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Clase Usuario para Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = str(id)  # importante que sea string para Flask-Login
        self.username = username

# Cargar usuario para mantener sesión
@login_manager.user_loader
def load_user(user_id):
    user_data = db.execute("SELECT * FROM users WHERE id = ?", user_id)
    if len(user_data) == 1:
        return User(user_data[0]["id"], user_data[0]["username"])
    return None

# Prevención de caché
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Ruta raíz
@app.route('/')
@login_required
def home():
    return render_template("index.html")

# Ruta login
@app.route('/login', methods=['GET', 'POST'])
def login():
    session.clear()
    if request.method == "POST":

        if not request.form.get("username"):
            flash("El nombre de usuario es obligatorio", "error")
            return render_template("login.html")
        elif not request.form.get("password"):
            flash("La contraseña es obligatoria", "error")
            return render_template("login.html")
        
        user = db.execute("SELECT * FROM users WHERE username = ?", 
                          request.form.get("username"))
        
        if len(user) != 1 or not check_password_hash(user[0]["hash"],
                                                      request.form.get("password")):
            flash("Nombre de usuario o contraseña incorrectos", "error")
            return render_template("login.html")
        
        user_obj = User(user[0]["id"], user[0]["username"])
        login_user(user_obj)
        flash("Inicio de sesión exitoso", "success")
        return redirect("/")
    else:
        return render_template("login.html")

# Ruta logout
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada", "success")
    return redirect("/login")

# Ruta de registro
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username or not password or not confirmation:
            flash("Todos los campos son obligatorios", "error")
            return render_template("register.html")

        if password != confirmation:
            flash("Las contraseñas no coinciden", "error")
            return render_template("register.html")

        hash_password = generate_password_hash(password)

        try:
            db.execute(
                "INSERT INTO users (username, hash) VALUES (?, ?)", username, hash_password)
            flash("Registro exitoso. Ahora puede iniciar sesión", "success")
            return redirect("/login")
        except:
            flash("El nombre de usuario ya existe", "error")
            return render_template("register.html")

    return render_template("register.html")

#Ruta de Compra
@app.route("/compras", methods=["GET", "POST"])
def compras():
    if request.method == "POST":
        try:
            # 🟡 1. Obtener y validar datos principales
            fecha = request.form.get("fecha")
            proveedor_id = request.form.get("proveedor")
            n_factura = request.form.get("n_factura") or ""
            tipo_pago = int(request.form.get("tipo_pago") or 0)
            observacion = request.form.get("observacion") or ""
            id_empresa = 1  # reemplazar según el usuario logueado
            tipo_movimiento = 1  # 1 = Compra

            if not fecha or not proveedor_id:
                flash("Fecha y proveedor son obligatorios", "warning")
                return redirect(url_for("compras"))

            # 🟡 2. Insertar movimiento (encabezado)
            db.execute("""
                INSERT INTO Movimientos_Inventario (
                    ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                    ID_Proveedor, Observacion, IVA, Retencion, ID_Empresa
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)
            """, tipo_movimiento, n_factura, tipo_pago, fecha,
                 proveedor_id, observacion, id_empresa)

            movimiento_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # 🟡 3. Obtener productos del formulario
            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]")
            descuentos = request.form.getlist("descuentos[]")

            if not productos:
                flash("Debe ingresar al menos un producto en la compra", "warning")
                return redirect(url_for("compras"))

            # 🟡 4. Insertar cada línea de producto
            for i in range(len(productos)):
                try:
                    id_producto = int(productos[i])
                    cantidad = float(cantidades[i])
                    costo = float(costos[i])
                    iva = float(ivas[i])
                    descuento = float(descuentos[i])
                    costo_total = (cantidad * costo) - descuento + iva

                    db.execute("""
                        INSERT INTO Detalle_Movimiento_Inventario (
                            ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                            Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, movimiento_id, tipo_movimiento, id_producto,
                         cantidad, costo, iva, descuento, costo_total, cantidad)

                    db.execute("""
                        UPDATE Productos
                        SET Existencias = Existencias + ?
                        WHERE ID_Producto = ?
                    """, cantidad, id_producto)

                except Exception as e:
                    flash(f"Error en producto #{i+1}: {e}", "danger")
                    return redirect(url_for("compras"))

            flash("✅ Compra registrada correctamente", "success")
            return redirect(url_for("gestionar_compras"))

        except Exception as e:
            flash(f"❌ Error general al registrar la compra: {e}", "danger")
            return redirect(url_for("compras"))

    # GET: mostrar formulario
    proveedores = db.execute("SELECT ID_Proveedor AS id, Nombre FROM Proveedores")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos")

    return render_template("compras.html", proveedores=proveedores, productos=productos)

#fin de compras

#gestionar compras
@app.route("/gestionar_compras")
def gestionar_compras():
    # Consultar todas las compras con total calculado
    compras = db.execute("""
        SELECT
            mi.ID_Movimiento AS id,
            mi.Fecha AS fecha,
            p.Nombre AS proveedor,
            mi.N_Factura AS factura,
            mi.Contado_Credito AS tipo_pago,
            mi.Observacion AS observacion,
            IFNULL(SUM(dmi.Costo_Total), 0) AS total
        FROM Movimientos_Inventario mi
        JOIN Proveedores p ON mi.ID_Proveedor = p.ID_Proveedor
        LEFT JOIN Detalle_Movimiento_Inventario dmi ON mi.ID_Movimiento = dmi.ID_Movimiento
        WHERE mi.ID_TipoMovimiento = 1
        GROUP BY mi.ID_Movimiento
        ORDER BY mi.Fecha DESC
    """)
    
    return render_template("gestionar_compras.html", compras=compras)

    #editar compra
@app.route("/compras/<int:id>/editar", methods=["GET", "POST"])
def editar_compra(id):
    if request.method == "POST":
        # Actualizar los datos del encabezado
        fecha = request.form.get("fecha")
        proveedor = request.form.get("proveedor")
        factura = request.form.get("n_factura")
        tipo_pago = request.form.get("tipo_pago")
        observacion = request.form.get("observacion")

        db.execute("""
            UPDATE Movimientos_Inventario
            SET Fecha = ?, ID_Proveedor = ?, N_Factura = ?, Contado_Credito = ?, Observacion = ?
            WHERE ID_Movimiento = ?
        """, fecha, proveedor, factura, tipo_pago, observacion, id)

        flash("Compra actualizada correctamente", "success")
        return redirect(url_for("gestionar_compras"))

    # Obtener datos actuales de la compra
    compra = db.execute("""
        SELECT mi.*, p.Nombre as proveedor_nombre
        FROM Movimientos_Inventario mi
        JOIN Proveedores p ON mi.ID_Proveedor = p.ID_Proveedor
        WHERE mi.ID_Movimiento = ?
    """, id)[0]

    proveedores = db.execute("SELECT ID_Proveedor as id, Nombre FROM Proveedores")

    return render_template("editar_compra.html", compra=compra, proveedores=proveedores)

    #fin de editar compra
    #eliminar compra
@app.route("/compras/<int:id>/eliminar")
def eliminar_compra(id):
    # Primero eliminamos los detalles relacionados
    db.execute("DELETE FROM Detalle_Movimiento_Inventario WHERE ID_Movimiento = ?", id)
    # Luego el encabezado
    db.execute("DELETE FROM Movimientos_Inventario WHERE ID_Movimiento = ?", id)

    flash("Compra eliminada correctamente", "success")
    return redirect(url_for("gestionar_compras"))


#fin de gestionar compras


if __name__ == '__main__':
    app.run(debug=True)
