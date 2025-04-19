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
from flask import request, redirect, url_for, flash, render_template
from datetime import datetime

# Registrar Compra
@app.route("/compras", methods=["GET", "POST"])
def compras():
    if request.method == "POST":
        try:
            # 🟡 1. Obtener datos del formulario
            fecha = request.form.get("fecha")
            proveedor_id = request.form.get("proveedor")
            n_factura = request.form.get("n_factura") or ""
            tipo_pago = int(request.form.get("tipo_pago") or 0)
            observacion = request.form.get("observacion") or ""
            id_empresa = 1  # Asignar según login
            tipo_movimiento = 1  # Compra

            if not fecha or not proveedor_id:
                flash("Fecha y proveedor son obligatorios", "warning")
                return redirect(url_for("compras"))

            # 🟡 2. Insertar encabezado de compra
            db.execute("""
                INSERT INTO Movimientos_Inventario (
                    ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                    ID_Proveedor, Observacion, IVA, Retencion, ID_Empresa
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)
            """, tipo_movimiento, n_factura, tipo_pago, fecha,
                 proveedor_id, observacion, id_empresa)

            movimiento_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # 🟡 3. Detalle de productos
            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]")
            descuentos = request.form.getlist("descuentos[]")

            if not productos:
                flash("Debe ingresar al menos un producto en la compra", "warning")
                return redirect(url_for("compras"))

            total_compra = 0

            for i in range(len(productos)):
                try:
                    id_producto = int(productos[i])
                    cantidad = float(cantidades[i])
                    costo = float(costos[i])
                    iva = float(ivas[i])
                    descuento = float(descuentos[i])
                    costo_total = (cantidad * costo) - descuento + iva
                    total_compra += costo_total

                    db.execute("""
                        INSERT INTO Detalle_Movimiento_Inventario (
                            ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                            Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, movimiento_id, tipo_movimiento, id_producto,
                         cantidad, costo, iva, descuento, costo_total, cantidad)

                    # 🟢 Actualizar inventario
                    db.execute("""
                        UPDATE Productos
                        SET Existencias = Existencias + ?
                        WHERE ID_Producto = ?
                    """, cantidad, id_producto)

                except Exception as e:
                    flash(f"Error en producto #{i+1}: {e}", "danger")
                    return redirect(url_for("compras"))

            # 🟡 4. Si es a crédito, insertar en Cuentas_Por_Pagar
            if tipo_pago == 1:  # Si es a crédito
                # Calculamos la fecha de vencimiento (por ejemplo, 30 días después de la fecha actual)
                fecha_vencimiento = (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=30)).date()

                db.execute("""
                    INSERT INTO Cuentas_Por_Pagar (
                        Fecha, ID_Proveedor, Num_Documento,
                        Observacion, Fecha_Vencimiento, Tipo_Movimiento,
                        Monto_Movimiento, IVA, Retencion, ID_Empresa
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                """, fecha, proveedor_id, n_factura, observacion,
                     vencimiento.strftime("%Y-%m-%d"), tipo_movimiento,
                     total_compra, id_empresa)

            flash("✅ Compra registrada correctamente", "success")
            return redirect(url_for("gestionar_compras"))

        except Exception as e:
            flash(f"❌ Error al registrar la compra: {e}", "danger")
            return redirect(url_for("compras"))

    # GET: formulario
    proveedores = db.execute("SELECT ID_Proveedor AS id, Nombre FROM Proveedores")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos")
    return render_template("compras.html", proveedores=proveedores, productos=productos)


# Gestionar compras
@app.route("/gestionar_compras")
def gestionar_compras():
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


# Editar compra
@app.route("/compras/<int:id>/editar", methods=["GET", "POST"])
def editar_compra(id):
    if request.method == "POST":
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

    compra = db.execute("""
        SELECT mi.*, p.Nombre as proveedor_nombre
        FROM Movimientos_Inventario mi
        JOIN Proveedores p ON mi.ID_Proveedor = p.ID_Proveedor
        WHERE mi.ID_Movimiento = ?
    """, id)[0]

    proveedores = db.execute("SELECT ID_Proveedor as id, Nombre FROM Proveedores")
    return render_template("editar_compra.html", compra=compra, proveedores=proveedores)


# Eliminar compra
@app.route("/compras/<int:id>/eliminar")
def eliminar_compra(id):
    db.execute("DELETE FROM Detalle_Movimiento_Inventario WHERE ID_Movimiento = ?", id)
    db.execute("DELETE FROM Movimientos_Inventario WHERE ID_Movimiento = ?", id)
    db.execute("DELETE FROM Cuentas_Por_Pagar WHERE Num_Documento IN ( SELECT N_Factura FROM Movimientos_Inventario WHERE ID_Movimiento = ?)", id)

    flash("Compra eliminada correctamente", "success")
    return redirect(url_for("gestionar_compras"))

#fin de gestionar compras

# Ruta de ventas
@app.route("/ventas", methods=["GET", "POST"])
def ventas():
    if request.method == "POST":
        try:
            # 🟡 1. Obtener y validar los datos principales
            fecha = request.form.get("fecha")
            cliente_id = request.form.get("cliente")  # El cliente es obligatorio para ventas
            n_factura = request.form.get("n_factura") or ""
            tipo_pago = int(request.form.get("tipo_pago") or 0)
            observacion = request.form.get("observacion") or ""
            id_empresa = 1  # reemplazar según el usuario logueado
            tipo_movimiento = 2  # 2 = Venta

            if not fecha or not cliente_id:
                flash("Fecha y cliente son obligatorios", "warning")
                return redirect(url_for("ventas"))

            # 🟡 2. Insertar movimiento (encabezado)
            db.execute("""
                INSERT INTO Movimientos_Inventario (
                    ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                    ID_Cliente, Observacion, IVA, Retencion, ID_Empresa
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)
            """, tipo_movimiento, n_factura, tipo_pago, fecha,
                 cliente_id, observacion, id_empresa)

            movimiento_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # 🟡 3. Obtener productos del formulario
            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]")
            descuentos = request.form.getlist("descuentos[]")

            if not productos:
                flash("Debe ingresar al menos un producto en la venta", "warning")
                return redirect(url_for("ventas"))

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
                        SET Existencias = Existencias - ?
                        WHERE ID_Producto = ?
                    """, cantidad, id_producto)

                except Exception as e:
                    flash(f"Error en producto #{i+1}: {e}", "danger")
                    return redirect(url_for("ventas"))

            # 🟡 5. Si es crédito, crear entrada en Cuentas_Por_Cobrar
            if tipo_pago == 1:  # Si es crédito
                total_venta = sum([(float(cantidades[i]) * float(costos[i])) - float(descuentos[i]) + float(ivas[i]) for i in range(len(productos))])
                fecha_vencimiento = (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=30)).date()

                
                # Crear la cuenta por cobrar
                db.execute("""
                    INSERT INTO Cuentas_Por_Cobrar (ID_Cliente, ID_Movimiento, Monto, Fecha_Vencimiento)
                    VALUES (?, ?, ?, ?)
                """, cliente_id, movimiento_id, total_venta, fecha_vencimiento)

            flash("✅ Venta registrada correctamente", "success")
            return redirect(url_for("gestionar_ventas"))

        except Exception as e:
            flash(f"❌ Error general al registrar la venta: {e}", "danger")
            return redirect(url_for("ventas"))

    # GET: mostrar formulario
    clientes = db.execute("SELECT ID_Cliente AS id, Nombre FROM Clientes")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos")

    return render_template("ventas.html", clientes=clientes, productos=productos)


@app.route("/gestionar_ventas", methods=["GET"])
def gestionar_ventas():
    try:
        # Obtener ventas con cliente
        ventas = db.execute("""
            SELECT f.ID_Movimiento, f.Fecha, f.Credito_Contado, f.IDCliente, c.Nombre AS Cliente
            FROM Facturacion f
            JOIN Clientes c ON f.IDCliente = c.ID_Cliente
        """)

        # Obtener productos por venta
        detalles = db.execute("""
            SELECT df.ID_Factura, p.Descripcion, df.Cantidad
            FROM Detalle_Facturacion df
            JOIN Productos p ON df.ID_Producto = p.ID_Producto
        """)

        # Agrupar productos por ID de factura
        productos_por_venta = {}
        for d in detalles:
            productos_por_venta.setdefault(d["ID_Factura"], []).append(
                f"{d['Cantidad']} x {d['Descripcion']}"
            )

        # Agregar productos a cada venta
        for venta in ventas:
            venta["Productos"] = productos_por_venta.get(venta["ID_Movimiento"], [])

        return render_template("gestionar_ventas.html", ventas=ventas)

    except Exception as e:
        flash(f"❌ Error al cargar las ventas: {e}", "danger")
        return redirect(url_for("ventas"))


@app.route("/editar_venta/<int:id_venta>", methods=["GET", "POST"])
def editar_venta(id_venta):
    if request.method == "POST":
        nuevo_cliente = request.form["cliente"]
        nueva_fecha = request.form["fecha"]
        tipo_pago = request.form["contado_credito"]

        try:
            db.execute("""
                UPDATE Facturacion
                SET IDCliente = ?, Fecha = ?, Credito_Contado = ?
                WHERE ID_Movimiento = ?
            """, nuevo_cliente, nueva_fecha, tipo_pago, id_venta)

            flash("✅ Venta actualizada correctamente", "success")
            return redirect(url_for("gestionar_ventas"))
        except Exception as e:
            flash(f"❌ Error al actualizar la venta: {e}", "danger")
            return redirect(url_for("gestionar_ventas"))

    else:
        venta = db.execute("""
            SELECT f.ID_Movimiento, f.Fecha, f.Credito_Contado, f.IDCliente, c.Nombre AS Cliente
            FROM Facturacion f
            JOIN Clientes c ON f.IDCliente = c.ID_Cliente
            WHERE f.ID_Movimiento = ?
        """, id_venta)[0]

        clientes = db.execute("SELECT ID_Cliente, Nombre FROM Clientes")

        return render_template("editar_venta.html", venta=venta, clientes=clientes)
#fin de ruta de ventas

# ruta de cobros
@app.route("/cobros", methods=["GET"])
def cobros():
    try:
        cuentas = db.execute("""
            SELECT dcc.ID_Movimiento, dcc.Num_Documento AS Factura,
                   c.Nombre AS Cliente,
                   dcc.Monto_Movimiento AS Saldo,
                   dcc.Fecha_Vencimiento
            FROM Detalle_Cuentas_Por_Cobrar dcc
            JOIN Clientes c ON dcc.ID_Cliente = c.ID_Cliente
        """)
        return render_template("cobros.html", cuentas=cuentas)
    except Exception as e:
        flash(f"❌ Error al cargar los cobros: {e}", "danger")
        return redirect(url_for("index"))
    
@app.route("/historial_pagos/<int:id_venta>")
def historial_pagos(id_venta):
    try:
        pagos = db.execute("""
            SELECT Fecha, Monto, mp.Nombre AS Metodo
            FROM Pagos_CuentasCobrar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            WHERE p.ID_Movimiento = ?
            ORDER BY Fecha DESC
        """, id_venta)

        factura = db.execute("""
            SELECT Num_Documento, Monto_Movimiento
            FROM Detalle_Cuentas_Por_Cobrar
            WHERE ID_Movimiento = ?
        """, id_venta)[0]

        return render_template("historial_pagos.html", pagos=pagos, factura=factura)
    except Exception as e:
        flash(f"❌ Error al cargar el historial: {e}", "danger")
        return redirect(url_for("cobros"))

# Cancelar manualmente una deuda (deja el saldo en 0)
@app.route("/cancelar_deuda/<int:id_venta>")
def cancelar_deuda(id_venta):
    try:
        db.execute("""
            UPDATE Detalle_Cuentas_Por_Cobrar
            SET Monto_Movimiento = 0
            WHERE ID_Movimiento = ?
        """, id_venta)

        flash("✅ Deuda marcada como cancelada manualmente.", "success")
        return redirect(url_for("cobros"))
    except Exception as e:
        flash(f"❌ Error al cancelar la deuda: {e}", "danger")
        return redirect(url_for("cobros"))

# Registrar un nuevo abono/cobro
@app.route("/registrar_cobro/<int:id_venta>", methods=["GET", "POST"])
def registrar_cobro(id_venta):
    if request.method == "POST":
        monto = request.form["monto"]
        metodo = request.form["metodo_pago"]
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Insertar nuevo pago
            db.execute("""
                INSERT INTO Pagos_CuentasCobrar (ID_Movimiento, Fecha, Monto, ID_MetodoPago)
                VALUES (?, ?, ?, ?)
            """, id_venta, fecha, monto, metodo)

            # Actualizar saldo pendiente
            db.execute("""
                UPDATE Detalle_Cuentas_Por_Cobrar
                SET Monto_Movimiento = Monto_Movimiento - ?
                WHERE ID_Movimiento = ?
            """, monto, id_venta)

            flash("✅ Cobro registrado correctamente", "success")
            return redirect(url_for("cobros"))
        except Exception as e:
            flash(f"❌ Error al registrar el cobro: {e}", "danger")
            return redirect(url_for("cobros"))

    else:
        try:
            factura = db.execute("""
                SELECT dcc.ID_Movimiento, dcc.Num_Documento, dcc.Monto_Movimiento,
                       c.Nombre AS Cliente
                FROM Detalle_Cuentas_Por_Cobrar dcc
                JOIN Clientes c ON dcc.ID_Cliente = c.ID_Cliente
                WHERE dcc.ID_Movimiento = ?
            """, id_venta)[0]

            metodos = db.execute("SELECT ID_MetodoPago, Nombre FROM Metodos_Pago")

            return render_template("registrar_cobro.html", factura=factura, metodos=metodos)

        except Exception as e:
            flash(f"❌ Error al cargar el formulario de cobro: {e}", "danger")
            return redirect(url_for("cobros"))

#fin de rutas de cobros


if __name__ == '__main__':
    app.run(debug=True)
