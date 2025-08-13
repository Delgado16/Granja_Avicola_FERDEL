from flask import Flask, flash, render_template, redirect, url_for, request, session, Response, jsonify, current_app
from cs50 import SQL
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from weasyprint import HTML
from datetime import datetime, timedelta
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import traceback
import json
import logging

logging.basicConfig(level=logging.DEBUG)

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
    current_month = datetime.now().strftime('%Y-%m')
    today = datetime.now().strftime('%Y-%m-%d')

    def execute_query(query, params=None):
        result = db.execute(query, params) if params else db.execute(query)
        return result[0]['total'] if result and result[0]['total'] is not None else 0

    # 1. Total sales (today and month) - Contado solamente
    total_ventas_hoy = execute_query("""
        SELECT COALESCE(SUM(df.Total), 0) AS total 
        FROM Detalle_Facturacion df
        JOIN Facturacion f ON df.ID_Factura = f.ID_Factura
        WHERE f.Fecha = ?
        AND f.Credito_Contado = 0  -- 0 para contado, 1 para crédito
    """, [today])

    total_ventas_mes = execute_query("""
        SELECT COALESCE(SUM(df.Total), 0) AS total 
        FROM Detalle_Facturacion df
        JOIN Facturacion f ON df.ID_Factura = f.ID_Factura
        WHERE strftime('%Y-%m', f.Fecha) = ?
        AND f.Credito_Contado = 0
    """, [current_month])

    # 2. Total purchases (today and month)
    total_compras_hoy = execute_query("""
        SELECT COALESCE(SUM(dm.Costo_Total), 0) AS total
        FROM Detalle_Movimiento_Inventario dm
        JOIN Movimientos_Inventario mi ON dm.ID_Movimiento = mi.ID_Movimiento
        JOIN Catalogo_Movimientos cm ON mi.ID_TipoMovimiento = cm.ID_TipoMovimiento
        WHERE DATE(mi.Fecha) = DATE(?)
        AND LOWER(cm.Descripcion) LIKE '%compra%'
        AND mi.Contado_Credito = 0
    """, [today])

    total_compras_mes = execute_query("""
        SELECT COALESCE(SUM(dm.Costo_Total), 0) AS total
        FROM Detalle_Movimiento_Inventario dm
        JOIN Movimientos_Inventario mi ON dm.ID_Movimiento = mi.ID_Movimiento
        JOIN Catalogo_Movimientos cm ON mi.ID_TipoMovimiento = cm.ID_TipoMovimiento
        WHERE strftime('%Y-%m', mi.Fecha) = ?
        AND LOWER(cm.Descripcion) LIKE '%compra%'
        AND mi.Contado_Credito = 0
    """, [current_month])

    # 3. Inventory by warehouse (limitado a 100 registros para mejor performance)
    inventario_bodegas = db.execute("""
        SELECT b.Nombre AS bodega, p.Descripcion AS producto, ib.Existencias
        FROM Inventario_Bodega ib
        JOIN Bodegas b ON ib.ID_Bodega = b.ID_Bodega
        JOIN Productos p ON ib.ID_Producto = p.ID_Producto
        ORDER BY b.Nombre, p.Descripcion
        LIMIT 100
    """)

    # 4. Vehicle information (corregido nombre de tabla Mantenimientos)
    vehiculos = db.execute("""
        SELECT v.Placa, v.Marca, v.Modelo, v.Color, v.Estado,
               (SELECT MAX(Kilometraje) FROM Mantenimientos 
                WHERE ID_Vehiculo = v.ID_Vehiculo) AS kilometraje
        FROM Vehiculos v
        ORDER BY v.Estado DESC, v.Placa
    """)

    # 5. Top customers (últimos 30 días)
    top_clientes = db.execute("""
        SELECT c.Nombre, SUM(df.Total) AS total_comprado
        FROM Clientes c
        JOIN Facturacion f ON c.ID_Cliente = f.IDCliente
        JOIN Detalle_Facturacion df ON f.ID_Factura = df.ID_Factura
        WHERE f.Fecha >= DATE('now', '-30 days')
        GROUP BY c.ID_Cliente
        ORDER BY total_comprado DESC
        LIMIT 5
    """)

    # 6. Latest invoice (hoy solamente)
    ultima_factura = db.execute("""
        SELECT f.ID_Factura, f.Fecha, c.Nombre AS cliente, SUM(df.Total) AS total
        FROM Facturacion f
        JOIN Clientes c ON f.IDCliente = c.ID_Cliente
        JOIN Detalle_Facturacion df ON f.ID_Factura = df.ID_Factura
        WHERE f.Fecha = ?
        GROUP BY f.ID_Factura
        ORDER BY f.Fecha DESC
        LIMIT 1
    """, [today])

    # 7. Accounts receivable (usando Saldo_Pendiente)
    cuentas_cobrar = execute_query("""
        SELECT COALESCE(SUM(Saldo_Pendiente), 0) AS total
        FROM Detalle_Cuentas_Por_Cobrar
        WHERE Fecha_Vencimiento >= DATE('now')
        AND Saldo_Pendiente > 0
    """)

    cuentas_cobrar_vencidas = execute_query("""
        SELECT COALESCE(SUM(Saldo_Pendiente), 0) AS total
        FROM Detalle_Cuentas_Por_Cobrar
        WHERE Fecha_Vencimiento < DATE('now')
        AND Saldo_Pendiente > 0
    """)

    # 8. Product stock alerts (comparando con Stock_Minimo)
    productos_stock_bajo = db.execute("""
        SELECT B.Nombre AS Bodega, P.COD_Producto, P.Descripcion, 
               I.Existencias, P.Stock_Minimo, U.Abreviatura
        FROM Inventario_Bodega I
        JOIN Bodegas B ON B.ID_Bodega = I.ID_Bodega
        JOIN Productos P ON P.ID_Producto = I.ID_Producto
        LEFT JOIN Unidades_Medida U ON U.ID_Unidad = P.Unidad_Medida
        WHERE I.Existencias <= 50
        AND P.Estado = 1
        ORDER BY I.Existencias ASC
        LIMIT 20
    """)

    # 9. Upcoming vehicle maintenance (corregido nombre de tabla Mantenimientos)
    proximos_mantenimientos = db.execute("""
        SELECT m.ID_Mantenimiento, v.Placa, m.Tipo, m.Fecha, m.Descripcion
        FROM Mantenimientos m
        JOIN Vehiculos v ON m.ID_Vehiculo = v.ID_Vehiculo
        WHERE m.Fecha BETWEEN DATE('now') AND DATE('now', '+30 days')
        ORDER BY m.Fecha ASC
        LIMIT 5
    """)

    # 10. Sales by product type (último mes, solo contado)
    ventas_por_tipo = db.execute("""
        SELECT tp.Descripcion AS tipo, 
               SUM(df.Cantidad) AS cantidad, 
               COALESCE(SUM(df.Total), 0) AS total
        FROM Detalle_Facturacion df
        JOIN Productos p ON df.ID_Producto = p.ID_Producto
        JOIN Tipo_Producto tp ON p.Tipo = tp.ID_TipoProducto
        JOIN Facturacion f ON df.ID_Factura = f.ID_Factura
        WHERE strftime('%Y-%m', f.Fecha) = ?
        AND f.Credito_Contado = 0
        GROUP BY tp.ID_TipoProducto
        ORDER BY total DESC
    """, [current_month])

    return render_template("index.html",
        today=today,
        current_month=current_month,
        total_ventas_hoy=total_ventas_hoy,
        total_ventas_mes=total_ventas_mes,
        total_compras_hoy=total_compras_hoy,
        total_compras_mes=total_compras_mes,
        inventario_bodegas=inventario_bodegas,
        vehiculos=vehiculos,
        top_clientes=top_clientes,
        ultima_factura=ultima_factura[0] if ultima_factura else None,
        cuentas_cobrar=cuentas_cobrar,
        cuentas_cobrar_vencidas=cuentas_cobrar_vencidas,
        productos_stock_bajo=productos_stock_bajo,
        proximos_mantenimientos=proximos_mantenimientos,
        ventas_por_tipo=ventas_por_tipo
    )

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


#Ruta de Compra ################################################################################
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
                            ID_Movimiento,  # ¡Asegúrate de incluir este campo!
                            Fecha,
                            ID_Proveedor,
                            Num_Documento,
                            Observacion,
                            Fecha_Vencimiento,
                            Tipo_Movimiento,
                            Monto_Movimiento,
                            IVA,
                            Retencion,
                            ID_Empresa,
                            Saldo_Pendiente
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, 
                    movimiento_id,  # Este valor lo obtienes del INSERT en Movimientos_Inventario
                    fecha,
                    proveedor_id,
                    n_factura,
                    observacion,
                    fecha_vencimiento.strftime("%Y-%m-%d"),
                    tipo_movimiento,  # Asegúrate que esto sea un ID numérico
                    total_compra,
                    0,  # IVA
                    0,  # Retención
                    id_empresa,
                    total_compra  # Saldo pendiente inicial = monto total
                    )

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
    return render_template("compras.html", proveedores=proveedores, 
                           productos=productos, 
                           bodegas=bodegas, 
                           empresas=empresas)
#################################################################################################
# Gestionar compras
@app.route("/gestionar_compras")
def gestionar_compras():
    try:
        # Consulta principal de compras
        compras = db.execute("""
            SELECT
                mi.ID_Movimiento AS id,
                mi.Fecha AS fecha,
                p.Nombre AS proveedor,
                mi.N_Factura AS factura,
                mi.Contado_Credito AS tipo_pago,
                mi.Observacion AS observacion,
                b.Nombre AS bodega,
                e.Descripcion AS empresa,
                IFNULL(SUM(dmi.Costo_Total), 0) AS total
            FROM Movimientos_Inventario mi
            JOIN Proveedores p ON mi.ID_Proveedor = p.ID_Proveedor
            JOIN Bodegas b ON mi.ID_Bodega = b.ID_Bodega
            JOIN Empresa e ON mi.ID_Empresa = e.ID_Empresa
            LEFT JOIN Detalle_Movimiento_Inventario dmi ON mi.ID_Movimiento = dmi.ID_Movimiento
            WHERE mi.ID_TipoMovimiento = 1
            GROUP BY mi.ID_Movimiento
            ORDER BY mi.ID_Movimiento DESC
            LIMIT 100
        """)

        # Obtener productos de cada compra
        for compra in compras:
            compra['productos'] = db.execute("""
                SELECT 
                    dmi.ID_Producto as id_producto,
                    p.Descripcion as descripcion,
                    dmi.Cantidad as cantidad,
                    dmi.Costo_Total as costo_total
                FROM Detalle_Movimiento_Inventario dmi
                JOIN Productos p ON dmi.ID_Producto = p.ID_Producto
                WHERE dmi.ID_Movimiento = ?
                ORDER BY p.Descripcion
            """, compra['id'])

        return render_template("gestionar_compras.html", compras=compras)

    except Exception as e:
        print(f"Error en gestión de compras: {str(e)}")
        flash("Ocurrió un error al cargar las compras", "danger")
        return redirect(url_for('home'))
    
##############################################################
# Editar compra (corregido para manejar los productos del formulario)
@app.route("/editar_compra/<int:id_compra>", methods=["GET", "POST"])
@login_required
def editar_compra(id_compra):
    # Verificar si la compra existe
    compra = db.execute("""
        SELECT * FROM Movimientos_Inventario 
        WHERE ID_Movimiento = ? AND ID_TipoMovimiento = (
            SELECT ID_TipoMovimiento FROM Catalogo_Movimientos WHERE Descripcion = 'Compra'
        )
    """, id_compra)
    
    if not compra:
        flash("La compra que intentas editar no existe.", "danger")
        return redirect(url_for("gestionar_compras"))

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

            # Validación de campos obligatorios
            if not all([fecha, proveedor_id, id_bodega, id_empresa]):
                flash("Todos los campos obligatorios deben estar completos.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))

            # Convertir y validar IDs
            try:
                proveedor_id = int(proveedor_id)
                id_bodega = int(id_bodega)
                id_empresa = int(id_empresa)
            except ValueError:
                flash("Los IDs deben ser valores numéricos válidos.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))

            # Verificar existencia de registros relacionados
            if not db.execute("SELECT 1 FROM Proveedores WHERE ID_Proveedor = ?", proveedor_id):
                flash("El proveedor seleccionado no existe.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))
                
            if not db.execute("SELECT 1 FROM Bodegas WHERE ID_Bodega = ?", id_bodega):
                flash("La bodega seleccionada no existe.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))
                
            if not db.execute("SELECT 1 FROM Empresa WHERE ID_Empresa = ?", id_empresa):
                flash("La empresa seleccionada no existe.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))

            # Iniciar transacción
            db.execute("BEGIN TRANSACTION")

            # 1. Revertir cambios en inventario (stock actual)
            detalles_actuales = db.execute("""
                SELECT ID_Producto, Cantidad FROM Detalle_Movimiento_Inventario
                WHERE ID_Movimiento = ?
            """, id_compra)

            for detalle in detalles_actuales:
                # Revertir en productos generales
                db.execute("""
                    UPDATE Productos
                    SET Existencias = Existencias - ?
                    WHERE ID_Producto = ?
                """, detalle["Cantidad"], detalle["ID_Producto"])

                # Revertir en inventario de bodega
                db.execute("""
                    UPDATE Inventario_Bodega
                    SET Existencias = Existencias - ?
                    WHERE ID_Bodega = ? AND ID_Producto = ?
                """, detalle["Cantidad"], compra[0]["ID_Bodega"], detalle["ID_Producto"])

            # 2. Eliminar detalles actuales
            db.execute("DELETE FROM Detalle_Movimiento_Inventario WHERE ID_Movimiento = ?", id_compra)

            # 3. Actualizar movimiento principal
            db.execute("""
                UPDATE Movimientos_Inventario SET
                    N_Factura = ?,
                    Contado_Credito = ?,
                    Fecha = ?,
                    ID_Proveedor = ?,
                    Observacion = ?,
                    ID_Empresa = ?,
                    ID_Bodega = ?
                WHERE ID_Movimiento = ?
            """, n_factura, tipo_pago, fecha, proveedor_id, observacion, id_empresa, id_bodega, id_compra)

            # 4. Procesar nuevos productos
            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas_porcentajes = request.form.getlist("ivas[]")
            descuentos_porcentajes = request.form.getlist("descuentos[]")

            if not productos:
                db.execute("ROLLBACK")
                flash("Debe agregar al menos un producto a la compra.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))

            total_compra = 0
            for i in range(len(productos)):
                try:
                    id_producto = int(productos[i])
                    cantidad = float(cantidades[i])
                    costo = float(costos[i])
                    iva_porcentaje = float(ivas_porcentajes[i] or 0)
                    descuento_porcentaje = float(descuentos_porcentajes[i] or 0)
                except (ValueError, IndexError):
                    db.execute("ROLLBACK")
                    flash("Datos de productos inválidos.", "danger")
                    return redirect(url_for("editar_compra", id_compra=id_compra))

                # Validar porcentajes
                if not (0 <= iva_porcentaje <= 100) or not (0 <= descuento_porcentaje <= 100):
                    db.execute("ROLLBACK")
                    flash("Los porcentajes deben estar entre 0 y 100.", "danger")
                    return redirect(url_for("editar_compra", id_compra=id_compra))

                # Verificar existencia del producto
                if not db.execute("SELECT 1 FROM Productos WHERE ID_Producto = ?", id_producto):
                    db.execute("ROLLBACK")
                    flash(f"El producto con ID {id_producto} no existe.", "danger")
                    return redirect(url_for("editar_compra", id_compra=id_compra))

                # Calcular subtotal, descuento e IVA
                subtotal = cantidad * costo
                descuento_valor = subtotal * (descuento_porcentaje / 100)
                iva_valor = subtotal * (iva_porcentaje / 100)
                costo_total = subtotal - descuento_valor + iva_valor
                total_compra += costo_total

                # Insertar nuevo detalle con valores calculados
                db.execute("""
                    INSERT INTO Detalle_Movimiento_Inventario (
                        ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                        Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, id_compra, compra[0]["ID_TipoMovimiento"], id_producto,
                     cantidad, costo, iva_valor, descuento_valor, costo_total, cantidad)

                # Actualizar inventarios
                db.execute("""
                    UPDATE Productos
                    SET Existencias = Existencias + ?
                    WHERE ID_Producto = ?
                """, cantidad, id_producto)

                # Actualizar bodega
                db.execute("""
                    INSERT OR REPLACE INTO Inventario_Bodega (ID_Bodega, ID_Producto, Existencias)
                    VALUES (?, ?, COALESCE((SELECT Existencias FROM Inventario_Bodega 
                           WHERE ID_Bodega = ? AND ID_Producto = ?), 0) + ?)
                """, id_bodega, id_producto, id_bodega, id_producto, cantidad)

            # 5. Manejar cuenta por pagar (si es crédito)
            if tipo_pago == 1:  # Crédito
                fecha_vencimiento = (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=30)).strftime('%Y-%m-%d')
                
                # Verificar si ya existe una cuenta por pagar
                cuenta_existente = db.execute("""
                    SELECT ID_Cuenta FROM Cuentas_Por_Pagar 
                    WHERE Num_Documento = ? AND Tipo_Movimiento = ?
                """, n_factura, compra[0]["ID_TipoMovimiento"])

                if cuenta_existente:
                    # Actualizar cuenta existente
                    db.execute("""
                        UPDATE Cuentas_Por_Pagar SET
                            Fecha = ?,
                            ID_Proveedor = ?,
                            Observacion = ?,
                            Fecha_Vencimiento = ?,
                            Monto_Movimiento = ?,
                            ID_Empresa = ?,
                            Saldo_Pendiente = ?
                        WHERE ID_Cuenta = ?
                    """, fecha, proveedor_id, observacion, fecha_vencimiento, 
                           total_compra, id_empresa, total_compra, cuenta_existente[0]["ID_Cuenta"])
                else:
                    # Crear nueva cuenta
                    db.execute("""
                        INSERT INTO Cuentas_Por_Pagar (
                            Fecha, ID_Proveedor, Num_Documento,
                            Observacion, Fecha_Vencimiento, Tipo_Movimiento,
                            Monto_Movimiento, IVA, Retencion, ID_Empresa, Saldo_Pendiente
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                    """, fecha, proveedor_id, n_factura, observacion,
                           fecha_vencimiento, compra[0]["ID_TipoMovimiento"],
                           total_compra, id_empresa, total_compra)
            else:
                # Eliminar cuenta si ya no es a crédito
                db.execute("""
                    DELETE FROM Cuentas_Por_Pagar 
                    WHERE Num_Documento = ? AND Tipo_Movimiento = ?
                """, n_factura, compra[0]["ID_TipoMovimiento"])

            db.execute("COMMIT")
            flash("Compra actualizada correctamente.", "success")
            return redirect(url_for("gestionar_compras"))

        except Exception as e:
            db.execute("ROLLBACK")
            flash(f"Error al actualizar la compra: {str(e)}", "danger")
            return redirect(url_for("editar_compra", id_compra=id_compra))

    # GET (Mostrar formulario de edición)
    proveedores = db.execute("SELECT ID_Proveedor AS id, Nombre FROM Proveedores ORDER BY Nombre")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos WHERE Estado = 1 ORDER BY Descripcion")
    bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas ORDER BY Nombre")
    empresas = db.execute("SELECT ID_Empresa, Descripcion FROM Empresa ORDER BY Descripcion")
    
    # Obtener detalles actuales de la compra con porcentajes calculados
    detalles = db.execute("""
        SELECT d.*, p.Descripcion AS producto_desc,
               CASE WHEN (d.Cantidad * d.Costo) > 0 
                    THEN (d.IVA * 100) / (d.Cantidad * d.Costo) 
                    ELSE 0 END AS iva_porcentaje,
               CASE WHEN (d.Cantidad * d.Costo) > 0 
                    THEN (d.Descuento * 100) / (d.Cantidad * d.Costo) 
                    ELSE 0 END AS descuento_porcentaje
        FROM Detalle_Movimiento_Inventario d
        JOIN Productos p ON d.ID_Producto = p.ID_Producto
        WHERE d.ID_Movimiento = ?
    """, id_compra)

    return render_template("editar_compra.html", 
                         compra=compra[0], 
                         detalles=detalles,
                         proveedores=proveedores, 
                         productos=productos, 
                         bodegas=bodegas, 
                         empresas=empresas)

###################################################################################
# Eliminar compra
@app.route("/compras/<int:id>/eliminar")
@login_required
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
###################################################################################

# Ruta de ventas
@app.route("/stock_por_bodega/<int:id_bodega>")
@login_required
def stock_por_bodega(id_bodega):
    try:
        stock = db.execute("""
            SELECT p.ID_Producto AS id, p.Descripcion AS descripcion, 
                   COALESCE(ib.Existencias, 0) AS stock
            FROM Productos p
            LEFT JOIN Inventario_Bodega ib ON p.ID_Producto = ib.ID_Producto AND ib.ID_Bodega = ?
            WHERE p.Estado = 1
            ORDER BY p.Descripcion
        """, id_bodega)
        
        return jsonify(stock)
    except Exception as e:
        print(f"Error al obtener stock: {e}")
        return jsonify({"error": str(e)}), 500

# Nueva ruta para obtener productos por bodega (para el select)
#####################################################################################
@app.route("/ventas", methods=["GET", "POST"])
@login_required
def ventas():
    if request.method == "POST":
        # Inicializamos la variable de transacción
        transaction_active = False
        
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

            # Convertir tipos
            try:
                tipo_pago = int(tipo_pago)
                id_bodega = int(id_bodega)
            except ValueError:
                flash("Tipo de pago o bodega inválidos.", "danger")
                return redirect(url_for("ventas"))

            id_empresa = 1  # Ajusta según tu lógica
            total_venta = 0

            # === INICIO DE TRANSACCIÓN ===
            db.execute("BEGIN")
            transaction_active = True

            # Insertar la factura
            db.execute("""
                INSERT INTO Facturacion (Fecha, IDCliente, Credito_Contado, Observacion, ID_Empresa)
                VALUES (?, ?, ?, ?, ?)
            """, fecha, cliente_id, tipo_pago, observacion, id_empresa)

            factura_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # Obtener tipo de movimiento de inventario
            tipo_mov = db.execute("SELECT ID_TipoMovimiento FROM Catalogo_Movimientos WHERE Descripcion = 'Venta'")
            if not tipo_mov:
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
                try:
                    id_producto = int(productos[i])
                    cantidad = float(cantidades[i])
                    costo = float(costos[i])
                    iva = float(ivas[i])
                    descuento = float(descuentos[i])
                except ValueError:
                    if transaction_active:
                        db.execute("ROLLBACK")
                        transaction_active = False
                    flash("Datos de productos inválidos.", "danger")
                    return redirect(url_for("ventas"))

                # Validación: mínimo 50 cajillas
                if cantidad < 0:
                    nombre_prod = db.execute("SELECT Descripcion FROM Productos WHERE ID_Producto = ?", id_producto)[0]["Descripcion"]
                    if transaction_active:
                        db.execute("ROLLBACK")
                        transaction_active = False
                    flash(f"No se permite vender menos de 50 cajillas del producto '{nombre_prod}'.", "danger")
                    return redirect(url_for("ventas"))
                
                # Validación: existencia en bodega
                existencia = db.execute("""
                    SELECT Existencias FROM Inventario_Bodega
                    WHERE ID_Bodega = ? AND ID_Producto = ?
                """, id_bodega, id_producto)
                
                if not existencia or existencia[0]["Existencias"] < cantidad:
                    nombre_prod = db.execute("SELECT Descripcion FROM Productos WHERE ID_Producto = ?", id_producto)[0]["Descripcion"]
                    if transaction_active:
                        db.execute("ROLLBACK")
                        transaction_active = False
                    flash(f"No hay suficiente stock del producto '{nombre_prod}' en la bodega seleccionada.", "danger")
                    return redirect(url_for("ventas"))

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
                        IVA, Retencion, ID_Empresa, Saldo_Pendiente
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, factura_id, fecha, cliente_id, f"F-{factura_id:05d}", observacion,
                    fecha_vencimiento.strftime("%Y-%m-%d"), 2, total_venta, 0, 0, id_empresa, total_venta)

            # Confirmar la transacción si todo salió bien
            db.execute("COMMIT")
            transaction_active = False
            flash("Venta registrada correctamente.", "success")
            return redirect(url_for("ver_factura", venta_id=factura_id))

        except Exception as e:
            print(traceback.format_exc())
            if transaction_active:
                try:
                    db.execute("ROLLBACK")
                except Exception as rollback_error:
                    print(f"Error al hacer rollback: {rollback_error}")
            flash(f"Error al registrar la venta: {str(e)}", "danger")
            return redirect(url_for("ventas"))

    # === GET ===
    try:
        clientes = db.execute("SELECT ID_Cliente AS id, Nombre AS nombre FROM Clientes")
        productos = db.execute("SELECT ID_Producto AS id, Descripcion AS descripcion FROM Productos")
        bodegas = db.execute("SELECT ID_Bodega AS id, Nombre AS nombre FROM Bodegas")

        last_seq = db.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", "Facturacion")
        next_id = last_seq[0]["seq"] + 1 if last_seq else 1
        n_factura = f"F-{next_id:05d}"

        return render_template("ventas.html", clientes=clientes, productos=productos, bodegas=bodegas, n_factura=n_factura)
    except Exception as e:
        flash(f"Error al cargar datos: {str(e)}", "danger")
        return redirect(url_for("ventas"))
    
@app.route("/ventas/factura/<int:venta_id>")
@login_required
def ver_factura(venta_id):
    """Endpoint para visualizar la factura recién creada"""
    n_factura = f"F-{venta_id:05d}"
    return render_template("ver_factura.html", venta_id=venta_id, n_factura=n_factura)

@app.route("/ventas/pdf/<int:venta_id>")
@login_required
def generar_factura_venta_pdf(venta_id):
    """Nueva ruta específica para facturas de ventas (similar a tu ruta original pero con prefijo /ventas)"""
    return generar_factura_pdf(venta_id)

############################################################################
@app.route("/gestionar_ventas", methods=["GET"])
@login_required
def gestionar_ventas():
    try:
        # Obtener las ventas con datos del cliente y el total de cada factura
        # ORDENADO PRINCIPALMENTE POR NÚMERO DE FACTURA DESCENDENTE (más reciente primero)
        ventas = db.execute("""
            SELECT f.ID_Factura, f.Fecha, c.Nombre AS Cliente, 
                   f.Credito_Contado, f.Observacion,
                   (SELECT SUM(Total) FROM Detalle_Facturacion WHERE ID_Factura = f.ID_Factura) AS Total
            FROM Facturacion f
            JOIN Clientes c ON c.ID_Cliente = f.IDCliente
            ORDER BY f.ID_Factura DESC
        """)

        # Resto del código (detalles, agrupación, formateo)...
        detalles = db.execute("""
            SELECT df.ID_Factura, p.Descripcion, df.Cantidad, df.Total AS Subtotal
            FROM Detalle_Facturacion df
            JOIN Productos p ON df.ID_Producto = p.ID_Producto
        """)

        productos_por_venta = {}
        for d in detalles:
            productos_por_venta.setdefault(d["ID_Factura"], []).append(
                f"{d['Cantidad']} x {d['Descripcion']} (C$ {d['Subtotal']:,.2f})"
            )

        for venta in ventas:
            venta["Productos"] = productos_por_venta.get(venta["ID_Factura"], [])
            venta["NumeroFactura"] = f"F-{venta['ID_Factura']:05d}"
            venta["TotalFormateado"] = f"C${venta['Total']:,.2f}" if venta['Total'] else "C$ 0.00"

        return render_template("gestionar_ventas.html", ventas=ventas)

    except Exception as e:
        flash(f"❌ Error al cargar las ventas: {e}", "danger")
        return redirect(url_for("ventas"))
    
######################################################################
@app.route("/productos_por_bodega/<int:id_bodega>")
@login_required
def productos_por_bodega(id_bodega):
    try:
        productos = db.execute("""
            SELECT p.ID_Producto AS id, p.Descripcion AS descripcion
            FROM Productos p
            INNER JOIN Inventario_Bodega ib ON ib.ID_Producto = p.ID_Producto
            WHERE ib.ID_Bodega = ? AND ib.Existencias > 0
        """, id_bodega)

        return jsonify(productos)
    except Exception as e:
        print(f"Error al obtener productos por bodega: {e}")
        return jsonify([])

########################################################################

@app.route("/editar_venta/<int:venta_id>", methods=["GET", "POST"])
@login_required
def editar_venta(venta_id):
    
    if request.method == "POST":
        try:
            # Obtener datos del formulario
            fecha = request.form.get("fecha")
            cliente_id = request.form.get("cliente")
            tipo_pago = request.form.get("tipo_pago")
            observacion = request.form.get("observacion", "")
            id_bodega = request.form.get("id_bodega")

            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas_porcentajes = request.form.getlist("ivas[]")
            descuentos_porcentajes = request.form.getlist("descuentos[]")
            detalles_ids = request.form.getlist("detalles_ids[]")

            # Validaciones básicas
            if not all([fecha, cliente_id, tipo_pago, id_bodega]):
                flash("Todos los campos obligatorios deben estar completos.", "danger")
                return redirect(url_for("editar_venta", venta_id=venta_id))

            if not productos or len(productos) == 0:
                flash("Debe ingresar al menos un producto.", "danger")
                return redirect(url_for("editar_venta", venta_id=venta_id))

            if len(productos) != len(cantidades) or len(productos) != len(costos):
                flash("Error en los datos de productos.", "danger")
                return redirect(url_for("editar_venta", venta_id=venta_id))

            # Convertir tipos
            tipo_pago = int(tipo_pago)
            id_bodega = int(id_bodega)
            id_empresa = 1  # Ajustar según necesidad
            total_venta = 0

            # Iniciar transacción
            db.execute("BEGIN TRANSACTION")

            # Obtener información original
            venta_original = db.execute("""
                SELECT * FROM Facturacion WHERE ID_Factura = ?
            """, venta_id)
            
            if not venta_original:
                db.execute("ROLLBACK")
                flash("La venta que intentas editar no existe.", "danger")
                return redirect(url_for("gestionar_ventas"))

            # Obtener movimiento de inventario
            movimiento_original = db.execute("""
                SELECT * FROM Movimientos_Inventario 
                WHERE N_Factura = ? AND ID_Empresa = ?
            """, f"F-{venta_id:05d}", id_empresa)
            
            if not movimiento_original:
                db.execute("ROLLBACK")
                flash("No se encontró el movimiento de inventario asociado.", "danger")
                return redirect(url_for("gestionar_ventas"))

            movimiento_id = movimiento_original[0]["ID_Movimiento"]

            # 1. Revertir cambios originales
            detalles_originales = db.execute("""
                SELECT * FROM Detalle_Facturacion WHERE ID_Factura = ?
            """, venta_id)

            for detalle in detalles_originales:
                db.execute("""
                    UPDATE Productos SET Existencias = Existencias + ?
                    WHERE ID_Producto = ?
                """, detalle["Cantidad"], detalle["ID_Producto"])
                
                db.execute("""
                    UPDATE Inventario_Bodega SET Existencias = Existencias + ?
                    WHERE ID_Bodega = ? AND ID_Producto = ?
                """, detalle["Cantidad"], id_bodega, detalle["ID_Producto"])

            # Eliminar registros originales
            db.execute("DELETE FROM Detalle_Facturacion WHERE ID_Factura = ?", venta_id)
            db.execute("DELETE FROM Detalle_Movimiento_Inventario WHERE ID_Movimiento = ?", movimiento_id)
            
            # Eliminar cuenta por cobrar si era crédito
            if venta_original[0]["Credito_Contado"] == 1:
                db.execute("""
                    DELETE FROM Detalle_Cuentas_Por_Cobrar 
                    WHERE ID_Movimiento = ? AND Tipo_Movimiento = 2
                """, venta_id)

            # 2. Actualizar factura principal
            db.execute("""
                UPDATE Facturacion 
                SET Fecha = ?, IDCliente = ?, Credito_Contado = ?, Observacion = ?
                WHERE ID_Factura = ?
            """, fecha, cliente_id, tipo_pago, observacion, venta_id)

            # 3. Actualizar movimiento de inventario
            db.execute("""
                UPDATE Movimientos_Inventario
                SET Fecha = ?, Contado_Credito = ?, Observacion = ?, ID_Bodega = ?
                WHERE ID_Movimiento = ?
            """, fecha, tipo_pago, observacion, id_bodega, movimiento_id)

            # 4. Insertar nuevos productos
            for i in range(len(productos)):
                id_producto = int(productos[i])
                cantidad = float(cantidades[i])
                costo = float(costos[i])
                iva_porcentaje = float(ivas_porcentajes[i])
                descuento_porcentaje = float(descuentos_porcentajes[i])

                # Validaciones
                if not (0 <= descuento_porcentaje <= 100) or not (0 <= iva_porcentaje <= 100):
                    db.execute("ROLLBACK")
                    flash("Los porcentajes deben estar entre 0 y 100.", "danger")
                    return redirect(url_for("editar_venta", venta_id=venta_id))
                
                # Verificar existencias
                existencia = db.execute("""
                    SELECT Existencias FROM Inventario_Bodega
                    WHERE ID_Bodega = ? AND ID_Producto = ?
                """, id_bodega, id_producto)
                
                if not existencia or existencia[0]["Existencias"] < cantidad:
                    producto_info = db.execute("SELECT Descripcion FROM Productos WHERE ID_Producto = ?", id_producto)
                    nombre_prod = producto_info[0]["Descripcion"] if producto_info else "producto desconocido"
                    db.execute("ROLLBACK")
                    flash(f"No hay suficiente stock de '{nombre_prod}' en la bodega.", "danger")
                    return redirect(url_for("editar_venta", venta_id=venta_id))

                # Cálculos
                subtotal = cantidad * costo
                descuento_valor = subtotal * (descuento_porcentaje / 100)
                iva_valor = subtotal * (iva_porcentaje / 100)
                total = subtotal - descuento_valor + iva_valor
                total_venta += total

                # Insertar detalle
                db.execute("""
                    INSERT INTO Detalle_Facturacion 
                    (ID_Factura, ID_Producto, Cantidad, Costo, Descuento, IVA, Total)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, venta_id, id_producto, cantidad, costo, descuento_valor, iva_valor, total)

                # Insertar movimiento
                db.execute("""
                    INSERT INTO Detalle_Movimiento_Inventario (
                        ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                        Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, 
                    movimiento_id, movimiento_original[0]["ID_TipoMovimiento"], id_producto,
                    cantidad, costo, iva_valor, descuento_valor, total, -cantidad
                )

                # Actualizar inventarios
                db.execute("""
                    UPDATE Productos SET Existencias = Existencias - ?
                    WHERE ID_Producto = ?
                """, cantidad, id_producto)

                db.execute("""
                    UPDATE Inventario_Bodega SET Existencias = Existencias - ?
                    WHERE ID_Bodega = ? AND ID_Producto = ?
                """, cantidad, id_bodega, id_producto)

            # Registrar cuenta por cobrar si es crédito
            if tipo_pago == 1:
                fecha_vencimiento = (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=30)).strftime("%Y-%m-%d")
                db.execute("""
                    INSERT INTO Detalle_Cuentas_Por_Cobrar (
                        ID_Movimiento, Fecha, ID_Cliente, Num_Documento, Observacion,
                        Fecha_Vencimiento, Tipo_Movimiento, Monto_Movimiento,
                        IVA, Retencion, ID_Empresa, Saldo_Pendiente
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """, 
                    venta_id, fecha, cliente_id, f"F-{venta_id:05d}", observacion,
                    fecha_vencimiento, 2, total_venta, id_empresa, total_venta
                )

            db.execute("COMMIT")
            flash("Venta actualizada correctamente.", "success")
            return redirect(url_for("gestionar_ventas"))

        except Exception as e:
            db.execute("ROLLBACK")
            flash(f"Error al actualizar la venta: {str(e)}", "danger")
            return redirect(url_for("editar_venta", venta_id=venta_id))

    # === MÉTODO GET ===
    try:
        # Obtener datos de la venta
        venta = db.execute("""
            SELECT f.*, c.Nombre AS cliente_nombre 
            FROM Facturacion f
            JOIN Clientes c ON f.IDCliente = c.ID_Cliente
            WHERE f.ID_Factura = ?
        """, venta_id)
        
        if not venta:
            flash("La venta que intentas editar no existe.", "danger")
            return redirect(url_for("gestionar_ventas"))

        # Obtener detalles
        detalles = db.execute("""
            SELECT df.*, p.Descripcion AS producto_nombre,
                   CASE WHEN (df.Cantidad * df.Costo) > 0 
                        THEN (df.IVA * 100) / (df.Cantidad * df.Costo) 
                        ELSE 0 END AS iva_porcentaje,
                   CASE WHEN (df.Cantidad * df.Costo) > 0 
                        THEN (df.Descuento * 100) / (df.Cantidad * df.Costo) 
                        ELSE 0 END AS descuento_porcentaje,
                   p.Precio_Venta AS precio_sugerido
            FROM Detalle_Facturacion df
            JOIN Productos p ON df.ID_Producto = p.ID_Producto
            WHERE df.ID_Factura = ?
        """, venta_id)

        # Obtener datos para selects
        clientes = db.execute("SELECT ID_Cliente AS id, Nombre AS nombre FROM Clientes")
        productos = db.execute("""
            SELECT ID_Producto AS id, Descripcion AS descripcion, Precio_Venta AS precio 
            FROM Productos WHERE Estado = 1
        """)
        bodegas = db.execute("SELECT ID_Bodega AS id, Nombre AS nombre FROM Bodegas")

        n_factura = f"F-{venta_id:05d}"

        return render_template("editar_venta.html", 
                            venta=venta[0] if venta else None, 
                            detalles=detalles,
                            clientes=clientes, 
                            productos=productos, 
                            bodegas=bodegas, 
                            n_factura=n_factura)

    except Exception as e:
        flash(f"Error al cargar la venta: {str(e)}", "danger")
        return redirect(url_for("gestionar_ventas"))
    
#fin de ruta de ventas
#####################################################################################################
# ruta de cobros
@app.route("/cobros", methods=["GET"])
@login_required
def cobros():
    try:
        # Obtener parámetros de filtro
        cliente_id = request.args.get('cliente_id', '')
        fecha_desde = request.args.get('fecha_desde', '')
        fecha_hasta = request.args.get('fecha_hasta', '')
        estado = request.args.get('estado', '')
        
        query = """
            SELECT dcc.ID_Movimiento, dcc.Num_Documento AS Factura,
                   c.Nombre AS Cliente, c.ID_Cliente,
                   dcc.Monto_Movimiento AS Saldo,
                   dcc.Fecha, dcc.Fecha_Vencimiento
            FROM Detalle_Cuentas_Por_Cobrar dcc
            JOIN Clientes c ON dcc.ID_Cliente = c.ID_Cliente
            WHERE dcc.Monto_Movimiento > 0
        """
        
        params = []
        
        # Aplicar filtros
        if cliente_id:
            query += " AND c.ID_Cliente = ?"
            params.append(cliente_id)
        if fecha_desde:
            query += " AND dcc.Fecha >= ?"
            params.append(fecha_desde)
        if fecha_hasta:
            query += " AND dcc.Fecha <= ?"
            params.append(fecha_hasta)
        if estado == 'vencido':
            query += " AND dcc.Fecha_Vencimiento < date('now')"
        elif estado == 'pendiente':
            query += " AND (dcc.Fecha_Vencimiento >= date('now') OR dcc.Fecha_Vencimiento IS NULL)"
            
        query += " ORDER BY dcc.Fecha_Vencimiento DESC"
        
        cuentas = db.execute(query, *params)
        
        # Obtener lista de clientes para el filtro
        clientes = db.execute("SELECT ID_Cliente, Nombre FROM Clientes ORDER BY Nombre")
        
        return render_template("cobros.html", 
                            cuentas=cuentas, 
                            clientes=clientes,
                            filtros={
                                'cliente_id': cliente_id,
                                'fecha_desde': fecha_desde,
                                'fecha_hasta': fecha_hasta,
                                'estado': estado
                            })
    except Exception as e:
        flash(f"❌ Error al cargar los cobros: {e}", "danger")
        return redirect(url_for("home"))
#######################################################################################
@app.route("/historial_pagos/<int:id_movimiento>")
@login_required
def historial_pagos(id_movimiento):
    try:
        # Obtener historial de pagos
        pagos = db.execute("""
            SELECT 
                p.ID_Pago, 
                p.Fecha, 
                p.Monto, 
                mp.Nombre AS Metodo, 
                p.Comentarios, 
                p.Detalles_Metodo
            FROM Pagos_CuentasCobrar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            WHERE p.ID_Movimiento = ?
            ORDER BY p.Fecha DESC
        """, id_movimiento)

        # Obtener información de la factura
        factura_result = db.execute("""
            SELECT 
                dcc.Num_Documento, 
                dcc.Monto_Movimiento,
                dcc.Fecha, 
                dcc.Fecha_Vencimiento, 
                c.Nombre AS Cliente,
                dcc.ID_Cliente, 
                dcc.Observacion
            FROM Detalle_Cuentas_Por_Cobrar dcc
            JOIN Clientes c ON dcc.ID_Cliente = c.ID_Cliente
            WHERE dcc.ID_Movimiento = ?
        """, id_movimiento)

        if not factura_result:
            flash("❌ Factura no encontrada", "danger")
            return redirect(url_for("cobros"))

        factura = factura_result[0]

        # Procesar los datos para la vista
        pagos_procesados = []
        total_pagado = 0

        for pago in pagos:
            try:
                # Formatear fecha
                fecha = pago['Fecha']
                if isinstance(fecha, str):
                    fecha = datetime.strptime(fecha, '%Y-%m-%d %H:%M:%S')
                
                # Procesar detalles
                detalles = {}
                if pago['Detalles_Metodo']:
                    try:
                        detalles = json.loads(pago['Detalles_Metodo'])
                    except:
                        detalles = {'raw': pago['Detalles_Metodo']}
                
                # Calcular total
                if pago['Monto']:
                    total_pagado += float(pago['Monto'])

                pagos_procesados.append({
                    'Fecha': fecha.strftime('%d/%m/%Y %H:%M') if fecha else 'Sin fecha',
                    'Monto': float(pago['Monto']) if pago['Monto'] else 0,
                    'Metodo': pago['Metodo'],
                    'Detalles': detalles,
                    'Comentarios': pago['Comentarios'] or 'Sin comentarios'
                })
            except Exception as e:
                app.logger.error(f"Error procesando pago {pago.get('ID_Pago')}: {str(e)}")
                continue

        return render_template("historial_pagos.html", 
                            pagos=pagos_procesados, 
                            factura=factura,
                            total_pagado=total_pagado)

    except Exception as e:
        flash(f"❌ Error al cargar el historial: {str(e)}", "danger")
        app.logger.error(f"Error en historial_pagos: {str(e)}")
        return redirect(url_for("cobros"))
#######################################################################################
@app.route("/registrar_cobro/<int:id_movimiento>", methods=["GET", "POST"])
@login_required
def registrar_cobro(id_movimiento):
    if request.method == "POST":
        try:
            # Validación y captura de datos básicos
            monto = float(request.form["monto"])
            metodo = int(request.form["metodo_pago"])
            comentarios = request.form.get("comentarios", "").strip()

            # Captura de detalles específicos del método de pago (similar a cuentas por pagar)
            datos_especificos = {}
            errores = []
            
            # Efectivo
            if metodo == 1:
                efectivo_recibido = float(request.form.get("efectivo_recibido", 0))
                if efectivo_recibido < 0:
                    errores.append("El efectivo recibido debe ser mayor a cero")
                if efectivo_recibido < monto:
                    errores.append("El efectivo recibido no puede ser menor que el monto del cobro")

                datos_especificos = {
                    'tipo': 'efectivo',
                    'efectivo_recibido': float(request.form.get("efectivo_recibido", 0)),
                    'cambio': float(request.form.get("efectivo_recibido", 0)) - monto
                }
            
            # Transferencia Bancaria
            elif metodo == 2:
                numero_transferencia = request.form.get("Numero_transferencia", "").strip()
                banco = request.form.get("banco", "").strip()

                if not numero_transferencia:
                    errores.append("El numero de transferencia es obligatorio")
                if not banco:
                    errores.append("Debes especificar al banco de origen")

                datos_especificos = {
                    'tipo': 'transferencia',
                    'numero_transferencia': request.form.get("numero_transferencia"),
                    'banco': request.form.get("banco"),
                    'referencia': request.form.get("referencia", "")
                }
            
            # Tarjeta
            elif metodo == 3:
                tipo_tarjeta = request.form.get("tipo_tarjeta", "").strip()
                ultimos_digitos = request.form.get("ultimos_digitos", "").strip()

                if not tipo_tarjeta:
                    errores.append("Debe especificar el tipo de tarjeta")
                if not ultimos_digitos or not ultimos_digitos.isdigit() or len(ultimos_digitos) != 4:
                    errores.append("Los ultimos 4 digitos de la tarjeta son obligatorios")
                
                datos_especificos = {
                    'tipo': 'tarjeta',
                    'tipo_tarjeta': request.form.get("tipo_tarjeta"),
                    'ultimos_digitos': request.form.get("ultimos_digitos"),
                    'autorizacion': request.form.get("autorizacion", "")
                }

            # Verificación de saldo disponible
            factura = db.execute("""
                SELECT Monto_Movimiento, ID_Cliente, Num_Documento
                FROM Detalle_Cuentas_Por_Cobrar
                WHERE ID_Movimiento = ?
            """, id_movimiento)
            
            if not factura:
                flash("❌ Factura no encontrada", "danger")
                return redirect(url_for("cobros"))
                
            saldo_actual = float(factura[0]["Monto_Movimiento"])

            # Validaciones de negocio
            if monto <= 0:
                flash("❌ El monto debe ser mayor a cero", "danger")
                return redirect(url_for("registrar_cobro", id_movimiento=id_movimiento))
                
            if monto > saldo_actual:
                flash(f"❌ El monto excede el saldo pendiente (${saldo_actual:.2f})", "danger")
                return redirect(url_for("registrar_cobro", id_movimiento=id_movimiento))
            
            if errores:
                for error in errores:
                    flash(f"❌ {error}", "danger")
                return redirect(url_for("registrar_cobro", id_movimiento=id_movimiento))
            
            # Convertir detalles a JSON
            detalles_metodo = json.dumps(datos_especificos, ensure_ascii=False)

            # Registro del cobro
            db.execute("BEGIN TRANSACTION")
            try:
                # Insertar pago con detalles estructurados
                db.execute("""
                    INSERT INTO Pagos_CuentasCobrar 
                    (ID_Movimiento, Fecha, Monto, ID_MetodoPago, Comentarios, Detalles_Metodo)
                    VALUES (?, datetime('now'), ?, ?, ?, ?)
                """, id_movimiento, monto, metodo, comentarios, detalles_metodo)

                # Actualizar saldo
                db.execute("""
                    UPDATE Detalle_Cuentas_Por_Cobrar 
                    SET Monto_Movimiento = Monto_Movimiento - ?
                    WHERE ID_Movimiento = ?
                """, monto, id_movimiento)

                db.execute("COMMIT")
                flash("✅ Cobro registrado correctamente", "success")
                return redirect(url_for("registrar_cobro", id_movimiento=id_movimiento))
                
            except Exception as e:
                db.execute("ROLLBACK")
                flash(f"❌ Error en la transacción: {str(e)}", "danger")
                app.logger.error(f"Error en transacción de cobro: {str(e)}")
                return redirect(url_for("registrar_cobro", id_movimiento=id_movimiento))
                
        except ValueError as e:
            flash(f"❌ Error en los datos numéricos: {str(e)}", "danger")
            return redirect(url_for("registrar_cobro", id_movimiento=id_movimiento))
        except Exception as e:
            flash(f"❌ Error al registrar cobro: {str(e)}", "danger")
            app.logger.error(f"Error en registrar_cobro: {str(e)}")
            return redirect(url_for("registrar_cobro", id_movimiento=id_movimiento))
    
    # Método GET - Mostrar formulario
    try:
        # Obtener datos de la cuenta/cliente
        factura = db.execute("""
            SELECT 
                dcc.ID_Movimiento, 
                dcc.Num_Documento, 
                dcc.Monto_Movimiento,
                c.Nombre AS Cliente,
                c.ID_Cliente
            FROM Detalle_Cuentas_Por_Cobrar dcc
            JOIN Clientes c ON dcc.ID_Cliente = c.ID_Cliente
            WHERE dcc.ID_Movimiento = ?
        """, id_movimiento)[0]
        
        # Obtener métodos de pago disponibles
        metodos_pago = db.execute("""
            SELECT ID_MetodoPago, Nombre 
            FROM Metodos_Pago 
            ORDER BY Nombre
        """)
        
        # Obtener historial de cobros anteriores
        historial_cobros = db.execute("""
            SELECT 
                p.ID_Pago,
                p.Fecha,
                p.Monto,
                mp.Nombre AS MetodoPago,
                p.Comentarios,
                p.Detalles_Metodo
            FROM Pagos_CuentasCobrar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            WHERE p.ID_Movimiento = ?
            ORDER BY p.Fecha DESC
        """, id_movimiento)

        # Convertir detalles de JSON a dict para la vista
        for cobro in historial_cobros:
            if cobro['Detalles_Metodo']:
                try:
                    cobro['Detalles_Metodo'] = json.loads(cobro['Detalles_Metodo'])
                except json.JSONDecodeError:
                    cobro['Detalles_Metodo'] = {'tipo': 'desconocido', 'detalle': cobro['Detalles_Metodo']}

        return render_template(
            "registrar_cobro.html",
            factura=factura,
            metodos=metodos_pago,
            historial=historial_cobros
        )
        
    except IndexError:
        flash("❌ Factura no encontrada", "danger")
        return redirect(url_for("cobros"))
    except Exception as e:
        flash(f"❌ Error al cargar datos: {str(e)}", "danger")
        app.logger.error(f"Error en GET registrar_cobro: {str(e)}")
        return redirect(url_for("cobros"))
#######################################################################################
@app.route("/cancelar_deuda/<int:id_movimiento>", methods=["POST"])
@login_required
def cancelar_deuda(id_movimiento):
    try:
        # Obtener saldo actual
        factura = db.execute("""
            SELECT Monto_Movimiento 
            FROM Detalle_Cuentas_Por_Cobrar 
            WHERE ID_Movimiento = ?
        """, id_movimiento)
        
        if not factura:
            flash("❌ Factura no encontrada", "danger")
            return redirect(url_for("cobros"))
            
        saldo_actual = float(factura[0]["Monto_Movimiento"])
        
        if saldo_actual <= 0:
            flash("ℹ️ Esta factura ya está pagada", "info")
            return redirect(url_for("historial_pagos", id_movimiento=id_movimiento))

        # Procesar cancelación
        db.execute("BEGIN TRANSACTION")
        try:
            # Registrar pago completo
            db.execute("""
                INSERT INTO Pagos_CuentasCobrar 
                (ID_Movimiento, Fecha, Monto, ID_MetodoPago, Comentarios)
                VALUES (?, datetime('now'), ?, 
                (SELECT ID_MetodoPago FROM Metodos_Pago WHERE Nombre = 'Cancelación Manual'), 
                'Cancelación manual de deuda')
            """, id_movimiento, saldo_actual)

            # Actualizar saldo a 0
            db.execute("""
                UPDATE Detalle_Cuentas_Por_Cobrar 
                SET Monto_Movimiento = 0
                WHERE ID_Movimiento = ?
            """, id_movimiento)

            db.execute("COMMIT")
            flash("✅ Deuda cancelada manualmente", "success")
            return redirect(url_for("historial_pagos", id_movimiento=id_movimiento))
            
        except Exception as e:
            db.execute("ROLLBACK")
            raise e
            
    except Exception as e:
        flash(f"❌ Error al cancelar la deuda: {str(e)}", "danger")
        return redirect(url_for("cobros"))
#fin de rutas de cobros
#######################################################################################
# ruta de pagos
@app.route("/pagos", methods=["GET"])
@login_required
def pagos():
    try:
        cuentas = db.execute("""
            SELECT 
                cpp.ID_Cuenta,
                cpp.ID_Movimiento,
                cpp.Num_Documento AS Factura,
                p.Nombre AS Proveedor,
                cpp.Monto_Movimiento,
                cpp.Saldo_Pendiente,
                cpp.Fecha_Vencimiento AS Fecha_Vencimiento_Original,
                strftime('%d/%m/%Y', cpp.Fecha_Vencimiento) AS Fecha_Vencimiento_Formateada,
                CASE 
                    WHEN cpp.Saldo_Pendiente <= 0 THEN 'Pagado'
                    WHEN cpp.Saldo_Pendiente < cpp.Monto_Movimiento THEN 'Abonado'
                    ELSE 'Pendiente'
                END AS Estado
            FROM Cuentas_Por_Pagar cpp
            JOIN Proveedores p ON cpp.ID_Proveedor = p.ID_Proveedor
            ORDER BY cpp.ID_Cuenta DESC
        """)
        return render_template("pagos.html", cuentas=cuentas)
    except Exception as e:
        flash(f"❌ Error al cargar los pagos: {str(e)}", "danger")
        app.logger.error(f"Error en pagos: {str(e)}")
        return redirect(url_for("home"))
#######################################################################################
@app.route("/actualizar_saldos", methods=["GET"])
@login_required
def actualizar_saldos():
    try:
        cuentas = db.execute("""
            SELECT 
                cpp.ID_Cuenta,
                cpp.Monto_Movimiento,
                cpp.Saldo_Pendiente,
                CASE 
                    WHEN cpp.Saldo_Pendiente <= 0 THEN 'Pagado'
                    WHEN cpp.Saldo_Pendiente < cpp.Monto_Movimiento THEN 'Abonado'
                    ELSE 'Pendiente'
                END AS Estado
            FROM Cuentas_Por_Pagar cpp
            ORDER BY cpp.ID_Cuenta DESC
        """)
        return jsonify(cuentas)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
#######################################################################################
@app.route("/registrar_pago/<int:id_cuenta>", methods=["GET", "POST"])
@login_required
def registrar_pago(id_cuenta):
    if request.method == "POST":
        try:
            # Validación y captura de datos básicos
            monto = float(request.form["monto"])
            metodo = int(request.form["metodo_pago"])
            comentarios = request.form.get("comentarios", "").strip()

            # Captura de detalles específicos del método de pago
            datos_especificos = {}
            
            # Efectivo
            if metodo == 1:
                datos_especificos = {
                    'tipo': 'efectivo',
                    'efectivo_recibido': request.form.get("efectivo_recibido"),
                    'cambio': float(request.form.get("efectivo_recibido", 0)) - monto if request.form.get("efectivo_recibido") else None
                }
            
            # Transferencia Bancaria
            elif metodo == 2:
                datos_especificos = {
                    'tipo': 'transferencia',
                    'numero_transferencia': request.form.get("numero_transferencia"),
                    'banco': request.form.get("banco"),
                    'referencia': request.form.get("referencia", "")
                }
            
            # Tarjeta
            elif metodo == 3:
                datos_especificos = {
                    'tipo': 'tarjeta',
                    'tipo_tarjeta': request.form.get("tipo_tarjeta"),
                    'ultimos_digitos': request.form.get("ultimos_digitos"),
                    'autorizacion': request.form.get("autorizacion", "")
                }

            # Serialización de detalles específicos
            detalles_metodo = json.dumps(datos_especificos, ensure_ascii=False)

            # Verificación de saldo disponible
            factura = db.execute("""
                SELECT Monto_Movimiento, Saldo_Pendiente 
                FROM Cuentas_Por_Pagar 
                WHERE ID_Cuenta = ?
            """, id_cuenta)
            
            if not factura:
                flash("❌ Factura no encontrada", "danger")
                return redirect(url_for("pagos"))
                
            factura = factura[0]
            saldo_actual = float(factura["Saldo_Pendiente"] or factura["Monto_Movimiento"])

            # Validaciones de negocio
            if monto <= 0:
                flash("❌ El monto debe ser mayor a cero", "danger")
                return redirect(url_for("registrar_pago", id_cuenta=id_cuenta))
                
            if monto > saldo_actual:
                flash(f"❌ El monto excede el saldo pendiente (${saldo_actual:.2f})", "danger")
                return redirect(url_for("registrar_pago", id_cuenta=id_cuenta))

            # Registro del pago
            fecha_pago = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            db.execute("""
                INSERT INTO Pagos_CuentasPagar 
                (ID_Cuenta, Fecha, Monto, ID_MetodoPago, Comentarios, Detalles_Metodo)
                VALUES (?, ?, ?, ?, ?, ?)
            """, id_cuenta, fecha_pago, monto, metodo, comentarios, detalles_metodo)

            # Actualización del saldo pendiente
            nuevo_saldo = saldo_actual - monto
            estado_pago = 2 if nuevo_saldo <= 0 else 1  # 2 = Pagado, 1 = Parcial

            db.execute("""
                UPDATE Cuentas_Por_Pagar 
                SET Saldo_Pendiente = ?
                WHERE ID_Cuenta = ?
            """, max(0, nuevo_saldo), id_cuenta)

            flash("✅ Pago registrado correctamente", "success")
            return redirect(url_for("detalle_cuenta", id_cuenta=id_cuenta))
            
        except ValueError as e:
            flash(f"❌ Error en los datos numéricos: {str(e)}", "danger")
            return redirect(url_for("registrar_pago", id_cuenta=id_cuenta))
        except Exception as e:
            flash(f"❌ Error al registrar pago: {str(e)}", "danger")
            app.logger.error(f"Error en registrar_pago: {str(e)}")
            return redirect(url_for("registrar_pago", id_cuenta=id_cuenta))
    
    # Método GET - Mostrar formulario
    try:
        # Obtener datos de la cuenta/proveedor
        factura = db.execute("""
            SELECT 
                cpp.ID_Cuenta, 
                cpp.ID_Movimiento, 
                cpp.Num_Documento, 
                cpp.Monto_Movimiento,
                cpp.Saldo_Pendiente,
                p.Nombre AS Proveedor,
                p.ID_Proveedor
            FROM Cuentas_Por_Pagar cpp
            JOIN Proveedores p ON cpp.ID_Proveedor = p.ID_Proveedor
            WHERE cpp.ID_Cuenta = ?
        """, id_cuenta)[0]
        
        # Obtener métodos de pago disponibles
        metodos_pago = db.execute("""
            SELECT ID_MetodoPago, Nombre 
            FROM Metodos_Pago 
            ORDER BY Nombre
        """)
        
        # Obtener historial de pagos anteriores (corregido)
        historial_pagos = db.execute("""
            SELECT 
                p.ID_Pago,
                p.Fecha,  # Obtenemos directamente el campo Fecha
                p.Monto,
                mp.Nombre AS MetodoPago,
                p.Comentarios
            FROM Pagos_CuentasPagar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            WHERE p.ID_Cuenta = ?
            ORDER BY p.Fecha DESC
        """, id_cuenta)

        # Convertir fechas string a datetime si es necesario
        for pago in historial_pagos:
            if isinstance(pago['Fecha'], str):
                try:
                    pago['Fecha'] = datetime.strptime(pago['Fecha'], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pago['Fecha'] = None

        return render_template(
            "registrar_pago.html",
            factura=factura,
            metodos=metodos_pago,
            historial=historial_pagos
        )
        
    except IndexError:
        flash("❌ Factura no encontrada", "danger")
        return redirect(url_for("pagos"))
    except Exception as e:
        flash(f"❌ Error al cargar datos: {str(e)}", "danger")
        app.logger.error(f"Error en GET registrar_pago: {str(e)}")
        return redirect(url_for("pagos"))
#######################################################################################
# Ruta para ver el detalle de la cuenta con los pagos
@app.route("/detalle_cuenta/<int:id_cuenta>")
@login_required
def detalle_cuenta(id_cuenta):
    try:
        # Obtener información de la cuenta
        cuenta = db.execute("""
            SELECT 
                cpp.*,
                p.Nombre AS Proveedor,
                p.RFC,
                p.Telefono
            FROM Cuentas_Por_Pagar cpp
            JOIN Proveedores p ON cpp.ID_Proveedor = p.ID_Proveedor
            WHERE cpp.ID_Cuenta = ?
        """, id_cuenta)[0]
        
        # Obtener todos los pagos asociados
        pagos = db.execute("""
            SELECT 
                p.*,
                mp.Nombre AS MetodoPago
            FROM Pagos_CuentasPagar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            WHERE p.ID_Cuenta = ?
            ORDER BY p.Fecha DESC
        """, id_cuenta)
        
        # Procesar detalles de cada pago
        for pago in pagos:
            if pago['Detalles_Metodo']:
                pago['Detalles'] = json.loads(pago['Detalles_Metodo'])
            else:
                pago['Detalles'] = {}
        
        return render_template(
            "pago.html",
            factura=cuenta,
            cuenta=cuenta,
            pagos=pagos
        )
        
    except IndexError:
        flash("❌ Cuenta no encontrada", "danger")
        return redirect(url_for("pagos"))
    except Exception as e:
        flash(f"❌ Error al cargar detalles: {str(e)}", "danger")
        app.logger.error(f"Error en detalle_cuenta: {str(e)}")
        return redirect(url_for("pagos"))
#######################################################################################
@app.route("/historial_pagos_pagar/<int:id_cuenta>")
@login_required
def historial_pagos_pagar(id_cuenta):
    try:
        # Obtener información de la cuenta
        cuenta = db.execute("""
            SELECT Num_Documento, Monto_Movimiento, Saldo_Pendiente
            FROM Cuentas_Por_Pagar
            WHERE ID_Cuenta = ?
        """, id_cuenta)[0]

        # Obtener historial de pagos
        pagos = db.execute("""
            SELECT 
                p.Fecha, 
                p.Monto, 
                mp.Nombre AS Metodo,
                p.Comentarios,
                p.Detalles_Metodo
            FROM Pagos_CuentasPagar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            WHERE p.ID_Cuenta = ?
            ORDER BY p.Fecha DESC
        """, id_cuenta)

        # Procesar detalles JSON
        for pago in pagos:
            if pago['Detalles_Metodo']:
                pago['Detalles'] = json.loads(pago['Detalles_Metodo'])
            else:
                pago['Detalles'] = {}

        return render_template(
            "historial_pagos_pagar.html",
            cuenta=cuenta,
            pagos=pagos,
            id_cuenta=id_cuenta
        )

    except IndexError:
        flash("❌ Cuenta no encontrada", "danger")
        return redirect(url_for("pagos"))
    except Exception as e:
        flash(f"❌ Error al cargar historial de pagos: {str(e)}", "danger")
        app.logger.error(f"Error en historial_pagos_pagar: {str(e)}")
        return redirect(url_for("pagos"))
#fin de ruta de pagos
#######################################################################################
# Ruta Factura impresion
def format_currency(value):
    return "{:,.2f}".format(value)
#######################################################################################
@app.route("/factura_alterna", methods=["GET", "POST"])
@login_required
def factura_alterna():
    id_empresa = getattr(current_user, 'id_empresa', 1)
    
    if request.method == "POST":
        try:
            # === VALIDACIÓN DE FECHA ===
            fecha = request.form.get("fecha")
            if not fecha:
                flash("La fecha es requerida", "danger")
                return redirect(url_for("factura_alterna"))

            try:
                fecha_date = datetime.strptime(fecha, '%Y-%m-%d').date()
                hoy = datetime.now().date()
                
                if fecha_date > hoy:
                    flash("La fecha no puede ser futura", "danger")
                    return redirect(url_for("factura_alterna"))
                if fecha_date < hoy - timedelta(days=365*5):
                    flash("La fecha no puede ser menor a 5 años", "danger")
                    return redirect(url_for("factura_alterna"))
            except ValueError:
                flash("Formato de fecha inválido (YYYY-MM-DD)", "danger")
                return redirect(url_for("factura_alterna"))

            # === OBTENER Y VALIDAR DATOS PRINCIPALES ===
            cliente_id = request.form.get("cliente")
            tipo_pago = request.form.get("tipo_pago")
            id_bodega = request.form.get("id_bodega")
            observacion = request.form.get("observacion", "").strip()
            
            if not all([cliente_id, tipo_pago, id_bodega]):
                flash("Todos los campos obligatorios deben estar completos", "danger")
                return redirect(url_for("factura_alterna"))

            try:
                cliente_id = int(cliente_id)
                tipo_pago = int(tipo_pago)
                id_bodega = int(id_bodega)
                
                if tipo_pago not in (0, 1):
                    flash("Tipo de pago inválido", "danger")
                    return redirect(url_for("factura_alterna"))
            except (ValueError, TypeError):
                flash("Datos numéricos inválidos", "danger")
                return redirect(url_for("factura_alterna"))

            # === OBTENER DATOS DE PRODUCTOS ===
            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("precio_unitarios[]") or request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]") or [0]*len(productos)
            descuentos = request.form.getlist("descuentos[]") or [0]*len(productos)

            # === VALIDACIONES DE PRODUCTOS ===
            if not productos:
                flash("Debe ingresar al menos un producto", "danger")
                return redirect(url_for("factura_alterna"))

            if len(productos) != len(cantidades) or len(productos) != len(costos):
                flash("Error en los datos de productos", "danger")
                return redirect(url_for("factura_alterna"))

            # === CONVERSIÓN DE DATOS DE PRODUCTOS ===
            try:
                productos_ids = [int(p) for p in productos]
                cantidades = [max(0.01, round(float(q), 2)) for q in cantidades]
                costos = [max(0.01, round(float(p), 2)) for p in costos]
                ivas = [float(i) for i in ivas]
                descuentos = [float(d) for d in descuentos]
            except (ValueError, TypeError) as ve:
                flash(f"Datos de productos inválidos: {str(ve)}", "danger")
                return redirect(url_for("factura_alterna"))

            # === VERIFICACIÓN EN BASE DE DATOS ===
            # Verificar cliente y bodega
            cliente_bodega = db.execute(
                """SELECT 
                   (SELECT COUNT(*) FROM Clientes WHERE ID_Cliente = ?) as cliente_existe,
                   (SELECT COUNT(*) FROM Bodegas WHERE ID_Bodega = ?) as bodega_existe""",
                cliente_id, id_bodega
            )[0]
            
            if not cliente_bodega["cliente_existe"]:
                flash("Cliente no encontrado", "danger")
                return redirect(url_for("factura_alterna"))
            if not cliente_bodega["bodega_existe"]:
                flash("Bodega no encontrada", "danger")
                return redirect(url_for("factura_alterna"))

            # Verificar productos y existencias
            placeholders = ",".join(["?"]*len(productos_ids))
            productos_db = db.execute(
                f"""SELECT p.ID_Producto, p.Descripcion, 
                    COALESCE(ib.Existencias, 0) as Existencias
                    FROM Productos p
                    LEFT JOIN Inventario_Bodega ib ON p.ID_Producto = ib.ID_Producto 
                    AND ib.ID_Bodega = ?
                    WHERE p.ID_Producto IN ({placeholders})""",
                id_bodega, *productos_ids
            )

            if len(productos_db) != len(productos_ids):
                flash("Algunos productos no existen", "danger")
                return redirect(url_for("factura_alterna"))

            # Verificar stock antes de transacción
            existencias = {p["ID_Producto"]: p["Existencias"] for p in productos_db}
            for i, id_producto in enumerate(productos_ids):
                if existencias[id_producto] < cantidades[i]:
                    nombre_prod = next(p["Descripcion"] for p in productos_db if p["ID_Producto"] == id_producto)
                    flash(f"No hay suficiente stock del producto '{nombre_prod}' en la bodega", "danger")
                    return redirect(url_for("factura_alterna"))

            # === INICIO DE TRANSACCIÓN ===
            db.execute("BEGIN")

            # === INSERTAR FACTURA ALTERNA ===
            factura_id = db.execute(
                """INSERT INTO Factura_Alterna 
                   (Fecha, IDCliente, Credito_Contado, Observacion, ID_Empresa)
                   VALUES (?, ?, ?, ?, ?) RETURNING ID_Factura""",
                fecha, cliente_id, tipo_pago, observacion, id_empresa
            )[0]["ID_Factura"]

            # Obtener tipo de movimiento
            tipo_movimiento = db.execute(
                "SELECT ID_TipoMovimiento FROM Catalogo_Movimientos WHERE Descripcion = 'Venta'"
            )
            if not tipo_movimiento:
                db.execute("ROLLBACK")
                flash("El tipo de movimiento 'Venta' no está definido.", "danger")
                return redirect(url_for("factura_alterna"))
            tipo_movimiento = tipo_movimiento[0]["ID_TipoMovimiento"]

            # Insertar movimiento de inventario
            movimiento_id = db.execute(
                """INSERT INTO Movimientos_Inventario (
                    ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                    ID_Proveedor, Observacion, IVA, Retencion,
                    ID_Empresa, ID_Bodega
                ) VALUES (?, ?, ?, ?, NULL, ?, 0, 0, ?, ?) RETURNING ID_Movimiento""",
                tipo_movimiento, f"FA-{factura_id:05d}", tipo_pago, fecha, 
                observacion, id_empresa, id_bodega
            )[0]["ID_Movimiento"]

            # === PROCESAR PRODUCTOS ===
            total_venta = 0
            detalles_factura = []
            detalles_movimiento = []
            updates_productos = []
            updates_inventario = []
            
            for i, id_producto in enumerate(productos_ids):
                cantidad = cantidades[i]
                costo = costos[i]
                iva = ivas[i]
                descuento = descuentos[i]
                total = (cantidad * costo) - descuento + iva
                total_venta += total

                # Preparar datos para inserción batch
                detalles_factura.append((factura_id, id_producto, cantidad, costo, total))
                detalles_movimiento.append((
                    movimiento_id, tipo_movimiento, id_producto,
                    cantidad, costo, iva, descuento, total, -cantidad
                ))
                updates_productos.append((cantidad, id_producto))
                updates_inventario.append((cantidad, id_bodega, id_producto))

            # Ejecutar inserciones batch
            db.executemany(
                """INSERT INTO Detalle_Factura_Alterna 
                   (ID_Factura, ID_Producto, Cantidad, Costo, Total)
                   VALUES (?, ?, ?, ?, ?)""",
                detalles_factura
            )

            db.executemany(
                """INSERT INTO Detalle_Movimiento_Inventario (
                    ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                    Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                detalles_movimiento
            )

            # Actualizar existencias (batch)
            db.executemany(
                "UPDATE Productos SET Existencias = Existencias - ? WHERE ID_Producto = ?",
                updates_productos
            )

            db.executemany(
                """UPDATE Inventario_Bodega 
                   SET Existencias = Existencias - ? 
                   WHERE ID_Bodega = ? AND ID_Producto = ?""",
                updates_inventario
            )

            # === REGISTRAR CUENTA POR COBRAR SI ES CRÉDITO ===
            if tipo_pago == 1:
                fecha_vencimiento = fecha_date + timedelta(days=30)
                db.execute(
                    """INSERT INTO Detalle_Cuentas_Por_Cobrar (
                        ID_Movimiento, Fecha, ID_Cliente, Num_Documento, Observacion,
                        Fecha_Vencimiento, Tipo_Movimiento, Monto_Movimiento,
                        IVA, Retencion, ID_Empresa
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)""",
                    factura_id, fecha, cliente_id, f"FA-{factura_id:05d}", observacion,
                    fecha_vencimiento.strftime("%Y-%m-%d"), 2, total_venta, id_empresa
                )

            db.execute("COMMIT")
            flash(f"Factura alterna #{factura_id} registrada correctamente. Total: ${total_venta:.2f}", "success")
            return redirect(url_for("factura_alterna"))

        except Exception as e:
            db.execute("ROLLBACK")
            print(f"Error en factura_alterna: {str(e)}\n{traceback.format_exc()}")
            flash(f"Error al registrar la factura alterna: {str(e)}", "danger")
            return redirect(url_for("factura_alterna"))

    # === MÉTODO GET ===
    try:
        # Obtener datos en consultas optimizadas
        clientes = db.execute(
            "SELECT ID_Cliente AS id, Nombre AS nombre FROM Clientes WHERE ID_Empresa = ?",
            id_empresa
        )
        
        productos = db.execute(
            "SELECT ID_Producto AS id, Descripcion AS descripcion FROM Productos WHERE ID_Empresa = ?",
            id_empresa
        )
        
        bodegas = db.execute(
            "SELECT ID_Bodega AS id, Nombre AS nombre FROM Bodegas WHERE ID_Empresa = ?",
            id_empresa
        )

        last_seq = db.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", "Factura_Alterna")
        next_id = last_seq[0]["seq"] + 1 if last_seq else 1

        return render_template("factura_alterna.html",
                           clientes=clientes,
                           productos=productos,
                           bodegas=bodegas,
                           id_empresa=id_empresa,
                           next_id=next_id)

    except Exception as e:
        print(f"Error en GET factura_alterna: {str(e)}\n{traceback.format_exc()}")
        flash("Error al cargar datos iniciales", "danger")
        return render_template("factura_alterna.html",
                           clientes=[],
                           productos=[],
                           bodegas=[],
                           next_id=1)
#######################################################################################
@app.route("/api/stock/<int:producto_id>/<int:bodega_id>", methods=["GET"])
@login_required
def get_stock(producto_id, bodega_id):
    try:
        stock = db.execute(
            """SELECT COALESCE(ib.Existencias, 0) as existencias
               FROM Productos p
               LEFT JOIN Inventario_Bodega ib ON p.ID_Producto = ib.ID_Producto 
               AND ib.ID_Bodega = ?
               WHERE p.ID_Producto = ?""",
            bodega_id, producto_id
        )
        
        if not stock:
            return jsonify({"error": "Producto no encontrado"}), 404
            
        return jsonify({"existencias": stock[0]["existencias"]})
        
    except Exception as e:
        print(f"Error en get_stock: {str(e)}")
        return jsonify({"error": str(e)}), 500
#######################################################################################
@app.route("/factura/pdf/<int:venta_id>")
@login_required
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

    # Calcula total general sumando los costos totales
    total_general = sum(item['Costo_Total'] for item in detalles)

    rendered = render_template(
        "factura_pdf.html",
        venta=venta,
        detalles=detalles,
        total_general=total_general,
        format_currency=format_currency,
        LogoFerdel_web_url=url_for('static', filename='LogoFerdel_web.png', _external=True)
    )
    pdf = HTML(string=rendered).write_pdf()
    return Response(pdf, mimetype='application/pdf')
#######################################################################################
@app.route("/facturas", methods=["GET", "POST"])
@login_required
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
#######################################################################################
#ruta de bodega e inventario
@app.route("/bodega", methods=["GET", "POST"])
@login_required
def ver_bodega():
    # Procesar acciones POST (crear/editar/eliminar)
    if request.method == "POST":
        # Crear nueva bodega
        if 'nombre' in request.form:
            nombre = request.form.get("nombre", "").strip()
            ubicacion = request.form.get("ubicacion", "").strip()
            if nombre:
                db.execute("INSERT INTO Bodegas (Nombre, Ubicacion) VALUES (?, ?)", nombre, ubicacion)
                flash("Bodega agregada correctamente", "success")
            else:
                flash("El nombre de la bodega es obligatorio.", "danger")
        
        # Editar bodega existente
        elif 'editar_bodega' in request.form:
            bodega_id = request.form.get("bodega_id")
            nuevo_nombre = request.form.get("nuevo_nombre", "").strip()
            nueva_ubicacion = request.form.get("nueva_ubicacion", "").strip()
            
            if nuevo_nombre:
                db.execute("UPDATE Bodegas SET Nombre = ?, Ubicacion = ? WHERE ID_Bodega = ?", 
                          nuevo_nombre, nueva_ubicacion, bodega_id)
                flash("Bodega actualizada correctamente", "success")
            else:
                flash("El nombre de la bodega es obligatorio.", "danger")
                
        # Eliminar bodega
        elif 'eliminar_bodega' in request.form:
            bodega_id = request.form.get("bodega_id")
            
            # Verificar si la bodega está desocupada
            inventario = db.execute("SELECT COUNT(*) as total FROM Inventario_Bodega WHERE ID_Bodega = ?", bodega_id)
            
            if inventario[0]['total'] == 0:
                db.execute("DELETE FROM Bodegas WHERE ID_Bodega = ?", bodega_id)
                flash("Bodega eliminada correctamente", "success")
            else:
                flash("No se puede eliminar la bodega porque contiene productos en inventario", "danger")
        
        return redirect(url_for("ver_bodega"))

    # Obtener todas las bodegas para GET requests
    bodegas = db.execute("SELECT ID_Bodega, Nombre, Ubicacion FROM Bodegas ORDER BY Nombre")

    # Crear diccionario con inventario por bodega
    inventario_por_bodega = {}
    for bodega in bodegas:
        inventario = db.execute("""
            SELECT P.COD_Producto, P.Descripcion, 
                   COALESCE(I.Existencias, 0) as Existencias, 
                   U.Abreviatura
            FROM Inventario_Bodega I
            JOIN Productos P ON P.ID_Producto = I.ID_Producto
            LEFT JOIN Unidades_Medida U ON U.ID_Unidad = P.Unidad_Medida
            WHERE I.ID_Bodega = ?
            ORDER BY P.Descripcion
        """, bodega["ID_Bodega"])
        inventario_por_bodega[str(bodega["ID_Bodega"])] = inventario

    return render_template("bodega.html", 
                         bodegas=bodegas, 
                         inventario_por_bodega=inventario_por_bodega)
#######################################################################################
# Ruta para manejar acciones AJAX (opcional, para mejor experiencia de usuario)
@app.route("/bodega/acciones", methods=["POST"])
@login_required
def acciones_bodega():
    if not request.is_json:
        return jsonify({"error": "Solicitud no válida"}), 400
    
    data = request.get_json()
    action = data.get("action")
    
    if action == "eliminar":
        bodega_id = data.get("bodega_id")
        # Verificar si la bodega está vacía
        inventario = db.execute("SELECT COUNT(*) as total FROM Inventario_Bodega WHERE ID_Bodega = ?", bodega_id)
        
        if inventario[0]['total'] > 0:
            return jsonify({
                "success": False,
                "message": "No se puede eliminar la bodega porque contiene productos"
            })
        
        db.execute("DELETE FROM Bodegas WHERE ID_Bodega = ?", bodega_id)
        return jsonify({
            "success": True,
            "message": "Bodega eliminada correctamente"
        })
    
    elif action == "editar":
        bodega_id = data.get("bodega_id")
        nuevo_nombre = data.get("nuevo_nombre", "").strip()
        nueva_ubicacion = data.get("nueva_ubicacion", "").strip()
        
        if not nuevo_nombre:
            return jsonify({
                "success": False,
                "message": "El nombre de la bodega es obligatorio"
            })
        
        db.execute("UPDATE Bodegas SET Nombre = ?, Ubicacion = ? WHERE ID_Bodega = ?", 
                  nuevo_nombre, nueva_ubicacion, bodega_id)
        return jsonify({
            "success": True,
            "message": "Bodega actualizada correctamente"
        })
    
    return jsonify({"error": "Acción no válida"}), 400
#######################################################################################
@app.route("/inventario", methods=["GET", "POST"])
@login_required
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
#######################################################################################
@app.route("/historial_inventario")
@login_required
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
#######################################################################################
#ruta de vehiculos
@app.route("/vehiculos", methods=["GET", "POST"])
@login_required
def vehiculos():
    try:
        if request.method == "POST":
            # Datos del formulario con nueva estructura
            data = {
                'placa': request.form.get("placa", "").strip().upper(),
                'marca': request.form.get("marca", "").strip(),
                'modelo': request.form.get("modelo", "").strip(),
                'año': int(request.form.get("año", 0)) if request.form.get("año") else None,
                'color': request.form.get("color", "").strip(),
                'chasis': request.form.get("chasis", "").strip(),
                'motor': request.form.get("motor", "").strip(),
                'capacidad_carga': float(request.form.get("capacidad_carga", 0)),
                'estado': 'activo',  # Valor por defecto según nueva estructura
                'kilometraje': float(request.form.get("kilometraje", 0)),
                'fecha_adquisicion': request.form.get("fecha_adquisicion", "")
            }

            # Validación reforzada
            if not data['placa']:
                flash("La placa es obligatoria.", "danger")
                return redirect(url_for("vehiculos"))

            # Insertar usando NUEVA ESTRUCTURA
            db.execute("""
                INSERT INTO Vehiculos 
                (Placa, Marca, Modelo, Año, Color, NumeroChasis, NumeroMotor, 
                 Capacidad_Carga, Estado, Ultimo_Kilometraje, Fecha_Adquisicion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data['placa'], data['marca'], data['modelo'], data['año'],
                 data['color'], data['chasis'], data['motor'], data['capacidad_carga'],
                 data['estado'], data['kilometraje'], data['fecha_adquisicion'] or None)

            flash("Vehículo agregado correctamente.", "success")
            return redirect(url_for("vehiculos"))

        # GET: Listar vehículos con nueva estructura
        estado_filtro = request.args.get("estado", "activo")
        search = request.args.get("search", "").strip()

        query = """
            SELECT 
                ID_Vehiculo, Placa, Marca, Modelo, Año, Color, Estado,
                Capacidad_Carga, Ultimo_Kilometraje, Fecha_Adquisicion
            FROM Vehiculos
            WHERE 1=1
        """
        params = []

        if estado_filtro != "todos":
            query += " AND Estado = ?"
            params.append(estado_filtro)

        if search:
            query += " AND (Placa LIKE ? OR Marca LIKE ? OR Modelo LIKE ?)"
            params.extend([f"%{search}%"] * 3)

        query += " ORDER BY Placa ASC"
        vehiculos = db.execute(query, *params)

        return render_template("vehiculos.html", 
                            vehiculos=vehiculos,
                            estados=['activo', 'mantenimiento', 'inactivo', 'baja'],
                            estado_filtro=estado_filtro,
                            search=search)

    except ValueError:
        flash("Error en los datos numéricos proporcionados.", "danger")
        return redirect(url_for("vehiculos"))
    except Exception as e:
        flash(f"Error inesperado: {str(e)}", "danger")
        return redirect(url_for("vehiculos"))

##########################################################################

@app.route("/vehiculos/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar_vehiculo(id):
    try:
        # Obtener el vehículo con la nueva estructura
        vehiculo = db.execute("""
            SELECT 
                ID_Vehiculo, Placa, Marca, Modelo, Año, Color,
                NumeroChasis, NumeroMotor, Estado, Capacidad_Carga,
                Ultimo_Kilometraje, Fecha_Adquisicion
            FROM Vehiculos 
            WHERE ID_Vehiculo = ?
        """, id)
        
        if not vehiculo:
            flash("Vehículo no encontrado.", "danger")
            return redirect(url_for("vehiculos"))
        vehiculo = vehiculo[0]

        if request.method == "POST":
            # Recoger y validar datos del formulario
            data = {
                'placa': request.form.get("placa", "").strip().upper(),
                'marca': request.form.get("marca", "").strip(),
                'modelo': request.form.get("modelo", "").strip(),
                'año': request.form.get("año", ""),
                'color': request.form.get("color", "").strip(),
                'chasis': request.form.get("chasis", "").strip(),
                'motor': request.form.get("motor", "").strip(),
                'estado': request.form.get("estado", "activo"),
                'capacidad_carga': request.form.get("capacidad_carga", "0"),
                'kilometraje': request.form.get("kilometraje", "0"),
                'fecha_adquisicion': request.form.get("fecha_adquisicion", "")
            }

            # Validaciones
            errores = []
            
            if not data['placa']:
                errores.append("La placa es obligatoria")
                
            if data['año'] and not data['año'].isdigit():
                errores.append("El año debe ser un número válido")
                
            try:
                data['capacidad_carga'] = float(data['capacidad_carga'])
            except ValueError:
                errores.append("La capacidad de carga debe ser un número")
                
            try:
                data['kilometraje'] = float(data['kilometraje'])
            except ValueError:
                errores.append("El kilometraje debe ser un número válido")

            # Si hay errores, mostrarlos y recargar el formulario
            if errores:
                for error in errores:
                    flash(error, "danger")
                return render_template("editar_vehiculo.html", 
                                      vehiculo=vehiculo,
                                      estados=['activo', 'mantenimiento', 'inactivo', 'baja'])

            # Convertir año a entero si existe
            data['año'] = int(data['año']) if data['año'] else None

            # Actualizar el vehículo en la nueva estructura
            db.execute("""
                UPDATE Vehiculos SET
                    Placa = ?,
                    Marca = ?,
                    Modelo = ?,
                    Año = ?,
                    Color = ?,
                    NumeroChasis = ?,
                    NumeroMotor = ?,
                    Estado = ?,
                    Capacidad_Carga = ?,
                    Ultimo_Kilometraje = ?,
                    Fecha_Adquisicion = ?
                WHERE ID_Vehiculo = ?
            """, 
            data['placa'], data['marca'], data['modelo'], data['año'],
            data['color'], data['chasis'], data['motor'], data['estado'],
            data['capacidad_carga'], data['kilometraje'], 
            data['fecha_adquisicion'] if data['fecha_adquisicion'] else None,
            id)

            flash("Vehículo actualizado correctamente.", "success")
            return redirect(url_for("vehiculos"))

        # Mostrar formulario de edición
        return render_template("editar_vehiculo.html", 
                            vehiculo=vehiculo,
                            estados=['activo', 'mantenimiento', 'inactivo', 'baja'])

    except Exception as e:
        # Manejo de errores inesperados
        flash(f"Error al actualizar el vehículo: {str(e)}", "danger")
        return redirect(url_for("vehiculos"))
    
#######################################################################################
@app.route("/combustible", methods=["GET", "POST"])
@login_required
def combustible():
    try:
        if request.method == "POST":
            # Datos del formulario adaptados al esquema real
            data = {
                'fecha': request.form.get("fecha"),
                'id_vehiculo': request.form.get("vehiculo"),
                'monto': float(request.form.get("monto", 0)),
                'litros': float(request.form.get("litros", 0)) if request.form.get("litros") else None,
                'kilometraje': float(request.form.get("kilometraje", 0)) if request.form.get("kilometraje") else None,
                'observacion': request.form.get("observaciones", "").strip(),
                'id_bodega': request.form.get("bodega"),
                'id_empresa': 1  # Asumiendo un valor por defecto
            }

            # Validación
            if not all([data['fecha'], data['id_vehiculo'], data['monto'] > 0]):
                flash("Fecha, vehículo y monto son obligatorios.", "danger")
                return redirect(url_for("combustible"))

            # Insertar usando la estructura REAL de la tabla
            db.execute("""
                INSERT INTO Gastos_Combustible 
                (Fecha, ID_Vehiculo, Monto, Litros, Kilometraje, Observacion, ID_Bodega, ID_Empresa)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, data['fecha'], data['id_vehiculo'], data['monto'], data['litros'],
                 data['kilometraje'], data['observacion'], data['id_bodega'], data['id_empresa'])

            # Actualizar kilometraje del vehículo
            if data['kilometraje']:
                db.execute("""
                    UPDATE Vehiculos
                    SET Ultimo_Kilometraje = ?
                    WHERE ID_Vehiculo = ?
                """, data['kilometraje'], data['id_vehiculo'])

            flash("Registro de combustible guardado.", "success")
            return redirect(url_for("combustible"))

        # GET: Listar registros con filtros
        filtros = {
            'fecha': request.args.get("fecha"),
            'id_vehiculo': request.args.get("vehiculo"),
            'mes': request.args.get("mes")
        }

        query = """
            SELECT 
                gc.ID_Gasto, gc.Fecha, gc.Monto, gc.Litros,
                gc.Kilometraje, gc.Observacion,
                v.Placa, v.Marca, v.Modelo,
                b.Nombre AS Bodega
            FROM Gastos_Combustible gc
            JOIN Vehiculos v ON v.ID_Vehiculo = gc.ID_Vehiculo
            LEFT JOIN Bodegas b ON b.ID_Bodega = gc.ID_Bodega
            WHERE 1=1
        """
        params = []

        if filtros['fecha']:
            query += " AND gc.Fecha = ?"
            params.append(filtros['fecha'])
        elif filtros['mes']:
            query += " AND strftime('%Y-%m', gc.Fecha) = ?"
            params.append(filtros['mes'])
            
        if filtros['id_vehiculo']:
            query += " AND gc.ID_Vehiculo = ?"
            params.append(filtros['id_vehiculo'])
            
        query += " ORDER BY gc.Fecha DESC"

        gastos = db.execute(query, *params)
        vehiculos = db.execute("SELECT ID_Vehiculo, Placa FROM Vehiculos WHERE Estado = 'activo' ORDER BY Placa")
        bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas ORDER BY Nombre")

        return render_template(
            "combustible.html",
            gastos=gastos,
            vehiculos=vehiculos,
            bodegas=bodegas,
            filtros=filtros
        )

    except ValueError:
        flash("Error en los datos numéricos.", "danger")
        return redirect(url_for("combustible"))
    except Exception as e:
        flash(f"Error inesperado: {str(e)}", "danger")
        return redirect(url_for("combustible"))
    
######################################################################################

@app.route("/vehiculos/<int:id>/mantenimientos", methods=["GET", "POST"])
@login_required
def mantenimientos_vehiculo(id):
    try:
        # Verificar que el vehículo existe
        vehiculo = db.execute("SELECT ID_Vehiculo, Placa FROM Vehiculos WHERE ID_Vehiculo = ?", id)
        if not vehiculo:
            flash("Vehículo no encontrado.", "danger")
            return redirect(url_for("vehiculos"))
        vehiculo = vehiculo[0]

        if request.method == "POST":
            # Datos del formulario con nueva estructura
            data = {
                'tipo': request.form.get("tipo"),
                'fecha': request.form.get("fecha"),
                'descripcion': request.form.get("descripcion", "").strip(),
                'costo': float(request.form.get("costo", 0)),
                'kilometraje': float(request.form.get("kilometraje", 0)),
                'proveedor': request.form.get("proveedor", "").strip(),
                'observaciones': request.form.get("observaciones", "").strip()
            }

            # Validación
            if not all([data['tipo'], data['fecha']]):
                flash("Tipo y fecha son obligatorios.", "danger")
                return redirect(url_for("mantenimientos_vehiculo", id=id))

            # Insertar usando NUEVA ESTRUCTURA
            db.execute("""
                INSERT INTO Mantenimientos 
                (ID_Vehiculo, Tipo, Fecha, Descripcion, Costo, 
                 Kilometraje, Proveedor, Observaciones)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, id, data['tipo'], data['fecha'], data['descripcion'],
                 data['costo'], data['kilometraje'], data['proveedor'],
                 data['observaciones'])

            # Actualizar kilometraje del vehículo si es mayor al actual
            if data['kilometraje']:
                db.execute("""
                    UPDATE Vehiculos
                    SET Ultimo_Kilometraje = ?,
                        Fecha_Ultimo_Mantenimiento = ?
                    WHERE ID_Vehiculo = ? AND (Ultimo_Kilometraje < ? OR Ultimo_Kilometraje IS NULL)
                """, data['kilometraje'], data['fecha'], id, data['kilometraje'])

            flash("Mantenimiento registrado correctamente.", "success")
            return redirect(url_for("mantenimientos_vehiculo", id=id))

        # GET: Listar mantenimientos del vehículo
        mantenimientos = db.execute("""
            SELECT * FROM Mantenimientos
            WHERE ID_Vehiculo = ?
            ORDER BY Fecha DESC
        """, id)

        return render_template(
            "mantenimientos.html",
            vehiculo=vehiculo,
            mantenimientos=mantenimientos,
            tipos_mantenimiento=['preventivo', 'correctivo', 'revision', 'lavado', 'neumaticos', 'frenos']
        )

    except ValueError:
        flash("Error en los datos numéricos.", "danger")
        return redirect(url_for("mantenimientos_vehiculo", id=id))
    except Exception as e:
        flash(f"Error inesperado: {str(e)}", "danger")
        return redirect(url_for("mantenimientos_vehiculo", id=id))

#######################################################################################
@app.route("/clientes", methods=["GET", "POST"])
@login_required
def clientes():
    try:
        # Manejo del POST (agregar nuevo cliente)
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            telefono = request.form.get("telefono", "").strip()
            direccion = request.form.get("direccion", "").strip()
            ruc_cedula = request.form.get("ruc_cedula", "").strip()

            if not nombre:
                flash("El nombre del cliente es obligatorio.", "danger")
                return redirect(url_for("clientes"))
            
            # Verificar si el RUC/Cédula ya existe (solo si se proporcionó)
            if ruc_cedula:
                existe = db.execute("SELECT 1 FROM Clientes WHERE RUC_CEDULA = ?", ruc_cedula)
                if existe:
                    flash("Ya existe un cliente con este RUC/Cédula", "danger")
                    return redirect(url_for("clientes"))

            # Usar transacción para operación crítica
            try:
                db.execute("BEGIN TRANSACTION")
                db.execute("""
                    INSERT INTO Clientes (Nombre, Telefono, Direccion, RUC_CEDULA)
                    VALUES (?, ?, ?, ?)
                """, nombre, telefono, direccion, ruc_cedula)
                db.execute("COMMIT")
                flash("Cliente agregado correctamente.", "success")
            except Exception as e:
                db.execute("ROLLBACK")
                logging.error(f"Error al insertar cliente: {str(e)}")
                flash("Error al guardar el cliente", "danger")
            
            return redirect(url_for("clientes"))
        
        # Manejo del GET (listar clientes)
        page = request.args.get("page", 1, type=int)
        per_page = 20
        offset = (page - 1) * per_page
        
        search_query = request.args.get("q", "").strip()
        
        # Consulta optimizada con COUNT OVER() para evitar consulta adicional
        query = """
            SELECT *, COUNT(*) OVER() AS total_count 
            FROM Clientes
        """
        params = []
        
        if search_query:
            query += " WHERE Nombre LIKE ? OR RUC_CEDULA LIKE ? OR Telefono LIKE ?"
            search_param = f"%{search_query}%"
            params.extend([search_param, search_param, search_param])
        
        query += " ORDER BY Nombre LIMIT ? OFFSET ?"
        params.extend([per_page, offset])
        
        clientes = db.execute(query, *params)
        total = clientes[0]['total_count'] if clientes else 0
        
        return render_template("clientes.html", 
                            clientes=clientes, 
                            page=page,
                            per_page=per_page,
                            total=total,
                            search=search_query)

    except Exception as e:
        logging.error(f"Error en ruta /clientes: {str(e)}", exc_info=True)
        flash("Ocurrió un error al procesar la solicitud. Por favor intenta nuevamente.", "danger")
        return redirect(url_for("clientes"))
        
#######################################################################################
@app.template_filter('to_date')
def format_date(value, format='%d/%m/%Y', default='N/A'):
    """Filtro para formatear fechas en templates"""
    if not value or value == 'N/A':
        return default
    try:
        if isinstance(value, str):
            # Intenta parsear ambos formatos (BD y visualización)
            if '-' in value:  # Formato de BD (YYYY-MM-DD)
                parsed = datetime.strptime(value, '%Y-%m-%d')
            else:
                parsed = datetime.strptime(value, format)
            return parsed.strftime(format)
        elif isinstance(value, datetime):
            return value.strftime(format)
        return default
    except ValueError:
        return default

@app.route("/cliente/<int:id_cliente>")
@login_required
def detalle_cliente(id_cliente):
    try:
        # ==============================================
        # Funciones de ayuda
        # ==============================================
        def format_currency(amount, default='C$0.00'):
            """Formatea montos monetarios consistentemente"""
            if amount is None:
                return default
            try:
                return f"C${float(amount):,.2f}"
            except (ValueError, TypeError):
                return default

        # ==============================================
        # 1. Datos básicos del cliente
        # ==============================================
        cliente_info = db.execute("""
            SELECT 
                c.*,
                (SELECT COUNT(*) FROM Facturacion WHERE IDCliente = c.ID_Cliente) + 
                (SELECT COUNT(*) FROM Factura_Alterna WHERE IDCliente = c.ID_Cliente) AS total_facturas,
                (SELECT COALESCE(SUM(Saldo_Pendiente), 0) FROM Detalle_Cuentas_Por_Cobrar 
                 WHERE ID_Cliente = c.ID_Cliente) AS total_pendiente,
                (SELECT COUNT(*) FROM Detalle_Cuentas_Por_Cobrar 
                 WHERE ID_Cliente = c.ID_Cliente AND Saldo_Pendiente > 0) AS facturas_pendientes,
                (SELECT MAX(Fecha) FROM (
                    SELECT Fecha FROM Facturacion WHERE IDCliente = c.ID_Cliente
                    UNION ALL
                    SELECT Fecha FROM Factura_Alterna WHERE IDCliente = c.ID_Cliente
                )) AS ultima_compra,
                (SELECT MIN(Fecha) FROM Facturacion WHERE IDCliente = c.ID_Cliente) AS fecha_primer_compra
            FROM Clientes c
            WHERE c.ID_Cliente = ?
            LIMIT 1
        """, id_cliente)

        if not cliente_info:
            flash("Cliente no encontrado", "danger")
            return redirect(url_for("clientes"))
            
        cliente_info = cliente_info[0]
        
        # Formatear campos
        cliente_info['total_pendiente'] = format_currency(cliente_info['total_pendiente'])
        cliente_info['ultima_compra'] = format_date(cliente_info['ultima_compra'])
        cliente_info['fecha_primer_compra'] = format_date(cliente_info['fecha_primer_compra'])

        # ==============================================
        # 2. Cuentas por cobrar (Consulta optimizada)
        # ==============================================
        cuentas_por_cobrar = db.execute("""
            WITH documentos AS (
                SELECT 
                    f.ID_Factura AS id, 
                    f.Fecha, 
                    'Factura' AS tipo,
                    f.IDCliente
                FROM Facturacion f  
                WHERE f.IDCliente = ?
                
                UNION ALL
                
                SELECT 
                    fa.ID_Factura AS id, 
                    fa.Fecha, 
                    'Factura Alterna' AS tipo,
                    fa.IDCliente
                FROM Factura_Alterna fa
                WHERE fa.IDCliente = ?
            ),
            pagos_agrupados AS (
                SELECT 
                    p.ID_Movimiento,
                    GROUP_CONCAT(strftime('%d/%m/%Y', p.Fecha) || ' - ' || printf('C$%.2f', p.Monto), ' | ') AS pagos,
                    SUM(p.Monto) AS total_pagado
                FROM Pagos_CuentasCobrar p
                GROUP BY p.ID_Movimiento
            )
            SELECT 
                d.ID_Movimiento,
                d.Num_Documento,
                COALESCE(doc.tipo, 'Otro documento') || '#' || d.Num_Documento AS Documento,
                strftime('%d/%m/%Y', COALESCE(doc.Fecha, d.Fecha)) AS Fecha,
                strftime('%d/%m/%Y', d.Fecha_Vencimiento) AS Vencimiento,
                ROUND(d.Saldo_Pendiente, 2) AS Monto_Original,
                ROUND(COALESCE(p.total_pagado, 0), 2) AS Total_Abonado,
                ROUND(d.Saldo_Pendiente - COALESCE(p.total_pagado, 0), 2) AS Saldo_Pendiente,
                CASE
                    WHEN (d.Saldo_Pendiente - COALESCE(p.total_pagado, 0)) <= 0 THEN 'Pagada'
                    WHEN d.Fecha_Vencimiento < date('now') THEN 'Vencida'
                    ELSE 'Vigente'
                END AS Estado,
                COALESCE(p.pagos, 'Sin pagos') AS Pagos_Realizados,
                c.Nombre AS Nombre_Cliente
            FROM Detalle_Cuentas_Por_Cobrar d
            JOIN Clientes c ON d.ID_Cliente = c.ID_Cliente
            LEFT JOIN documentos doc ON doc.id = d.Num_Documento AND doc.IDCliente = d.ID_Cliente
            LEFT JOIN pagos_agrupados p ON p.ID_Movimiento = d.ID_Movimiento
            WHERE d.ID_Cliente = ?
            ORDER BY 
                CASE 
                    WHEN (d.Monto_Movimiento - COALESCE(p.total_pagado, 0)) <= 0 THEN 2 
                    WHEN d.Fecha_Vencimiento < date('now') THEN 0 
                    ELSE 1 
                END,
                d.Fecha_Vencimiento ASC
        """, id_cliente, id_cliente, id_cliente)

        # Formatear y calcular días para vencimiento
        for cuenta in cuentas_por_cobrar:
            cuenta['Monto_Original'] = format_currency(cuenta['Monto_Original'])
            cuenta['Total_Abonado'] = format_currency(cuenta['Total_Abonado'])
            cuenta['Saldo_Pendiente'] = format_currency(cuenta['Saldo_Pendiente'])
            
            try:
                if cuenta['Estado'] == 'Vencida':
                    cuenta['dias_vencimiento'] = "Vencida"
                elif cuenta.get('Vencimiento'):
                    fecha_venc = datetime.strptime(cuenta['Vencimiento'], '%d/%m/%Y')
                    dias = (fecha_venc - datetime.now()).days
                    cuenta['dias_vencimiento'] = f"Vence en {dias} días" if dias > 0 else "Vencida"
                else:
                    cuenta['dias_vencimiento'] = "Sin fecha"
            except:
                cuenta['dias_vencimiento'] = "Error en fecha"

        # ==============================================
        # 3. Crear Trigger para actualización automática
        # ==============================================
        try:
            db.execute("""
                CREATE TRIGGER IF NOT EXISTS actualizar_saldo_despues_pago
                AFTER INSERT ON Pagos_CuentasCobrar
                FOR EACH ROW
                BEGIN
                    -- Bloqueo para evitar condiciones de carrera
                    BEGIN IMMEDIATE;
                    UPDATE Detalle_Cuentas_Por_Cobrar
                    SET Saldo_Pendiente = (
                        SELECT d.Monto_Movimiento - COALESCE(SUM(p.Monto), 0)
                        FROM Pagos_CuentasCobrar p
                        WHERE p.ID_Movimiento = NEW.ID_Movimiento
                    )
                    WHERE ID_Movimiento = NEW.ID_Movimiento;
                    COMMIT;
                END;
            """)
        except Exception as e:
            logging.warning(f"Trigger no pudo crearse: {str(e)}")

        # ==============================================
        # 4. Historial de compras (últimas 10)
        # ==============================================
        historial_compras = db.execute("""
            WITH compras AS (
                SELECT 
                    f.ID_Factura AS id,
                    f.Fecha,
                    ROUND(SUM(df.Total), 2) AS Total,
                    f.Credito_Contado AS Tipo,
                    'Factura' AS Documento
                FROM Facturacion f
                JOIN Detalle_Facturacion df ON f.ID_Factura = df.ID_Factura
                WHERE f.IDCliente = ?
                GROUP BY f.ID_Factura

                UNION ALL

                SELECT 
                    fa.ID_Factura AS id,
                    fa.Fecha,
                    ROUND(SUM(dfa.Total), 2) AS Total,
                    fa.Credito_Contado AS Tipo,
                    'Factura Alterna' AS Documento
                FROM Factura_Alterna fa
                JOIN Detalle_Factura_Alterna dfa ON fa.ID_Factura = dfa.ID_Factura
                WHERE fa.IDCliente = ?
                GROUP BY fa.ID_Factura
            )
            SELECT * FROM compras
            ORDER BY Fecha DESC
            LIMIT 10
        """, id_cliente, id_cliente)

        for compra in historial_compras:
            compra['Fecha'] = format_date(compra.get('Fecha'))
            compra['Total'] = format_currency(compra.get('Total'))

        # ==============================================
        # 5. Productos más comprados (Top 5)
        # ==============================================
        productos_frecuentes = db.execute("""
            SELECT 
                p.ID_Producto,
                p.Descripcion,
                p.COD_Producto,
                COUNT(*) AS veces_comprado,
                ROUND(SUM(df.Cantidad), 2) AS cantidad_total,
                ROUND(SUM(df.Total), 2) AS monto_total,
                ROUND(SUM(df.Total)/SUM(df.Cantidad), 2) AS precio_promedio,
                p.Unidad_Medida,
                um.Abreviatura AS unidad_abreviatura
            FROM (
                SELECT df.ID_Producto, df.Cantidad, df.Total 
                FROM Facturacion f
                JOIN Detalle_Facturacion df ON f.ID_Factura = df.ID_Factura
                WHERE f.IDCliente = ?
                
                UNION ALL
                
                SELECT dfa.ID_Producto, dfa.Cantidad, dfa.Total
                FROM Factura_Alterna fa
                JOIN Detalle_Factura_Alterna dfa ON fa.ID_Factura = dfa.ID_Factura
                WHERE fa.IDCliente = ?
            ) df
            JOIN Productos p ON df.ID_Producto = p.ID_Producto
            LEFT JOIN Unidades_Medida um ON p.Unidad_Medida = um.ID_Unidad
            GROUP BY p.ID_Producto
            ORDER BY cantidad_total DESC
            LIMIT 5
        """, id_cliente, id_cliente)

        for producto in productos_frecuentes:
            producto['monto_total'] = format_currency(producto.get('monto_total'))
            producto['precio_promedio'] = format_currency(producto.get('precio_promedio'))

        # ==============================================
        # 6. Historial de pagos (últimos 10)
        # ==============================================
        historial_pagos = db.execute("""
            SELECT 
                p.ID_Pago,
                p.Fecha,
                ROUND(p.Monto, 2) AS Monto,
                mp.Nombre AS metodo_pago,
                p.Comentarios,
                d.Num_Documento AS documento_relacionado,
                d.Fecha AS fecha_documento,
                ROUND(d.Monto_Movimiento, 2) AS monto_documento,
                CASE 
                    WHEN EXISTS (SELECT 1 FROM Facturacion f WHERE f.ID_Factura = d.Num_Documento) 
                        THEN 'Factura'
                    WHEN EXISTS (SELECT 1 FROM Factura_Alterna fa WHERE fa.ID_Factura = d.Num_Documento) 
                        THEN 'Factura Alterna'
                    ELSE 'Otro'
                END AS tipo_documento
            FROM Pagos_CuentasCobrar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            JOIN Detalle_Cuentas_Por_Cobrar d ON p.ID_Movimiento = d.ID_Movimiento
            WHERE d.ID_Cliente = ?
            ORDER BY p.Fecha DESC
            LIMIT 10
        """, id_cliente)

        for pago in historial_pagos:
            pago['Fecha'] = format_date(pago.get('Fecha'))
            pago['fecha_documento'] = format_date(pago.get('fecha_documento'))
            pago['Monto'] = format_currency(pago.get('Monto'))
            pago['monto_documento'] = format_currency(pago.get('monto_documento'))

        # ==============================================
        # 7. Estadísticas financieras
        # ==============================================
        estadisticas = db.execute("""
            WITH todas_compras AS (
                SELECT f.Fecha, ROUND(SUM(df.Total), 2) AS Total FROM Facturacion f
                JOIN Detalle_Facturacion df ON f.ID_Factura = df.ID_Factura
                WHERE f.IDCliente = ?
                GROUP BY f.ID_Factura
                
                UNION ALL
                
                SELECT fa.Fecha, ROUND(SUM(dfa.Total), 2) AS Total FROM Factura_Alterna fa
                JOIN Detalle_Factura_Alterna dfa ON fa.ID_Factura = dfa.ID_Factura
                WHERE fa.IDCliente = ?
                GROUP BY fa.ID_Factura
            )
            SELECT 
                COUNT(*) AS total_compras,
                ROUND(SUM(Total), 2) AS monto_total,
                ROUND(AVG(Total), 2) AS promedio_compra,
                MIN(Fecha) AS primera_compra,
                MAX(Fecha) AS ultima_compra,
                ROUND((SELECT SUM(Total) FROM todas_compras 
                 WHERE strftime('%Y', Fecha) = strftime('%Y', date('now'))), 2) AS monto_anual,
                ROUND((SELECT SUM(Total) FROM todas_compras 
                 WHERE strftime('%Y-%m', Fecha) = strftime('%Y-%m', date('now'))), 2) AS monto_mensual
            FROM todas_compras
        """, id_cliente, id_cliente)

        if estadisticas:
            estadisticas = estadisticas[0]
            for key in ['monto_total', 'promedio_compra', 'monto_anual', 'monto_mensual']:
                estadisticas[key] = format_currency(estadisticas.get(key))
            for key in ['primera_compra', 'ultima_compra']:
                estadisticas[key] = format_date(estadisticas.get(key))

        # ==============================================
        # Renderizar template
        # ==============================================
        return render_template(
            "detalle_cliente.html",
            cliente=cliente_info,
            cuentas_por_cobrar=cuentas_por_cobrar,
            historial_compras=historial_compras,
            productos_frecuentes=productos_frecuentes,
            historial_pagos=historial_pagos,
            estadisticas=estadisticas if estadisticas else {},
            now=datetime.now(),
            format_date=format_date,
            format_currency=format_currency
        )

    except Exception as e:
        logging.error(f"Error en detalle_cliente {id_cliente}: {str(e)}", exc_info=True)
        flash("Error técnico al cargar el detalle del cliente", "danger")
        return redirect(url_for("clientes"))

@app.route("/historial_pagos_cliente/<int:id_cliente>")
@login_required
def historial_pagos_cliente(id_cliente):
    try:
        facturas = db.execute("""
            SELECT ID_Movimiento 
            FROM Detalle_Cuentas_Por_Cobrar 
            WHERE ID_Cliente = ? AND Saldo_Pendiente > 0
            LIMIT 1
        """, id_cliente)
        
        if not facturas:
            flash("El cliente no tiene facturas pendientes", "info")
            return redirect(url_for("detalle_cliente", id_cliente=id_cliente))
            
        return redirect(url_for("historial_pagos", id_movimiento=facturas[0]["ID_Movimiento"]))
        
    except Exception as e:
        flash(f"Error al cargar historial de pagos: {str(e)}", "danger")
        return redirect(url_for("detalle_cliente", id_cliente=id_cliente))

#######################################################################################
# Editar Cliente
@app.route("/clientes/<int:id>/editar", methods=["GET", "POST"])
@login_required
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
#######################################################################################
# Eliminar Cliente
@app.route("/clientes/<int:id>/eliminar")
@login_required
def eliminar_cliente(id):

    db.execute("DELETE FROM Clientes WHERE ID_Cliente = ?", id)
    flash("Cliente eliminado correctamente.", "success")
    return redirect(url_for("clientes"))
#######################################################################################
# Añadir Proveedor
@app.route("/proveedores", methods=["GET", "POST"])
@login_required
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

    proveedores = db.execute("SELECT * FROM Proveedores ORDER BY ID_Proveedor")
    return render_template("proveedores.html", proveedores=proveedores)
#######################################################################################
@app.route("/proveedores/<int:id_proveedor>")
@login_required
def detalle_proveedor(id_proveedor):
    try:
        # 1. Obtener información básica del proveedor (modificado para CS50 SQL)
        proveedor = db.execute("SELECT * FROM Proveedores WHERE ID_Proveedor = ?", id_proveedor)
        if not proveedor:  # Ahora proveedor es una lista
            flash("Proveedor no encontrado", "danger")
            return redirect(url_for("proveedores"))
        proveedor = proveedor[0]  # Tomamos el primer elemento

        # 2. Obtener cuentas por pagar (modificado)
        cuentas_pendientes = db.execute("""
            SELECT 
                cp.ID_Cuenta,
                cp.Fecha,
                cp.Num_Documento,
                cp.Observacion AS Descripcion,
                cp.Fecha_Vencimiento,
                cm.Descripcion AS Tipo_Movimiento,
                cp.Monto_Movimiento AS Total,
                cp.IVA,
                cp.Retencion,
                cp.Saldo_Pendiente,
                CASE 
                    WHEN cp.Fecha_Vencimiento < date('now') AND cp.Saldo_Pendiente > 0 THEN 'Vencido'
                    WHEN cp.Saldo_Pendiente > 0 THEN 'Pendiente'
                    ELSE 'Pagado'
                END AS Estado
            FROM Cuentas_Por_Pagar cp
            JOIN Catalogo_Movimientos cm ON cp.Tipo_Movimiento = cm.ID_TipoMovimiento
            WHERE cp.ID_Proveedor = ?
            ORDER BY cp.Fecha DESC
        """, id_proveedor)  # Sin fetchall()

        # 3. Obtener historial de compras (modificado)
        historial_compras = db.execute("""
            SELECT 
                mi.ID_Movimiento,
                mi.Fecha,
                mi.N_Factura AS Factura,
                cm.Descripcion AS Tipo,
                SUM(dmi.Costo_Total) AS Total,
                mi.Observacion,
                e.Descripcion AS Empresa,
                b.Nombre AS Bodega
            FROM Movimientos_Inventario mi
            JOIN Catalogo_Movimientos cm ON mi.ID_TipoMovimiento = cm.ID_TipoMovimiento
            JOIN Detalle_Movimiento_Inventario dmi ON mi.ID_Movimiento = dmi.ID_Movimiento
            JOIN Empresa e ON mi.ID_Empresa = e.ID_Empresa
            LEFT JOIN Bodegas b ON mi.ID_Bodega = b.ID_Bodega
            WHERE mi.ID_Proveedor = ?
            GROUP BY mi.ID_Movimiento
            ORDER BY mi.Fecha DESC
        """, id_proveedor)  # Sin fetchall()

        # 4. Obtener productos más comprados (modificado)
        productos_top = db.execute("""
            SELECT 
                p.ID_Producto,
                p.COD_Producto AS Codigo,
                p.Descripcion,
                um.Descripcion AS Unidad,
                COUNT(dmi.ID_Producto) AS Veces_Comprado,
                SUM(dmi.Cantidad) AS Cantidad_Total,
                SUM(dmi.Costo_Total) AS Monto_Total,
                ROUND(SUM(dmi.Costo_Total) / SUM(dmi.Cantidad), 2) AS Precio_Promedio
            FROM Detalle_Movimiento_Inventario dmi
            JOIN Productos p ON dmi.ID_Producto = p.ID_Producto
            JOIN Unidades_Medida um ON p.Unidad_Medida = um.ID_Unidad
            JOIN Movimientos_Inventario mi ON dmi.ID_Movimiento = mi.ID_Movimiento
            WHERE mi.ID_Proveedor = ?
            GROUP BY dmi.ID_Producto
            ORDER BY Monto_Total DESC
            LIMIT 10
        """, id_proveedor)  # Sin fetchall()

        # 5. Obtener historial de pagos realizados (modificado)
        historial_pagos = db.execute("""
            SELECT 
                p.ID_Pago,
                p.Fecha,
                p.Monto,
                mp.Nombre AS Metodo_Pago,
                p.Detalles_Metodo AS Detalles,
                p.Comentarios,
                cp.Num_Documento AS Documento,
                cp.Fecha AS Fecha_Documento,
                cp.Monto_Movimiento AS Total_Documento
            FROM Pagos_CuentasPagar p
            JOIN Metodos_Pago mp ON p.ID_MetodoPago = mp.ID_MetodoPago
            JOIN Cuentas_Por_Pagar cp ON p.ID_Cuenta = cp.ID_Cuenta
            WHERE cp.ID_Proveedor = ?
            ORDER BY p.Fecha DESC
        """, id_proveedor)  # Sin fetchall()

        # 6. Calcular resumen financiero (modificado)
        resumen = db.execute("""
            SELECT 
                SUM(CASE WHEN Saldo_Pendiente > 0 THEN Saldo_Pendiente ELSE 0 END) AS Total_Pendiente,
                SUM(CASE WHEN Saldo_Pendiente > 0 AND Fecha_Vencimiento < date('now') 
                    THEN Saldo_Pendiente ELSE 0 END) AS Total_Vencido,
                SUM(Monto_Movimiento) AS Total_Compras,
                (SELECT SUM(Monto) FROM Pagos_CuentasPagar p 
                 JOIN Cuentas_Por_Pagar cp ON p.ID_Cuenta = cp.ID_Cuenta 
                 WHERE cp.ID_Proveedor = ?) AS Total_Pagado
            FROM Cuentas_Por_Pagar
            WHERE ID_Proveedor = ?
        """, id_proveedor, id_proveedor)[0]  # [0] para obtener el primer resultado

        return render_template(
            "detalle_proveedor.html",
            proveedor=proveedor,
            cuentas_pendientes=cuentas_pendientes,
            historial_compras=historial_compras,
            productos_top=productos_top,
            historial_pagos=historial_pagos,
            resumen=resumen
        )
        
    except Exception as e:
        flash(f"Error al cargar el proveedor: {str(e)}", "danger")
        return redirect(url_for("proveedores"))
    
#######################################################################################
# Editar Proveedor
@app.route("/proveedores/<int:id_proveedor>/editar", methods=["GET", "POST"])
@login_required
def editar_proveedor(id_proveedor):
    # Obtener el proveedor (db.execute devuelve una lista de diccionarios)
    proveedores = db.execute("SELECT * FROM Proveedores WHERE ID_Proveedor = ?", id_proveedor)
    
    # Verificar si se encontró el proveedor
    if len(proveedores) != 1:
        flash("Proveedor no encontrado.", "danger")
        return redirect(url_for("proveedores"))
    
    proveedor = proveedores[0]  # Tomamos el primer (y único) resultado

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        ruc_cedula = request.form.get("ruc_cedula", "").strip()

        # Actualizar el proveedor en la base de datos
        db.execute("""
            UPDATE Proveedores
            SET Nombre = ?, Telefono = ?, Direccion = ?, RUC_CEDULA = ?
            WHERE ID_Proveedor = ?
        """, nombre, telefono, direccion, ruc_cedula, id_proveedor)
        
        flash("Proveedor actualizado correctamente.", "success")
        return redirect(url_for("detalle_proveedor", id_proveedor=id_proveedor))

    # Pasar el diccionario del proveedor a la plantilla
    return render_template("editar_proveedor.html", proveedor=proveedor)
#######################################################################################
# Eliminar Proveedor
@app.route("/proveedores/<int:id>/eliminar")
@login_required
def eliminar_proveedor(id):
    db.execute("DELETE FROM Proveedores WHERE ID_Proveedor = ?", id)
    flash("Proveedor eliminado correctamente.", "success")
    return redirect(url_for("proveedores"))
#######################################################################################
# Añadir Empresa (generalmente se gestiona solo una, pero igual aquí)
@app.route("/empresa", methods=["GET", "POST"])
@login_required
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
#######################################################################################
# Editar Empresa
@app.route("/empresa/<int:id>/editar", methods=["GET", "POST"])
@login_required
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
#######################################################################################
# Eliminar Empresa
@app.route("/empresa/<int:id>/eliminar")
@login_required
def eliminar_empresa(id):
    db.execute("DELETE FROM Empresa WHERE ID_Empresa = ?", id)
    flash("Empresa eliminada correctamente.", "success")
    return redirect(url_for("empresa"))
#######################################################################################
# Listar y Agregar Producto
@app.route("/productos", methods=["GET", "POST"])
@login_required
def productos():
    """
    Ruta para gestionar productos: listar, agregar nuevos productos
    """
    if request.method == "POST":
        try:
            # Obtener datos del formulario
            cod = request.form.get("cod_producto", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            unidad = request.form.get("unidad")
            familia = request.form.get("familia") or None
            tipo = request.form.get("tipo") or None
            
            # Convertir valores numéricos con manejo de errores
            try:
                costo_promedio = float(request.form.get("costo_promedio", 0))
                precio_venta = float(request.form.get("precio_venta", 0))
                existencias = float(request.form.get("existencias", 0))
                estado = int(request.form.get("estado", 1))
            except ValueError:
                flash("Los valores numéricos son inválidos. Verifique los datos ingresados.", "danger")
                return redirect(url_for("productos"))
            
            iva = 1 if request.form.get("iva") else 0
            id_bodega = request.form.get("bodega")
            id_empresa = session.get("id_empresa", 1)  # Obtener de sesión o usar valor predeterminado
            
            # Validaciones básicas
            if not descripcion or not unidad or not id_bodega:
                flash("Descripción, unidad y bodega son obligatorias.", "danger")
                return redirect(url_for("productos"))
                
            # Validar valores numéricos
            if costo_promedio < 0 or precio_venta < 0 or existencias < 0:
                flash("Los valores numéricos no pueden ser negativos.", "danger")
                return redirect(url_for("productos"))
                
            # Validar longitud de campos
            if len(descripcion) > 100:  # Ajustar según la definición de tu BD
                flash("La descripción es demasiado larga.", "danger")
                return redirect(url_for("productos"))
                
            # Iniciar transacción y realizar inserciones
            try:
                # Iniciar transacción
                db.execute("BEGIN TRANSACTION")
                
                # Insertar producto
                db.execute("""
                    INSERT INTO Productos (
                        COD_Producto, Descripcion, Unidad_Medida, Existencias,
                        Estado, Familia, Costo_Promedio, IVA, Tipo, Precio_Venta, ID_Empresa
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, cod, descripcion, unidad, existencias, estado, familia, costo_promedio, iva, tipo, precio_venta, id_empresa)
                
                # Obtener el ID del nuevo producto - CORREGIDO
                resultado = db.execute("SELECT last_insert_rowid() AS id")
                
                # Manejar diferentes tipos de retorno de db.execute()
                if isinstance(resultado, list):
                    # Si db.execute() devuelve una lista de diccionarios
                    if resultado and len(resultado) > 0:
                        producto_id = resultado[0]["id"]
                    else:
                        raise Exception("No se pudo obtener el ID del producto insertado")
                else:
                    # Si db.execute() devuelve un objeto cursor u otro objeto
                    try:
                        # Intentar usar fetchone() si está disponible
                        row = resultado.fetchone()
                        producto_id = row["id"]
                    except (AttributeError, TypeError):
                        # Si no tiene fetchone() o hay otro error
                        raise Exception("No se pudo obtener el ID del producto insertado")
                
                # Insertar en Inventario_Bodega
                db.execute("""
                    INSERT INTO Inventario_Bodega (ID_Bodega, ID_Producto, Existencias)
                    VALUES (?, ?, ?)
                """, id_bodega, producto_id, existencias)
                
                # Confirmar transacción
                db.execute("COMMIT")
                flash("Producto agregado correctamente en la bodega.", "success")
            except Exception as e:
                # Revertir en caso de error
                try:
                    db.execute("ROLLBACK")
                except:
                    pass  # Ignorar errores en el rollback
                flash(f"Error al guardar el producto: {str(e)}", "danger")
                
        except Exception as e:
            flash(f"Error inesperado: {str(e)}", "danger")
            
        return redirect(url_for("productos"))

    # Obtener datos para el formulario (GET request)
    try:
        # Consulta para obtener productos con información relacionada
        productos = db.execute("""
            SELECT P.*, U.Descripcion AS Unidad, F.Descripcion AS FamiliaDesc, T.Descripcion AS TipoDesc
            FROM Productos P
            LEFT JOIN Unidades_Medida U ON P.Unidad_Medida = U.ID_Unidad
            LEFT JOIN Familia F ON P.Familia = F.ID_Familia
            LEFT JOIN Tipo_Producto T ON P.Tipo = T.ID_TipoProducto
            ORDER BY P.cod_producto
        """)
        
        # Consultas para obtener datos de formularios
        unidades = db.execute("SELECT ID_Unidad, Descripcion FROM Unidades_Medida ORDER BY Descripcion")
        familias = db.execute("SELECT ID_Familia, Descripcion FROM Familia ORDER BY Descripcion")
        tipos = db.execute("SELECT ID_TipoProducto, Descripcion FROM Tipo_Producto ORDER BY Descripcion")
        bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas ORDER BY Nombre")
        
        # Asegurarse de que los resultados sean iterables
        if not isinstance(productos, (list, tuple)) and hasattr(productos, 'fetchall'):
            productos = productos.fetchall()
        if not isinstance(unidades, (list, tuple)) and hasattr(unidades, 'fetchall'):
            unidades = unidades.fetchall()
        if not isinstance(familias, (list, tuple)) and hasattr(familias, 'fetchall'):
            familias = familias.fetchall()
        if not isinstance(tipos, (list, tuple)) and hasattr(tipos, 'fetchall'):
            tipos = tipos.fetchall()
        if not isinstance(bodegas, (list, tuple)) and hasattr(bodegas, 'fetchall'):
            bodegas = bodegas.fetchall()
            
    except Exception as e:
        flash(f"Error al cargar los datos: {str(e)}", "danger")
        # Proporcionar valores predeterminados vacíos
        productos = []
        unidades = []
        familias = []
        tipos = []
        bodegas = []

    # Renderizar plantilla con los datos
    return render_template(
        "productos.html", 
        productos=productos, 
        unidades=unidades, 
        familias=familias, 
        tipos=tipos, 
        bodegas=bodegas
    )
#######################################################################################
# Editar Producto
@app.route("/productos/<int:id>/editar", methods=["GET", "POST"])
@login_required
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
#######################################################################################
# Eliminar Producto
@app.route("/productos/<int:id>/eliminar")
@login_required
def eliminar_producto(id):
    db.execute("DELETE FROM Productos WHERE ID_Producto = ?", id)
    flash("Producto eliminado correctamente.", "success")
    return redirect(url_for("productos"))
#######################################################################################
# Listar y Agregar Familia
@app.route("/familia", methods=["GET", "POST"])
@login_required
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
#######################################################################################
# Editar Familia
@app.route("/familia/<int:id>/editar", methods=["GET", "POST"])
@login_required
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
#######################################################################################
# Listar y Agregar Tipo de Producto
@app.route("/tipo_producto", methods=["GET", "POST"])
@login_required
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
#######################################################################################
# Editar Tipo de Producto
@app.route("/tipo_producto/<int:id>/editar", methods=["GET", "POST"])
@login_required
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
#######################################################################################

@app.route("/rutas")
@login_required
def gestionar_rutas():
    """Listar todas las rutas"""
    rutas = db.execute("SELECT * FROM Rutas ORDER BY Nombre")
    return render_template("gestionar_rutas.html", rutas=rutas)

@app.route("/rutas/crear", methods=["GET", "POST"])
@login_required
def crear_ruta():
    """Crear una nueva ruta"""
    if request.method == "POST":
        nombre = request.form.get("nombre")
        descripcion = request.form.get("descripcion")
        zona = request.form.get("zona")
        dias = request.form.get("dias_operacion")

        if not nombre:
            flash("El nombre de la ruta es obligatorio", "danger")
            return redirect("/rutas/crear")

        db.execute(
            "INSERT INTO Rutas (Nombre, Descripcion, Zona, Dias_operacion, Estado) VALUES (?, ?, ?, ?, 1)",
            nombre, descripcion, zona, dias
        )
        flash("Ruta creada exitosamente", "success")
        return redirect("/rutas")

    return render_template("rutas.html")

@app.route("/rutas/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar_ruta(id):
    """Editar una ruta existente"""
    ruta = db.execute("SELECT * FROM Rutas WHERE ID_Ruta = ?", id)
    if not ruta:
        flash("Ruta no encontrada", "danger")
        return redirect("/rutas")

    if request.method == "POST":
        nombre = request.form.get("nombre")
        descripcion = request.form.get("descripcion")
        zona = request.form.get("zona")
        dias = request.form.get("dias_operacion")
        estado = 1 if request.form.get("estado") else 0

        db.execute(
            "UPDATE Rutas SET Nombre = ?, Descripcion = ?, Zona = ?, Dias_operacion = ?, Estado = ? WHERE ID_Ruta = ?",
            nombre, descripcion, zona, dias, estado, id
        )
        flash("Ruta actualizada exitosamente", "success")
        return redirect("/rutas")

    return render_template("editar_rutas.html", ruta=ruta[0])

@app.route("/rutas/<int:id>/eliminar", methods=["POST"])
@login_required
def eliminar_ruta(id):
    """Eliminar una ruta"""
    # Verificar si tiene sesiones asociadas
    sesiones = db.execute("SELECT COUNT(*) as total FROM Sesiones_Ruta WHERE ID_Ruta = ?", id)
    if sesiones[0]["total"] > 0:
        flash("No se puede eliminar: la ruta tiene sesiones asociadas", "danger")
        return redirect("/rutas")

    db.execute("DELETE FROM Rutas WHERE ID_Ruta = ?", id)
    flash("Ruta eliminada exitosamente", "success")
    return redirect("/rutas")

@app.route("/sesiones")
@login_required
def listar_sesiones():
    """Listar todas las sesiones de ruta"""
    sesiones = db.execute("""
        SELECT sr.*, r.Nombre as Ruta, v.Placa, c.Nombre as Conductor
        FROM Sesiones_Ruta sr
        JOIN Rutas r ON sr.ID_Ruta = r.ID_Ruta
        JOIN Vehiculos v ON sr.ID_Vehiculo = v.ID_Vehiculo
        LEFT JOIN Conductores c ON sr.ID_Conductor = c.ID_Conductor
        ORDER BY sr.Fecha DESC, sr.Hora_Inicio DESC
    """)
    return render_template("sesion_rutas.html", sesiones=sesiones, estados=get_estados_sesion())

def get_estados_sesion():
    return ['pendiente', 'en_ruta', 'completada', 'cancelada']

@app.route("/sesiones/crear", methods=["GET", "POST"])
@login_required
def crear_sesion():
    """Crear nueva sesión de ruta"""
    if request.method == "POST":
        id_ruta = request.form.get("id_ruta")
        id_vehiculo = request.form.get("id_vehiculo")
        id_conductor = request.form.get("id_conductor")
        fecha = request.form.get("fecha")
        hora_inicio = request.form.get("hora_inicio")
        kilometraje = request.form.get("kilometraje")

        if not all([id_ruta, id_vehiculo, id_conductor, fecha, hora_inicio]):
            flash("Todos los campos son obligatorios", "danger")
            return redirect("/sesiones/crear")

        # Verificar disponibilidad del vehículo
        vehiculo_ocupado = db.execute("""
            SELECT * FROM Sesiones_Ruta 
            WHERE ID_Vehiculo = ? AND Estado = 'en_ruta' AND Fecha = ?
        """, id_vehiculo, fecha)

        if vehiculo_ocupado:
            flash("El vehículo ya está asignado a otra ruta en esta fecha", "danger")
            return redirect("/sesiones/crear")

        db.execute("""
            INSERT INTO Sesiones_Ruta 
            (ID_Ruta, ID_Vehiculo, ID_Conductor, Fecha, Hora_Inicio, Kilometraje_Inicial, Estado)
            VALUES (?, ?, ?, ?, ?, ?, 'pendiente')
        """, id_ruta, id_vehiculo, id_conductor, fecha, hora_inicio, kilometraje)

        flash("Sesión de ruta creada exitosamente", "success")
        return redirect("/sesiones")

    rutas = db.execute("SELECT * FROM Rutas WHERE Estado = 1")
    vehiculos = db.execute("SELECT * FROM Vehiculos WHERE Estado = 'disponible'")
    conductores = db.execute("SELECT * FROM Conductores")

    return render_template("crear_sesion_ruta.html", 
                         rutas=rutas, 
                         vehiculos=vehiculos, 
                         conductores=conductores)

@app.route("/sesiones/<int:id>/iniciar", methods=["POST"])
@login_required
def iniciar_sesion(id):
    """Cambiar estado de sesión a 'en_ruta'"""
    db.execute("UPDATE Sesiones_Ruta SET Estado = 'en_ruta' WHERE ID_Sesion = ?", id)
    flash("Sesión de ruta iniciada", "success")
    return redirect("/sesiones")

@app.route("/sesiones/<int:id>/finalizar", methods=["GET", "POST"])
@login_required
def finalizar_sesion(id):
    """Finalizar una sesión de ruta"""
    if request.method == "POST":
        hora_fin = request.form.get("hora_fin")
        kilometraje_final = request.form.get("kilometraje_final")
        observaciones = request.form.get("observaciones")

        db.execute("""
            UPDATE Sesiones_Ruta 
            SET Estado = 'completada', Hora_Fin = ?, Kilometraje_Final = ?, Observaciones = ?
            WHERE ID_Sesion = ?
        """, hora_fin, kilometraje_final, observaciones, id)

        flash("Sesión de ruta finalizada exitosamente", "success")
        return redirect("/sesiones")

    sesion = db.execute("SELECT * FROM Sesiones_Ruta WHERE ID_Sesion = ?", id)
    if not sesion:
        flash("Sesión no encontrada", "danger")
        return redirect("/sesiones")

    return render_template("sesiones/finalizar.html", sesion=sesion[0])

@app.route("/sesiones/<int:id_sesion>/carga", methods=["GET", "POST"])
@login_required
def gestion_carga(id_sesion):
    """Gestionar carga inicial para una sesión"""
    sesion = db.execute("""
        SELECT sr.*, r.Nombre as Ruta, v.Placa
        FROM Sesiones_Ruta sr
        JOIN Rutas r ON sr.ID_Ruta = r.ID_Ruta
        JOIN Vehiculos v ON sr.ID_Vehiculo = v.ID_Vehiculo
        WHERE sr.ID_Sesion = ?
    """, id_sesion)

    if not sesion:
        flash("Sesión no encontrada", "danger")
        return redirect("/sesiones")

    if request.method == "POST":
        id_bodega = request.form.get("id_bodega")
        productos = request.form.getlist("productos[]")
        cantidades = request.form.getlist("cantidades[]")
        precios = request.form.getlist("precios[]")

        if not id_bodega:
            flash("Debe seleccionar una bodega", "danger")
            return redirect(f"/sesiones/{id_sesion}/carga")

        # Crear registro de carga
        carga_id = db.execute("""
            INSERT INTO Carga_Inicial_Ruta (ID_Sesion, ID_Bodega, Observaciones)
            VALUES (?, ?, ?)
            RETURNING ID_Carga
        """, id_sesion, id_bodega, "Carga inicial")[0]["ID_Carga"]

        # Registrar productos
        for i in range(len(productos)):
            db.execute("""
                INSERT INTO Detalle_Carga_Ruta 
                (ID_Carga, ID_Producto, Cantidad, Precio_Unitario)
                VALUES (?, ?, ?, ?)
            """, carga_id, productos[i], cantidades[i], precios[i])

            # Descontar del inventario
            db.execute("""
                UPDATE Inventario_Bodega 
                SET Existencias = Existencias - ?
                WHERE ID_Bodega = ? AND ID_Producto = ?
            """, cantidades[i], id_bodega, productos[i])

        flash("Carga inicial registrada exitosamente", "success")
        return redirect(f"/sesiones/{id_sesion}")

    # Obtener bodegas y productos disponibles
    bodegas = db.execute("SELECT * FROM Bodegas")
    productos = db.execute("""
        SELECT p.*, ib.Existencias, um.Abreviatura
        FROM Productos p
        JOIN Inventario_Bodega ib ON p.ID_Producto = ib.ID_Producto
        JOIN Unidades_Medida um ON p.Unidad_Medida = um.ID_Unidad
        WHERE ib.Existencias > 0
        ORDER BY p.Descripcion
    """)

    # Verificar si ya tiene carga registrada
    carga_existente = db.execute("""
        SELECT * FROM Carga_Inicial_Ruta WHERE ID_Sesion = ?
    """, id_sesion)

    detalles_carga = []
    if carga_existente:
        detalles_carga = db.execute("""
            SELECT d.*, p.Descripcion as Producto, um.Abreviatura
            FROM Detalle_Carga_Ruta d
            JOIN Productos p ON d.ID_Producto = p.ID_Producto
            JOIN Unidades_Medida um ON p.Unidad_Medida = um.ID_Unidad
            WHERE d.ID_Carga = ?
        """, carga_existente[0]["ID_Carga"])

    return render_template("sesiones/carga.html", 
                         sesion=sesion[0], 
                         bodegas=bodegas, 
                         productos=productos,
                         carga_existente=carga_existente,
                         detalles_carga=detalles_carga)

@app.route("/sesiones/<int:id_sesion>/ventas", methods=["GET", "POST"])
@login_required
def gestion_ventas(id_sesion):
    """Registrar ventas durante la ruta"""
    sesion = db.execute("""
        SELECT sr.*, r.Nombre as Ruta, v.Placa, c.Nombre as Conductor
        FROM Sesiones_Ruta sr
        JOIN Rutas r ON sr.ID_Ruta = r.ID_Ruta
        JOIN Vehiculos v ON sr.ID_Vehiculo = v.ID_Vehiculo
        LEFT JOIN Conductores c ON sr.ID_Conductor = c.ID_Conductor
        WHERE sr.ID_Sesion = ?
    """, id_sesion)

    if not sesion:
        flash("Sesión no encontrada", "danger")
        return redirect("/sesiones")

    if sesion[0]["Estado"] != "en_ruta":
        flash("Solo se pueden registrar ventas en sesiones activas", "warning")
        return redirect(f"/sesiones/{id_sesion}")

    if request.method == "POST":
        productos = request.form.getlist("productos[]")
        cantidades = request.form.getlist("cantidades[]")
        precios = request.form.getlist("precios[]")
        cliente = request.form.get("cliente")
        ubicacion = request.form.get("ubicacion")

        if not productos:
            flash("Debe agregar al menos un producto", "danger")
            return redirect(f"/sesiones/{id_sesion}/ventas")

        # Calcular total
        total = sum(float(cantidades[i]) * float(precios[i]) for i in range(len(productos)))

        # Crear venta
        venta_id = db.execute("""
            INSERT INTO Ventas_Ruta 
            (ID_Sesion, Total, Estado, Ubicacion_GPS)
            VALUES (?, ?, 'registrada', ?)
            RETURNING ID_Venta
        """, id_sesion, total, ubicacion)[0]["ID_Venta"]

        # Registrar productos
        for i in range(len(productos)):
            db.execute("""
                INSERT INTO Detalle_Venta_Ruta 
                (ID_Venta, ID_Producto, Cantidad, Precio_Unitario)
                VALUES (?, ?, ?, ?)
            """, venta_id, productos[i], cantidades[i], precios[i])

        flash("Venta registrada exitosamente", "success")
        return redirect(f"/sesiones/{id_sesion}/ventas")

    # Obtener productos de la carga inicial
    productos_carga = db.execute("""
        SELECT dc.ID_Producto, p.Descripcion, um.Abreviatura, 
               dc.Cantidad as Cargado,
               (dc.Cantidad - COALESCE((
                   SELECT SUM(dv.Cantidad) 
                   FROM Detalle_Venta_Ruta dv
                   JOIN Ventas_Ruta v ON dv.ID_Venta = v.ID_Venta
                   WHERE v.ID_Sesion = ? AND dv.ID_Producto = dc.ID_Producto
               ), 0)) as Disponible
        FROM Detalle_Carga_Ruta dc
        JOIN Productos p ON dc.ID_Producto = p.ID_Producto
        JOIN Unidades_Medida um ON p.Unidad_Medida = um.ID_Unidad
        WHERE dc.ID_Carga = (
            SELECT ID_Carga FROM Carga_Inicial_Ruta WHERE ID_Sesion = ?
        )
        HAVING Disponible > 0
    """, id_sesion, id_sesion)

    # Obtener ventas existentes
    ventas = db.execute("""
        SELECT v.*, 
               (SELECT COUNT(*) FROM Detalle_Venta_Ruta WHERE ID_Venta = v.ID_Venta) as Items
        FROM Ventas_Ruta v
        WHERE v.ID_Sesion = ?
        ORDER BY v.Fecha_Hora DESC
    """, id_sesion)

    return render_template("sesiones/ventas.html", 
                         sesion=sesion[0], 
                         productos=productos_carga,
                         ventas=ventas)

if __name__ == '__main__':
    app.run(debug=True)