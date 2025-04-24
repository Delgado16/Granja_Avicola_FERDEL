from flask import Flask, flash, render_template, redirect, url_for, request, session, make_response
from cs50 import SQL
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from weasyprint import HTML


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
        fecha = request.form.get("fecha")
        proveedor_id = request.form.get("proveedor")
        bodega_id = int(request.form.get("bodega"))
        observacion = request.form.get("observacion", "")
        id_empresa = 1  # O según usuario logueado

        # Insertar encabezado de movimiento de compra
        db.execute("""
            INSERT INTO Movimientos_Inventario (
                ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                ID_Proveedor, Observacion, IVA, Retencion, ID_Empresa, ID_Bodega
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
        """, 1, "", 0, fecha, proveedor_id, observacion, id_empresa, bodega_id)

        movimiento_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

        productos = request.form.getlist("productos[]")
        cantidades = request.form.getlist("cantidades[]")
        costos = request.form.getlist("costos[]")

        for i in range(len(productos)):
            id_producto = int(productos[i])
            cantidad = float(cantidades[i])
            costo = float(costos[i])

            db.execute("""
                INSERT INTO Detalle_Movimiento_Inventario (
                    ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                    Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
            """, movimiento_id, 1, id_producto,
                 cantidad, costo, cantidad * costo, cantidad)

            # Actualizar inventario de la bodega seleccionada
            existe = db.execute("""
                SELECT Existencias FROM Inventario_Bodega WHERE ID_Bodega = ? AND ID_Producto = ?
            """, bodega_id, id_producto)
            if existe:
                db.execute("""
                    UPDATE Inventario_Bodega SET Existencias = Existencias + ? 
                    WHERE ID_Bodega = ? AND ID_Producto = ?
                """, cantidad, bodega_id, id_producto)
            else:
                db.execute("""
                    INSERT INTO Inventario_Bodega (ID_Bodega, ID_Producto, Existencias)
                    VALUES (?, ?, ?)
                """, bodega_id, id_producto, cantidad)

        flash("Compra registrada correctamente", "success")
        return redirect(url_for("compras"))

    # GET: cargar proveedores, productos, bodegas
    proveedores = db.execute("SELECT ID_Proveedor AS id, Nombre FROM Proveedores")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos")
    bodegas = db.execute("SELECT ID_Bodega AS id, Nombre FROM Bodegas")
    return render_template("compras.html", proveedores=proveedores, productos=productos, bodegas=bodegas)



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
            accion = request.form.get("accion", "guardar")
            fecha = request.form.get("fecha")
            cliente_id = request.form.get("cliente")
            tipo_pago = int(request.form.get("tipo_pago") or 0)
            observacion = request.form.get("observacion") or ""
            id_empresa = 1
            tipo_movimiento = 2

            # Insertar movimiento sin número aún
            db.execute("""
                INSERT INTO Movimientos_Inventario (
                    ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                    ID_Proveedor, Observacion, IVA, Retencion, ID_Empresa
                ) VALUES (?, ?, ?, ?, NULL, ?, 0, 0, ?)
            """, tipo_movimiento, "", tipo_pago, fecha, observacion, id_empresa)

            movimiento_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]
            n_factura = f"F-{movimiento_id:05d}"

            db.execute("UPDATE Movimientos_Inventario SET N_Factura = ? WHERE ID_Movimiento = ?", n_factura, movimiento_id)

            cliente_nombre = db.execute("SELECT Nombre FROM Clientes WHERE ID_Cliente = ?", cliente_id)[0]["Nombre"]
            db.execute("""
                INSERT INTO Facturacion (
                    ID_Movimiento, Fecha, IDCliente, Cliente, Credito_Contado, Observacion, ID_Empresa
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, movimiento_id, fecha, cliente_id, cliente_nombre, tipo_pago, observacion, id_empresa)

            id_factura = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]")
            descuentos = request.form.getlist("descuentos[]")

            for i in range(len(productos)):
                id_producto = int(productos[i])
                cantidad = float(cantidades[i])
                costo = float(costos[i])
                iva = float(ivas[i])
                descuento = float(descuentos[i])
                total = (cantidad * costo) - descuento + iva

                db.execute("""
                    INSERT INTO Detalle_Movimiento_Inventario (
                        ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                        Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, movimiento_id, tipo_movimiento, id_producto,
                     cantidad, costo, iva, descuento, total, cantidad)

                db.execute("""
                    INSERT INTO Detalle_Facturacion (
                        ID_Factura, ID_Producto, Cantidad, Costo, Descuento, IVA, Total
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, id_factura, id_producto, cantidad, costo, descuento, iva, total)

                db.execute("UPDATE Productos SET Existencias = Existencias - ? WHERE ID_Producto = ?", cantidad, id_producto)

            if tipo_pago == 1:
                total_venta = sum([(float(cantidades[i]) * float(costos[i])) - float(descuentos[i]) + float(ivas[i]) for i in range(len(productos))])
                fecha_vencimiento = (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=30)).date()
                db.execute("""
                    INSERT INTO Cuentas_Por_Cobrar (
                        ID_Cliente, ID_Movimiento, Monto, Fecha_Vencimiento
                    ) VALUES (?, ?, ?, ?)
                """, cliente_id, movimiento_id, total_venta, fecha_vencimiento)

            flash("✅ Venta registrada correctamente", "success")
            if accion == "imprimir":
                return redirect(url_for("generar_factura_pdf", venta_id=movimiento_id))
            return redirect(url_for("gestionar_ventas"))

        except Exception as e:
            flash(f"❌ Error al registrar venta: {e}", "danger")
            return redirect(url_for("ventas"))

    # GET
    clientes = db.execute("SELECT ID_Cliente AS id, Nombre FROM Clientes")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos")
    ultimo = db.execute("SELECT MAX(ID_Movimiento) AS max_id FROM Movimientos_Inventario")
    siguiente_id = (ultimo[0]["max_id"] or 0) + 1
    n_factura_sugerido = f"F-{siguiente_id:05d}"
    return render_template("ventas.html", clientes=clientes, productos=productos, n_factura=n_factura_sugerido)




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

# ruta de pagos
@app.route("/pagos", methods=["GET"])
def pagos():
    try:
        cuentas = db.execute("""
            SELECT cpp.ID_Movimiento, cpp.Num_Documento AS Factura,
                   p.Nombre AS Proveedor,
                   cpp.Monto_Movimiento AS Saldo,
                   cpp.Fecha_Vencimiento
            FROM Cuentas_Por_Pagar cpp
            JOIN Proveedores p ON cpp.ID_Proveedor = p.ID_Proveedor
        """)
        return render_template("pagos.html", cuentas=cuentas)
    except Exception as e:
        flash(f"❌ Error al cargar los pagos: {e}", "danger")
        return redirect(url_for("index"))

@app.route("/registrar_pago/<int:id_pago>", methods=["GET", "POST"])
def registrar_pago(id_pago):
    if request.method == "POST":
        monto = request.form["monto"]
        metodo = request.form["metodo_pago"]
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            db.execute("""
                INSERT INTO Pagos_CuentasPagar (ID_Movimiento, Fecha, Monto, ID_MetodoPago)
                VALUES (?, ?, ?, ?)
            """, id_pago, fecha, monto, metodo)

            db.execute("""
                UPDATE Cuentas_Por_Pagar
                SET Monto_Movimiento = Monto_Movimiento - ?
                WHERE ID_Movimiento = ?
            """, monto, id_pago)

            flash("✅ Pago registrado correctamente", "success")
            return redirect(url_for("pagos"))
        except Exception as e:
            flash(f"❌ Error al registrar el pago: {e}", "danger")
            return redirect(url_for("pagos"))

    else:
        factura = db.execute("""
            SELECT cpp.ID_Movimiento, cpp.Num_Documento, cpp.Monto_Movimiento,
                   p.Nombre AS Proveedor
            FROM Cuentas_Por_Pagar cpp
            JOIN Proveedores p ON cpp.ID_Proveedor = p.ID_Proveedor
            WHERE cpp.ID_Movimiento = ?
        """, id_pago)[0]

        metodos = db.execute("SELECT ID_MetodoPago, Nombre FROM Metodos_Pago")

        return render_template("registrar_pago.html", factura=factura, metodos=metodos)

@app.route("/historial_pagos_pagar/<int:id_pago>")
def historial_pagos_pagar(id_pago):
    try:
        pagos = db.execute("""
            SELECT Fecha, Monto, mp.Nombre AS Metodo
            FROM Pagos_CuentasPagar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            WHERE p.ID_Movimiento = ?
            ORDER BY Fecha DESC
        """, id_pago)

        factura = db.execute("""
            SELECT Num_Documento, Monto_Movimiento
            FROM Cuentas_Por_Pagar
            WHERE ID_Movimiento = ?
        """, id_pago)[0]

        return render_template("historial_pagos_pagar.html", pagos=pagos, factura=factura)

    except Exception as e:
        flash(f"❌ Error al cargar historial de pagos: {e}", "danger")
        return redirect(url_for("pagos"))
#fin de ruta de pagos

# Ruta Factura impresion
@app.route("/factura/pdf/<int:venta_id>")
def generar_factura_pdf(venta_id):
    # Encabezado de la factura
    venta = db.execute("""
        SELECT M.ID_Movimiento, M.Fecha, M.N_Factura, C.Nombre AS Cliente,
               M.Contado_Credito, M.Observacion
        FROM Movimientos_Inventario M
        JOIN Clientes C ON C.ID_Cliente = M.ID_Cliente
        WHERE M.ID_Movimiento = ?
    """, venta_id)

    if not venta:
        flash("Factura no encontrada", "danger")
        return redirect(url_for("gestionar_ventas"))

    venta = venta[0]

    # Detalles de productos vendidos
    detalles = db.execute("""
        SELECT P.Descripcion, D.Cantidad, D.Costo, D.IVA, D.Descuento, D.Costo_Total
        FROM Detalle_Movimiento_Inventario D
        JOIN Productos P ON P.ID_Producto = D.ID_Producto
        WHERE D.ID_Movimiento = ?
    """, venta_id)

    # Renderizar y generar PDF
    rendered = render_template("factura_pdf.html", venta=venta, detalles=detalles)
    pdf = HTML(string=rendered).write_pdf()
    return Response(pdf, mimetype='application/pdf')


@app.route("/facturas", methods=["GET", "POST"])
def visualizar_facturas():
    cliente = request.args.get("cliente", "").strip()
    fecha = request.args.get("fecha", "").strip()

    query = """
        SELECT F.ID_Movimiento, F.Fecha, F.Cliente, F.Credito_Contado, F.Observacion,
               M.N_Factura
        FROM Facturacion F
        JOIN Movimientos_Inventario M ON M.ID_Movimiento = F.ID_Movimiento
        WHERE 1=1
    """
    params = []

    if cliente:
        query += " AND F.Cliente LIKE ?"
        params.append(f"%{cliente}%")
    if fecha:
        query += " AND F.Fecha = ?"
        params.append(fecha)

    query += " ORDER BY F.ID_Movimiento DESC"

    facturas = db.execute(query, *params)
    return render_template("facturas.html", facturas=facturas, cliente=cliente, fecha=fecha)
#fin de ruta de factura

#ruta de bodega e inventario
@app.route("/bodega", methods=["GET", "POST"])
def ver_bodega():
    # Manejar el alta de nueva bodega
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        ubicacion = request.form.get("ubicacion", "").strip()
        if nombre:
            db.execute("INSERT INTO Bodegas (Nombre, Ubicacion) VALUES (?, ?)", nombre, ubicacion)
            flash("Bodega agregada correctamente", "success")
            return redirect(url_for("ver_bodega"))
        else:
            flash("El nombre de la bodega es obligatorio.", "danger")

    # Obtener bodegas para el selector
    bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas")
    # Selección de bodega
    bodega_id = request.args.get("bodega_id", type=int)
    if not bodega_id and bodegas:
        bodega_id = bodegas[0]["ID_Bodega"]  # Por defecto la primera

    # Obtener inventario de la bodega seleccionada
    inventario = []
    if bodega_id:
        inventario = db.execute("""
            SELECT P.COD_Producto, P.Descripcion, I.Existencias, U.Abreviatura
            FROM Inventario_Bodega I
            JOIN Productos P ON P.ID_Producto = I.ID_Producto
            LEFT JOIN Unidades_Medida U ON U.ID_Unidad = P.Unidad_Medida
            WHERE I.ID_Bodega = ?
            ORDER BY P.Descripcion
        """, bodega_id)

    return render_template("bodega.html", bodegas=bodegas, inventario=inventario, bodega_id=bodega_id)


@app.route("/inventario", methods=["GET", "POST"])
def gestionar_inventario():
    productos = db.execute("SELECT ID_Producto, Descripcion, Existencias FROM Productos ORDER BY Descripcion")
    if request.method == "POST":
        tipo = request.form.get("tipo")
        id_producto = int(request.form.get("producto"))
        cantidad = float(request.form.get("cantidad"))
        motivo = request.form.get("motivo", "")
        if tipo == "entrada":
            db.execute("UPDATE Productos SET Existencias = Existencias + ? WHERE ID_Producto = ?", cantidad, id_producto)
        else:
            db.execute("UPDATE Productos SET Existencias = Existencias - ? WHERE ID_Producto = ?", cantidad, id_producto)
        flash("Ajuste realizado correctamente.", "success")
        return redirect(url_for("gestionar_inventario"))
    return render_template("inventario.html", productos=productos)

@app.route("/historial_inventario")
def historial_inventario():
    productos = db.execute("SELECT ID_Producto, Descripcion FROM Productos ORDER BY Descripcion")
    tipos = db.execute("SELECT ID_TipoMovimiento, Descripcion FROM Catalogo_Movimientos ORDER BY Descripcion")

    # Filtros opcionales GET
    producto_id = request.args.get("producto", "")
    tipo_id = request.args.get("tipo", "")
    fecha = request.args.get("fecha", "")

    query = """
        SELECT MI.Fecha, P.Descripcion AS Producto, CM.Descripcion AS TipoMovimiento,
               DMI.Cantidad, DMI.Costo, MI.Observacion, MI.ID_Movimiento, DMI.ID_Producto
        FROM Detalle_Movimiento_Inventario DMI
        JOIN Movimientos_Inventario MI ON MI.ID_Movimiento = DMI.ID_Movimiento
        JOIN Productos P ON P.ID_Producto = DMI.ID_Producto
        JOIN Catalogo_Movimientos CM ON CM.ID_TipoMovimiento = MI.ID_TipoMovimiento
        WHERE 1=1
    """
    params = []

    if producto_id:
        query += " AND DMI.ID_Producto = ?"
        params.append(producto_id)
    if tipo_id:
        query += " AND MI.ID_TipoMovimiento = ?"
        params.append(tipo_id)
    if fecha:
        query += " AND MI.Fecha = ?"
        params.append(fecha)

    query += " ORDER BY MI.Fecha DESC, MI.ID_Movimiento DESC"

    movimientos = db.execute(query, *params)
    return render_template("historial_inventario.html", movimientos=movimientos, productos=productos, tipos=tipos, producto_id=producto_id, tipo_id=tipo_id, fecha=fecha)


#fin de ruta de bodega e inventario

if __name__ == '__main__':
    app.run(debug=True)
