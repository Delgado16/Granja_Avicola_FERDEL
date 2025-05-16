from flask import Flask, flash, render_template, redirect, url_for, request, session, make_response,Response
from cs50 import SQL
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from weasyprint import HTML
from datetime import datetime, timedelta


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
    user_data = db.execute("SELECT * FROM Usuarios WHERE ID_Usuario = ?", user_id)
    if len(user_data) == 1:
        return User(user_data[0]["ID_Usuario"], user_data[0]["NombreUsuario"])
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
        
        user = db.execute("SELECT * FROM Usuarios WHERE NombreUsuario = ?", 
                          request.form.get("username"))
        
        if len(user) != 1 or not check_password_hash(user[0]["ContrasenaHash"],
                                                      request.form.get("password")):
            flash("Nombre de usuario o contraseña incorrectos", "error")
            return render_template("login.html")
        
        user_obj = User(user[0]["ID_Usuario"], user[0]["NombreUsuario"])
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
                "INSERT INTO Usuarios (NombreUsuario, ContrasenaHash) VALUES (?, ?)", username, hash_password)
            flash("Registro exitoso. Ahora puede iniciar sesión", "success")
            return redirect("/login")
        except:
            flash("El nombre de usuario ya existe", "error")
            return render_template("register.html")

    return render_template("register.html")


#Ruta de Compra


# Registrar Compra
@app.route("/compras", methods=["GET", "POST"])
@login_required
def compras():
    if request.method == "POST":
        try:
            # Obtener datos del formulario
            fecha = request.form.get("fecha")
            proveedor_id = request.form.get("proveedor")
            id_bodega = request.form.get("id_bodega")
            id_empresa = request.form.get("id_empresa")
            n_factura = request.form.get("n_factura") or ""
            tipo_pago = int(request.form.get("tipo_pago") or 0)
            observacion = request.form.get("observacion") or ""

            # Validación por campo
            if not fecha:
                flash("La fecha es obligatoria.", "danger")
                return redirect(url_for("compras"))
            if not proveedor_id:
                flash("Debe seleccionar un proveedor.", "danger")
                return redirect(url_for("compras"))
            if not id_bodega:
                flash("Debe seleccionar una bodega.", "danger")
                return redirect(url_for("compras"))
            if not id_empresa:
                flash("Debe seleccionar una empresa.", "danger")
                return redirect(url_for("compras"))

            try:
                proveedor_id = int(proveedor_id)
                id_bodega = int(id_bodega)
                id_empresa = int(id_empresa)
            except ValueError:
                flash("Los valores de proveedor, bodega y empresa deben ser numéricos.", "danger")
                return redirect(url_for("compras"))

            # Verificar existencia de registros foráneos
            if not db.execute("SELECT 1 FROM Proveedores WHERE ID_Proveedor = ?", proveedor_id):
                flash("El proveedor seleccionado no existe.", "danger")
                return redirect(url_for("compras"))
            if not db.execute("SELECT 1 FROM Bodegas WHERE ID_Bodega = ?", id_bodega):
                flash("La bodega seleccionada no existe.", "danger")
                return redirect(url_for("compras"))
            if not db.execute("SELECT 1 FROM Empresa WHERE ID_Empresa = ?", id_empresa):
                flash("La empresa seleccionada no existe.", "danger")
                return redirect(url_for("compras"))

            # Obtener ID del tipo de movimiento 'Compra'
            tipo_mov = db.execute("SELECT ID_TipoMovimiento FROM Catalogo_Movimientos WHERE Descripcion = 'Compra'")
            if not tipo_mov:
                flash("El tipo de movimiento 'Compra' no está definido en el catálogo.", "danger")
                return redirect(url_for("compras"))
            tipo_movimiento = tipo_mov[0]["ID_TipoMovimiento"]

            # Insertar movimiento de inventario
            db.execute("""
                INSERT INTO Movimientos_Inventario (
                    ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                    ID_Proveedor, Observacion, IVA, Retencion, ID_Empresa, ID_Bodega
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            """, tipo_movimiento, n_factura, tipo_pago, fecha,
                 proveedor_id, observacion, id_empresa, id_bodega)

            movimiento_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # Procesar productos
            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]")
            descuentos = request.form.getlist("descuentos[]")

            if not productos:
                flash("Debe agregar al menos un producto a la compra.", "danger")
                return redirect(url_for("compras"))

            total_compra = 0
            for i in range(len(productos)):
                id_producto = productos[i]
                if not db.execute("SELECT 1 FROM Productos WHERE ID_Producto = ?", id_producto):
                    flash(f"El producto con ID {id_producto} no existe.", "danger")
                    return redirect(url_for("compras"))

                cantidad = float(cantidades[i] or 0)
                costo = float(costos[i] or 0)
                iva = float(ivas[i] or 0)
                descuento = float(descuentos[i] or 0)

                costo_total = (cantidad * costo) - descuento + iva
                total_compra += costo_total

                # Insertar detalle
                db.execute("""
                    INSERT INTO Detalle_Movimiento_Inventario (
                        ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                        Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, movimiento_id, tipo_movimiento, id_producto,
                     cantidad, costo, iva, descuento, costo_total, cantidad)

                # Actualizar stock general
                db.execute("""
                    UPDATE Productos
                    SET Existencias = Existencias + ?
                    WHERE ID_Producto = ?
                """, cantidad, id_producto)

                # Actualizar inventario en la bodega
                existe_en_bodega = db.execute("""
                    SELECT 1 FROM Inventario_Bodega WHERE ID_Bodega = ? AND ID_Producto = ?
                """, id_bodega, id_producto)

                if existe_en_bodega:
                    db.execute("""
                        UPDATE Inventario_Bodega
                        SET Existencias = Existencias + ?
                        WHERE ID_Bodega = ? AND ID_Producto = ?
                    """, cantidad, id_bodega, id_producto)
                else:
                    db.execute("""
                        INSERT INTO Inventario_Bodega (ID_Bodega, ID_Producto, Existencias)
                        VALUES (?, ?, ?)
                    """, id_bodega, id_producto, cantidad)

            # Registrar cuenta por pagar si es a crédito
            if tipo_pago == 1:
                fecha_vencimiento = (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=30)).date()
                db.execute("""
                    INSERT INTO Cuentas_Por_Pagar (
                        Fecha, ID_Proveedor, Num_Documento,
                        Observacion, Fecha_Vencimiento, Tipo_Movimiento,
                        Monto_Movimiento, IVA, Retencion, ID_Empresa
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                """, fecha, proveedor_id, n_factura, observacion,
                    fecha_vencimiento.strftime("%Y-%m-%d"), tipo_movimiento,
                    total_compra, id_empresa)

            flash("✅ Compra registrada correctamente.", "success")
            return redirect(url_for("gestionar_compras"))

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            flash(f"❌ Error al registrar la compra: {e}", "danger")
            return redirect(url_for("compras"))

    # GET (formulario)
    proveedores = db.execute("SELECT ID_Proveedor AS id, Nombre FROM Proveedores")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos")
    bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas")
    empresas = db.execute("SELECT ID_Empresa, Descripcion FROM Empresa")
    return render_template("compras.html", proveedores=proveedores, productos=productos, bodegas=bodegas, empresas=empresas)




# Gestionar compras
@app.route("/gestionar_compras")
def gestionar_compras():
    compras = db.execute("""
        SELECT
            mi.ID_Movimiento AS id,
            mi.Fecha AS fecha,
            p.Nombre AS proveedor,
            p.ID_Proveedor AS proveedor_id,
            mi.N_Factura AS factura,
            mi.Contado_Credito AS tipo_pago,
            mi.Observacion AS observacion,
            mi.ID_Bodega AS id_bodega,
            mi.ID_Empresa AS id_empresa,
            IFNULL(SUM(dmi.Costo_Total), 0) AS total
        FROM Movimientos_Inventario mi
        JOIN Proveedores p ON mi.ID_Proveedor = p.ID_Proveedor
        LEFT JOIN Detalle_Movimiento_Inventario dmi ON mi.ID_Movimiento = dmi.ID_Movimiento
        WHERE mi.ID_TipoMovimiento = 1
        GROUP BY mi.ID_Movimiento
        ORDER BY mi.Fecha DESC
    """)

    proveedores = db.execute("SELECT ID_Proveedor AS id, Nombre FROM Proveedores")
    empresas = db.execute("SELECT ID_Empresa, Descripcion FROM Empresa")
    bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas")

    return render_template("gestionar_compras.html",
                           compras=compras,
                           proveedores=proveedores,
                           empresas=empresas,
                           bodegas=bodegas)



# Editar compra
@app.route("/compras/<int:id>/editar", methods=["POST"])
@login_required
def editar_compra(id):
    try:
        # Obtener datos del formulario
        fecha = request.form.get("fecha")
        proveedor_id = request.form.get("proveedor")
        id_bodega = request.form.get("id_bodega")
        id_empresa = request.form.get("id_empresa")
        n_factura = request.form.get("n_factura") or ""
        tipo_pago = int(request.form.get("tipo_pago") or 0)
        observacion = request.form.get("observacion") or ""

        # Validación por campo
        if not fecha:
            flash("La fecha es obligatoria.", "danger")
            return redirect(url_for("gestionar_compras"))
        if not proveedor_id:
            flash("Debe seleccionar un proveedor.", "danger")
            return redirect(url_for("gestionar_compras"))
        if not id_bodega:
            flash("Debe seleccionar una bodega.", "danger")
            return redirect(url_for("gestionar_compras"))
        if not id_empresa:
            flash("Debe seleccionar una empresa.", "danger")
            return redirect(url_for("gestionar_compras"))

        try:
            proveedor_id = int(proveedor_id)
            id_bodega = int(id_bodega)
            id_empresa = int(id_empresa)
        except ValueError:
            flash("Los valores de proveedor, bodega y empresa deben ser numéricos.", "danger")
            return redirect(url_for("gestionar_compras"))

        # Verificar existencia de registros foráneos
        if not db.execute("SELECT 1 FROM Proveedores WHERE ID_Proveedor = ?", proveedor_id):
            flash("El proveedor seleccionado no existe.", "danger")
            return redirect(url_for("gestionar_compras"))
        if not db.execute("SELECT 1 FROM Bodegas WHERE ID_Bodega = ?", id_bodega):
            flash("La bodega seleccionada no existe.", "danger")
            return redirect(url_for("gestionar_compras"))
        if not db.execute("SELECT 1 FROM Empresa WHERE ID_Empresa = ?", id_empresa):
            flash("La empresa seleccionada no existe.", "danger")
            return redirect(url_for("gestionar_compras"))

        # Actualizar encabezado
        db.execute("""
            UPDATE Movimientos_Inventario
            SET Fecha = ?, ID_Proveedor = ?, ID_Empresa = ?, ID_Bodega = ?,
                N_Factura = ?, Contado_Credito = ?, Observacion = ?
            WHERE ID_Movimiento = ?
        """, fecha, proveedor_id, id_empresa, id_bodega,
             n_factura, tipo_pago, observacion, id)

        flash("✅ Compra actualizada correctamente.", "success")
        return redirect(url_for("gestionar_compras"))

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        flash(f"❌ Error al actualizar la compra: {e}", "danger")
        return redirect(url_for("gestionar_compras"))




# Eliminar compra
@app.route("/compras/<int:id>/eliminar")
def eliminar_compra(id):
    # 1. Borrar cuenta por pagar
    db.execute("DELETE FROM Cuentas_Por_Pagar WHERE ID_Movimiento = ?", id)
    # 2. Borrar detalle del movimiento
    db.execute("DELETE FROM Detalle_Movimiento_Inventario WHERE ID_Movimiento = ?", id)
    # 3. Borrar encabezado del movimiento
    db.execute("DELETE FROM Movimientos_Inventario WHERE ID_Movimiento = ?", id)

    flash("Compra eliminada correctamente", "success")
    return redirect(url_for("gestionar_compras"))

#fin de gestionar compras

# Ruta de ventas
@app.route("/ventas", methods=["GET", "POST"])
@login_required
def ventas():
    if request.method == "POST":
        try:
            fecha = request.form.get("fecha")
            cliente_id = request.form.get("cliente")
            tipo_pago = request.form.get("tipo_pago")
            observacion = request.form.get("observacion", "")
            id_bodega = request.form.get("id_bodega")

            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]")
            descuentos = request.form.getlist("descuentos[]")

            # === VALIDACIONES ===
            if not fecha or not cliente_id or not tipo_pago or not id_bodega:
                flash("Todos los campos obligatorios deben estar completos.", "danger")
                return redirect(url_for("ventas"))

            if not productos or len(productos) == 0:
                flash("Debe ingresar al menos un producto.", "danger")
                return redirect(url_for("ventas"))

            if len(productos) != len(cantidades) or len(productos) != len(costos):
                flash("Error en los datos de productos.", "danger")
                return redirect(url_for("ventas"))

            tipo_pago = int(tipo_pago)
            id_bodega = int(id_bodega)
            id_empresa = 1  # Ajusta según tu lógica
            total_venta = 0

            # === INICIO DE TRANSACCIÓN ===
            db.execute("BEGIN")

            # Insertar la factura
            db.execute("""
                INSERT INTO Facturacion (Fecha, IDCliente, Credito_Contado, Observacion, ID_Empresa)
                VALUES (?, ?, ?, ?, ?)
            """, fecha, cliente_id, tipo_pago, observacion, id_empresa)

            factura_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # Obtener tipo de movimiento de inventario
            tipo_mov = db.execute("SELECT ID_TipoMovimiento FROM Catalogo_Movimientos WHERE Descripcion = 'Venta'")
            if not tipo_mov:
                db.execute("ROLLBACK")
                flash("El tipo de movimiento 'Venta' no está definido.", "danger")
                return redirect(url_for("ventas"))

            tipo_movimiento = tipo_mov[0]["ID_TipoMovimiento"]

            db.execute("""
                INSERT INTO Movimientos_Inventario (
                    ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                    ID_Proveedor, Observacion, IVA, Retencion,
                    ID_Empresa, ID_Bodega
                ) VALUES (?, ?, ?, ?, NULL, ?, 0, 0, ?, ?)
            """, tipo_movimiento, f"F-{factura_id:05d}", tipo_pago, fecha, observacion, id_empresa, id_bodega)

            movimiento_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # === Insertar productos ===
            for i in range(len(productos)):
                id_producto = int(productos[i])
                cantidad = float(cantidades[i])
                costo = float(costos[i])
                iva = float(ivas[i])
                descuento = float(descuentos[i])
                total = (cantidad * costo) - descuento + iva
                total_venta += total

                # Detalle de facturación
                db.execute("""
                    INSERT INTO Detalle_Facturacion (ID_Factura, ID_Producto, Cantidad, Costo, Descuento, IVA, Total)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, factura_id, id_producto, cantidad, costo, descuento, iva, total)

                # Movimiento de inventario
                db.execute("""
                    INSERT INTO Detalle_Movimiento_Inventario (
                        ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                        Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, movimiento_id, tipo_movimiento, id_producto,
                     cantidad, costo, iva, descuento, total, -cantidad)

                # Actualizar inventario
                db.execute("""
                    UPDATE Productos SET Existencias = Existencias - ?
                    WHERE ID_Producto = ?
                """, cantidad, id_producto)

                db.execute("""
                    UPDATE Inventario_Bodega SET Existencias = Existencias - ?
                    WHERE ID_Bodega = ? AND ID_Producto = ?
                """, cantidad, id_bodega, id_producto)

            # Si es crédito, registrar cuenta por cobrar
            if tipo_pago == 1:
                fecha_vencimiento = (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=30)).date()
                db.execute("""
                    INSERT INTO Detalle_Cuentas_Por_Cobrar (
                        ID_Movimiento, Fecha, ID_Cliente, Num_Documento, Observacion,
                        Fecha_Vencimiento, Tipo_Movimiento, Monto_Movimiento,
                        IVA, Retencion, ID_Empresa
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                """, factura_id, fecha, cliente_id, f"F-{factura_id:05d}", observacion,
                     fecha_vencimiento.strftime("%Y-%m-%d"), 2, total_venta, id_empresa)

            db.execute("COMMIT")
            flash("Venta registrada correctamente.", "success")
            return redirect(url_for("gestionar_ventas"))

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            db.execute("ROLLBACK")
            flash(f"Error al registrar la venta: {e}", "danger")
            return redirect(url_for("ventas"))

    # === GET ===
    clientes = db.execute("SELECT ID_Cliente AS id, Nombre AS nombre FROM Clientes")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion AS descripcion FROM Productos")
    bodegas = db.execute("SELECT ID_Bodega AS id, Nombre AS nombre FROM Bodegas")

    last_seq = db.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", "Facturacion")
    next_id = last_seq[0]["seq"] + 1 if last_seq else 1
    n_factura = f"F-{next_id:05d}"

    return render_template("ventas.html", clientes=clientes, productos=productos, bodegas=bodegas, n_factura=n_factura)


@app.route("/gestionar_ventas", methods=["GET"])
def gestionar_ventas():
    try:
        # Obtener las ventas con datos del cliente
        ventas = db.execute("""
            SELECT f.ID_Factura, f.Fecha, c.Nombre AS Cliente, f.Credito_Contado, f.Observacion
            FROM Facturacion f
            JOIN Clientes c ON c.ID_Cliente = f.IDCliente
            ORDER BY f.Fecha DESC
        """)

        # Obtener los detalles (productos por venta)
        detalles = db.execute("""
            SELECT df.ID_Factura, p.Descripcion, df.Cantidad
            FROM Detalle_Facturacion df
            JOIN Productos p ON df.ID_Producto = p.ID_Producto
        """)

        # Agrupar productos por factura
        productos_por_venta = {}
        for d in detalles:
            productos_por_venta.setdefault(d["ID_Factura"], []).append(
                f"{d['Cantidad']} x {d['Descripcion']}"
            )

        # Preparar datos para mostrar en la plantilla
        for venta in ventas:
            venta["Productos"] = productos_por_venta.get(venta["ID_Factura"], [])
            venta["NumeroFactura"] = f"F-{venta['ID_Factura']:05d}"  # ← Formato del número de factura

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
        return redirect(url_for("home"))


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
    venta = db.execute("""
        SELECT F.ID_Factura, F.Fecha, C.Nombre AS Cliente, F.Credito_Contado, F.Observacion
        FROM Facturacion F
        JOIN Clientes C ON C.ID_Cliente = F.IDCliente
        WHERE F.ID_Factura = ?
    """, venta_id)

    if not venta:
        flash("Factura no encontrada", "danger")
        return redirect(url_for("gestionar_ventas"))

    venta = venta[0]

    detalles = db.execute("""
        SELECT P.Descripcion, D.Cantidad, D.Costo, D.IVA, D.Descuento,
               (D.Cantidad * D.Costo - D.Descuento + D.IVA) AS Costo_Total
        FROM Detalle_Facturacion D
        JOIN Productos P ON P.ID_Producto = D.ID_Producto
        WHERE D.ID_Factura = ?
    """, venta_id)

    rendered = render_template("factura_pdf.html", venta=venta, detalles=detalles)
    pdf = HTML(string=rendered).write_pdf()
    return Response(pdf, mimetype='application/pdf')



@app.route("/facturas", methods=["GET", "POST"])
def visualizar_facturas():
    cliente = request.args.get("cliente", "").strip()
    fecha = request.args.get("fecha", "").strip()

    query = """
        SELECT F.ID_Factura, F.Fecha, C.Nombre AS Cliente, F.Credito_Contado, F.Observacion
        FROM Facturacion F
        JOIN Clientes C ON C.ID_Cliente = F.IDCliente
        WHERE 1=1
    """
    params = []

    if cliente:
        query += " AND C.Nombre LIKE ?"
        params.append(f"%{cliente}%")
    if fecha:
        query += " AND F.Fecha = ?"
        params.append(fecha)

    query += " ORDER BY F.ID_Factura DESC"

    facturas = db.execute(query, *params)
    return render_template("facturas.html", facturas=facturas, cliente=cliente, fecha=fecha)

#fin de ruta de factura

#ruta de bodega e inventario
@app.route("/bodega", methods=["GET", "POST"])
def ver_bodega():
    # Alta de nueva bodega
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        ubicacion = request.form.get("ubicacion", "").strip()
        if nombre:
            db.execute("INSERT INTO Bodegas (Nombre, Ubicacion) VALUES (?, ?)", nombre, ubicacion)
            flash("Bodega agregada correctamente", "success")
            return redirect(url_for("ver_bodega"))
        else:
            flash("El nombre de la bodega es obligatorio.", "danger")

    # Obtener todas las bodegas
    bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas")

    # Crear diccionario con inventario por bodega
    inventario_por_bodega = {}
    for bodega in bodegas:
        inventario = db.execute("""
            SELECT P.COD_Producto, P.Descripcion, I.Existencias, U.Abreviatura
            FROM Inventario_Bodega I
            JOIN Productos P ON P.ID_Producto = I.ID_Producto
            LEFT JOIN Unidades_Medida U ON U.ID_Unidad = P.Unidad_Medida
            WHERE I.ID_Bodega = ?
            ORDER BY P.Descripcion
        """, bodega["ID_Bodega"])
        inventario_por_bodega[str(bodega["ID_Bodega"])] = inventario  # clave como string para seguridad

    return render_template("bodega.html", bodegas=bodegas, inventario_por_bodega=inventario_por_bodega)




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

#ruta de vehiculos
@app.route("/vehiculos", methods=["GET", "POST"])
def vehiculos():
    # Agregar nuevo vehículo
    if request.method == "POST":
        placa = request.form.get("placa", "").strip()
        marca = request.form.get("marca", "").strip()
        modelo = request.form.get("modelo", "").strip()
        año = request.form.get("año", "").strip()
        color = request.form.get("color", "").strip()
        chasis = request.form.get("chasis", "").strip()
        motor = request.form.get("motor", "").strip()
        estado = int(request.form.get("estado", 1))

        # Validación básica
        if not placa:
            flash("La placa es obligatoria.", "danger")
            return redirect(url_for("vehiculos"))

        db.execute("""
            INSERT INTO Vehiculos 
            (Placa, Marca, Modelo, Año, Color, NumeroChasis, NumeroMotor, Estado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, placa, marca, modelo, año, color, chasis, motor, estado)
        flash("Vehículo agregado correctamente.", "success")
        return redirect(url_for("vehiculos"))

    # Mostrar lista de vehículos
    vehiculos = db.execute("""
        SELECT 
            ID_Vehiculo, Placa, Marca, Modelo, Año, Color, 
            NumeroChasis, NumeroMotor, Estado
        FROM Vehiculos
        ORDER BY Placa ASC
    """)
    return render_template("vehiculos.html", vehiculos=vehiculos)



@app.route("/vehiculos/<int:id>/editar", methods=["GET", "POST"])
def editar_vehiculo(id):
    vehiculo = db.execute("SELECT * FROM Vehiculos WHERE ID_Vehiculo = ?", id)
    if not vehiculo:
        flash("Vehículo no encontrado.", "danger")
        return redirect(url_for("vehiculos"))
    vehiculo = vehiculo[0]

    if request.method == "POST":
        placa = request.form.get("placa", "").strip()
        marca = request.form.get("marca", "").strip()
        modelo = request.form.get("modelo", "").strip()
        año = request.form.get("año", "").strip()
        color = request.form.get("color", "").strip()
        chasis = request.form.get("chasis", "").strip()
        motor = request.form.get("motor", "").strip()
        estado = int(request.form.get("estado", 1))

        db.execute("""
            UPDATE Vehiculos
            SET Placa = ?, Marca = ?, Modelo = ?, Año = ?, Color = ?, 
                NumeroChasis = ?, NumeroMotor = ?, Estado = ?
            WHERE ID_Vehiculo = ?
        """, placa, marca, modelo, año, color, chasis, motor, estado, id)
        flash("Vehículo actualizado correctamente.", "success")
        return redirect(url_for("vehiculos"))

    return render_template("editar_vehiculo.html", vehiculo=vehiculo)

@app.route("/vehiculos/<int:id>/eliminar")
def eliminar_vehiculo(id):
    vehiculo = db.execute("SELECT * FROM Vehiculos WHERE ID_Vehiculo = ?", id)
    if not vehiculo:
        flash("Vehículo no encontrado.", "danger")
    else:
        db.execute("DELETE FROM Vehiculos WHERE ID_Vehiculo = ?", id)
        flash("Vehículo eliminado correctamente.", "success")
    return redirect(url_for("vehiculos"))

@app.route("/combustible", methods=["GET", "POST"])
def combustible():
    # --- REGISTRO DE GASTO (POST) ---
    if request.method == "POST":
        fecha = request.form.get("fecha")
        id_vehiculo = request.form.get("vehiculo")
        monto = request.form.get("monto")
        litros = request.form.get("litros") or None
        kilometraje = request.form.get("kilometraje") or None
        observacion = request.form.get("observacion") or ""
        id_bodega = request.form.get("bodega") or None
        id_empresa = 1  # O según tu lógica

        if not fecha or not id_vehiculo or not monto:
            flash("Fecha, vehículo y monto son obligatorios.", "danger")
            return redirect(url_for("combustible"))

        db.execute("""
            INSERT INTO Gastos_Combustible 
            (Fecha, ID_Vehiculo, Monto, Litros, Kilometraje, Observacion, ID_Bodega, ID_Empresa)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, fecha, id_vehiculo, monto, litros, kilometraje, observacion, id_bodega, id_empresa)

        flash("Gasto de combustible registrado correctamente.", "success")
        return redirect(url_for("combustible"))

    # --- FILTRO Y LISTADO DE GASTOS (GET) ---
    fecha_filtro = request.args.get("fecha")
    id_vehiculo_filtro = request.args.get("vehiculo")

    # Consulta base
    consulta = """
        SELECT g.Fecha, v.Placa, v.Marca, v.Modelo, g.Monto, g.Litros, g.Kilometraje, g.Observacion
        FROM Gastos_Combustible g
        JOIN Vehiculos v ON v.ID_Vehiculo = g.ID_Vehiculo
        WHERE 1=1
    """
    params = []
    if fecha_filtro:
        consulta += " AND g.Fecha = ?"
        params.append(fecha_filtro)
    if id_vehiculo_filtro:
        consulta += " AND g.ID_Vehiculo = ?"
        params.append(id_vehiculo_filtro)
    consulta += " ORDER BY g.Fecha DESC"

    gastos = db.execute(consulta, *params)
    vehiculos = db.execute("SELECT ID_Vehiculo, Placa, Marca, Modelo FROM Vehiculos WHERE Estado=1")
    bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas")

    return render_template(
        "combustible.html",
        vehiculos=vehiculos,
        bodegas=bodegas,
        gastos=gastos,
        fecha=fecha_filtro,
        id_vehiculo=id_vehiculo_filtro
    )


@app.route("/clientes", methods=["GET", "POST"])
def clientes():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        ruc_cedula = request.form.get("ruc_cedula", "").strip()

        if not nombre:
            flash("El nombre del cliente es obligatorio.", "danger")
            return redirect(url_for("clientes"))

        db.execute("""
            INSERT INTO Clientes (Nombre, Telefono, Direccion, RUC_CEDULA)
            VALUES (?, ?, ?, ?)
        """, nombre, telefono, direccion, ruc_cedula)
        flash("Cliente agregado correctamente.", "success")
        return redirect(url_for("clientes"))

    # Mostrar lista de clientes
    clientes = db.execute("SELECT * FROM Clientes ORDER BY Nombre")
    return render_template("clientes.html", clientes=clientes)

# Editar Cliente
@app.route("/clientes/<int:id>/editar", methods=["GET", "POST"])
def editar_cliente(id):
    cliente = db.execute("SELECT * FROM Clientes WHERE ID_Cliente = ?", id)
    if not cliente:
        flash("Cliente no encontrado.", "danger")
        return redirect(url_for("clientes"))
    cliente = cliente[0]

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        ruc_cedula = request.form.get("ruc_cedula", "").strip()

        db.execute("""
            UPDATE Clientes
            SET Nombre = ?, Telefono = ?, Direccion = ?, RUC_CEDULA = ?
            WHERE ID_Cliente = ?
        """, nombre, telefono, direccion, ruc_cedula, id)
        flash("Cliente actualizado correctamente.", "success")
        return redirect(url_for("clientes"))

    return render_template("editar_cliente.html", cliente=cliente)

# Eliminar Cliente
@app.route("/clientes/<int:id>/eliminar")
def eliminar_cliente(id):
    db.execute("DELETE FROM Clientes WHERE ID_Cliente = ?", id)
    flash("Cliente eliminado correctamente.", "success")
    return redirect(url_for("clientes"))


# Añadir Proveedor
@app.route("/proveedores", methods=["GET", "POST"])
def proveedores():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        ruc_cedula = request.form.get("ruc_cedula", "").strip()

        if not nombre:
            flash("El nombre del proveedor es obligatorio.", "danger")
            return redirect(url_for("proveedores"))

        db.execute("""
            INSERT INTO Proveedores (Nombre, Telefono, Direccion, RUC_CEDULA)
            VALUES (?, ?, ?, ?)
        """, nombre, telefono, direccion, ruc_cedula)
        flash("Proveedor agregado correctamente.", "success")
        return redirect(url_for("proveedores"))

    # Mostrar lista de proveedores
    proveedores = db.execute("SELECT * FROM Proveedores ORDER BY Nombre")
    return render_template("proveedores.html", proveedores=proveedores)

# Editar Proveedor
@app.route("/proveedores/<int:id>/editar", methods=["GET", "POST"])
def editar_proveedor(id):
    proveedor = db.execute("SELECT * FROM Proveedores WHERE ID_Proveedor = ?", id)
    if not proveedor:
        flash("Proveedor no encontrado.", "danger")
        return redirect(url_for("proveedores"))
    proveedor = proveedor[0]

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        ruc_cedula = request.form.get("ruc_cedula", "").strip()

        db.execute("""
            UPDATE Proveedores
            SET Nombre = ?, Telefono = ?, Direccion = ?, RUC_CEDULA = ?
            WHERE ID_Proveedor = ?
        """, nombre, telefono, direccion, ruc_cedula, id)
        flash("Proveedor actualizado correctamente.", "success")
        return redirect(url_for("proveedores"))

    return render_template("editar_proveedor.html", proveedor=proveedor)

# Eliminar Proveedor
@app.route("/proveedores/<int:id>/eliminar")
def eliminar_proveedor(id):
    db.execute("DELETE FROM Proveedores WHERE ID_Proveedor = ?", id)
    flash("Proveedor eliminado correctamente.", "success")
    return redirect(url_for("proveedores"))


# Añadir Empresa (generalmente se gestiona solo una, pero igual aquí)
@app.route("/empresa", methods=["GET", "POST"])
def empresa():
    if request.method == "POST":
        descripcion = request.form.get("descripcion", "").strip()
        if not descripcion:
            flash("La descripción de la empresa es obligatoria.", "danger")
            return redirect(url_for("empresa"))

        db.execute("INSERT INTO Empresa (Descripcion) VALUES (?)", descripcion)
        flash("Empresa agregada correctamente.", "success")
        return redirect(url_for("empresa"))

    empresas = db.execute("SELECT * FROM Empresa ORDER BY ID_Empresa")
    return render_template("empresa.html", empresas=empresas)

# Editar Empresa
@app.route("/empresa/<int:id>/editar", methods=["GET", "POST"])
def editar_empresa(id):
    empresa = db.execute("SELECT * FROM Empresa WHERE ID_Empresa = ?", id)
    if not empresa:
        flash("Empresa no encontrada.", "danger")
        return redirect(url_for("empresa"))
    empresa = empresa[0]

    if request.method == "POST":
        descripcion = request.form.get("descripcion", "").strip()
        db.execute("""
            UPDATE Empresa
            SET Descripcion = ?
            WHERE ID_Empresa = ?
        """, descripcion, id)
        flash("Empresa actualizada correctamente.", "success")
        return redirect(url_for("empresa"))

    return render_template("editar_empresa.html", empresa=empresa)

# Eliminar Empresa
@app.route("/empresa/<int:id>/eliminar")
def eliminar_empresa(id):
    db.execute("DELETE FROM Empresa WHERE ID_Empresa = ?", id)
    flash("Empresa eliminada correctamente.", "success")
    return redirect(url_for("empresa"))

# Listar y Agregar Producto
@app.route("/productos", methods=["GET", "POST"])
def productos():
    if request.method == "POST":
        cod = request.form.get("cod_producto", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        unidad = request.form.get("unidad")
        familia = request.form.get("familia") or None
        tipo = request.form.get("tipo") or None
        costo_promedio = float(request.form.get("costo_promedio", 0))
        precio_venta = float(request.form.get("precio_venta", 0))
        existencias = float(request.form.get("existencias", 0))
        iva = 1 if request.form.get("iva") else 0
        estado = int(request.form.get("estado", 1))
        id_empresa = 1  # Cambia según login/sesión

        if not descripcion or not unidad:
            flash("La descripción y la unidad son obligatorias.", "danger")
            return redirect(url_for("productos"))

        db.execute("""
            INSERT INTO Productos (
                COD_Producto, Descripcion, Unidad_Medida, Existencias,
                Estado, Familia, Costo_Promedio, IVA, Tipo, Precio_Venta, ID_Empresa
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, cod, descripcion, unidad, existencias, estado, familia, costo_promedio, iva, tipo, precio_venta, id_empresa)
        flash("Producto agregado correctamente.", "success")
        return redirect(url_for("productos"))

    # Listar productos y combos
    productos = db.execute("""
        SELECT P.*, U.Descripcion AS Unidad, F.Descripcion AS FamiliaDesc, T.Descripcion AS TipoDesc
        FROM Productos P
        LEFT JOIN Unidades_Medida U ON P.Unidad_Medida = U.ID_Unidad
        LEFT JOIN Familia F ON P.Familia = F.ID_Familia
        LEFT JOIN Tipo_Producto T ON P.Tipo = T.ID_TipoProducto
        ORDER BY P.Descripcion
    """)
    unidades = db.execute("SELECT ID_Unidad, Descripcion FROM Unidades_Medida")
    familias = db.execute("SELECT ID_Familia, Descripcion FROM Familia")
    tipos = db.execute("SELECT ID_TipoProducto, Descripcion FROM Tipo_Producto")
    return render_template("productos.html", productos=productos, unidades=unidades, familias=familias, tipos=tipos)



# Editar Producto
@app.route("/productos/<int:id>/editar", methods=["GET", "POST"])
def editar_producto(id):
    producto = db.execute("SELECT * FROM Productos WHERE ID_Producto = ?", id)
    if not producto:
        flash("Producto no encontrado.", "danger")
        return redirect(url_for("productos"))
    producto = producto[0]

    if request.method == "POST":
        cod = request.form.get("cod_producto", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        unidad = request.form.get("unidad")
        familia = request.form.get("familia") or None
        tipo = request.form.get("tipo") or None
        costo_promedio = float(request.form.get("costo_promedio", 0))
        precio_venta = float(request.form.get("precio_venta", 0))
        existencias = float(request.form.get("existencias", 0))
        iva = 1 if request.form.get("iva") else 0
        estado = int(request.form.get("estado", 1))
        id_empresa = 1  # Cambia según login/sesión

        db.execute("""
            UPDATE Productos SET
                COD_Producto = ?, Descripcion = ?, Unidad_Medida = ?,
                Existencias = ?, Estado = ?, Familia = ?, Costo_Promedio = ?,
                IVA = ?, Tipo = ?, Precio_Venta = ?, ID_Empresa = ?
            WHERE ID_Producto = ?
        """, cod, descripcion, unidad, existencias, estado, familia, costo_promedio, iva, tipo, precio_venta, id_empresa, id)
        flash("Producto actualizado correctamente.", "success")
        return redirect(url_for("productos"))

    unidades = db.execute("SELECT ID_Unidad, Descripcion FROM Unidades_Medida")
    familias = db.execute("SELECT ID_Familia, Descripcion FROM Familia")
    tipos = db.execute("SELECT ID_TipoProducto, Descripcion FROM Tipo_Producto")

    return render_template("editar_producto.html", producto=producto, unidades=unidades, familias=familias, tipos=tipos)


# Eliminar Producto
@app.route("/productos/<int:id>/eliminar")
def eliminar_producto(id):
    db.execute("DELETE FROM Productos WHERE ID_Producto = ?", id)
    flash("Producto eliminado correctamente.", "success")
    return redirect(url_for("productos"))

# Listar y Agregar Familia
@app.route("/familia", methods=["GET", "POST"])
def familia():
    if request.method == "POST":
        descripcion = request.form.get("descripcion", "").strip()
        if not descripcion:
            flash("La descripción es obligatoria.", "danger")
            return redirect(url_for("familia"))
        db.execute("INSERT INTO Familia (Descripcion) VALUES (?)", descripcion)
        flash("Familia agregada correctamente.", "success")
        return redirect(url_for("familia"))

    familias = db.execute("SELECT * FROM Familia ORDER BY Descripcion")
    return render_template("familia.html", familias=familias)

# Editar Familia
@app.route("/familia/<int:id>/editar", methods=["GET", "POST"])
def editar_familia(id):
    familia = db.execute("SELECT * FROM Familia WHERE ID_Familia = ?", id)
    if not familia:
        flash("Familia no encontrada.", "danger")
        return redirect(url_for("familia"))
    familia = familia[0]
    if request.method == "POST":
        descripcion = request.form.get("descripcion", "").strip()
        if not descripcion:
            flash("La descripción es obligatoria.", "danger")
            return redirect(url_for("editar_familia", id=id))
        db.execute("UPDATE Familia SET Descripcion = ? WHERE ID_Familia = ?", descripcion, id)
        flash("Familia actualizada correctamente.", "success")
        return redirect(url_for("familia"))
    return render_template("editar_familia.html", familia=familia)

# Listar y Agregar Tipo de Producto
@app.route("/tipo_producto", methods=["GET", "POST"])
def tipo_producto():
    if request.method == "POST":
        descripcion = request.form.get("descripcion", "").strip()
        if not descripcion:
            flash("La descripción es obligatoria.", "danger")
            return redirect(url_for("tipo_producto"))
        db.execute("INSERT INTO Tipo_Producto (Descripcion) VALUES (?)", descripcion)
        flash("Tipo de producto agregado correctamente.", "success")
        return redirect(url_for("tipo_producto"))

    tipos = db.execute("SELECT * FROM Tipo_Producto ORDER BY Descripcion")
    return render_template("tipo_producto.html", tipos=tipos)

# Editar Tipo de Producto
@app.route("/tipo_producto/<int:id>/editar", methods=["GET", "POST"])
def editar_tipo_producto(id):
    tipo = db.execute("SELECT * FROM Tipo_Producto WHERE ID_TipoProducto = ?", id)
    if not tipo:
        flash("Tipo de producto no encontrado.", "danger")
        return redirect(url_for("tipo_producto"))
    tipo = tipo[0]
    if request.method == "POST":
        descripcion = request.form.get("descripcion", "").strip()
        if not descripcion:
            flash("La descripción es obligatoria.", "danger")
            return redirect(url_for("editar_tipo_producto", id=id))
        db.execute("UPDATE Tipo_Producto SET Descripcion = ? WHERE ID_TipoProducto = ?", descripcion, id)
        flash("Tipo de producto actualizado correctamente.", "success")
        return redirect(url_for("tipo_producto"))
    return render_template("editar_tipo_producto.html", tipo=tipo)



if __name__ == '__main__':
    app.run(debug=True)
