from flask import Flask, flash, render_template, redirect, url_for, request, session, Response, jsonify, current_app
from cs50 import SQL
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from weasyprint import HTML
from datetime import datetime, timedelta
#from helpers import get_current_user
import traceback
import json

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

    # 1. Total sales (today and month)
    total_ventas_hoy = execute_query("""
        SELECT SUM(df.Total) AS total 
        FROM Detalle_Facturacion df
        JOIN Facturacion f ON df.ID_Factura = f.ID_Factura
        WHERE f.Fecha = ?
    """, [today])

    total_ventas_mes = execute_query("""
        SELECT SUM(df.Total) AS total 
        FROM Detalle_Facturacion df
        JOIN Facturacion f ON df.ID_Factura = f.ID_Factura
        WHERE strftime('%Y-%m', f.Fecha) = ?
    """, [current_month])


# 2. Total purchases (today and month) - VERSION CORREGIDA
    total_compras_hoy = execute_query("""
        SELECT COALESCE(SUM(dm.Costo_Total), 0) AS total
        FROM Detalle_Movimiento_Inventario dm
        JOIN Movimientos_Inventario mi ON dm.ID_Movimiento = mi.ID_Movimiento
        JOIN Catalogo_Movimientos cm ON mi.ID_TipoMovimiento = cm.ID_TipoMovimiento
        WHERE DATE(mi.Fecha) = DATE(?)
        AND LOWER(cm.Descripcion) LIKE '%compra%'
    """, [today])

    total_compras_mes = execute_query("""
        SELECT COALESCE(SUM(dm.Costo_Total), 0) AS total
        FROM Detalle_Movimiento_Inventario dm
        JOIN Movimientos_Inventario mi ON dm.ID_Movimiento = mi.ID_Movimiento
        JOIN Catalogo_Movimientos cm ON mi.ID_TipoMovimiento = cm.ID_TipoMovimiento
        WHERE strftime('%Y-%m', mi.Fecha) = ?
        AND LOWER(cm.Descripcion) LIKE '%compra%'
    """, [current_month])

    # 3. Inventory by warehouse
    inventario_bodegas = db.execute("""
        SELECT b.Nombre AS bodega, p.Descripcion AS producto, ib.Existencias
        FROM Inventario_Bodega ib
        JOIN Bodegas b ON ib.ID_Bodega = b.ID_Bodega
        JOIN Productos p ON ib.ID_Producto = p.ID_Producto
        ORDER BY b.Nombre, p.Descripcion
    """)

    # 4. Vehicle information
    vehiculos = db.execute("""
        SELECT v.Placa, v.Marca, v.Modelo, v.Color, v.Estado,
               (SELECT MAX(Kilometraje) FROM Mantenimiento_Vehiculo 
                WHERE ID_Vehiculo = v.ID_Vehiculo) AS kilometraje
        FROM Vehiculos v
        ORDER BY v.Estado DESC, v.Placa
    """)

    # 5. Top customers
    top_clientes = db.execute("""
        SELECT c.Nombre, SUM(df.Total) AS total_comprado
        FROM Clientes c
        JOIN Facturacion f ON c.ID_Cliente = f.IDCliente
        JOIN Detalle_Facturacion df ON f.ID_Factura = df.ID_Factura
        GROUP BY c.ID_Cliente
        ORDER BY total_comprado DESC
        LIMIT 5
    """)

    # 6. Latest invoice and today's date
    ultima_factura = db.execute("""
        SELECT f.ID_Factura, f.Fecha, c.Nombre AS cliente, SUM(df.Total) AS total
        FROM Facturacion f
        JOIN Clientes c ON f.IDCliente = c.ID_Cliente
        JOIN Detalle_Facturacion df ON f.ID_Factura = df.ID_Factura
        GROUP BY f.ID_Factura
        ORDER BY f.Fecha DESC
        LIMIT 1
    """)

    # 7. Accounts receivable
    cuentas_cobrar = execute_query("""
        SELECT SUM(Monto_Movimiento) AS total
        FROM Detalle_Cuentas_Por_Cobrar
        WHERE Fecha_Vencimiento >= DATE('now')
    """)

    cuentas_cobrar_vencidas = execute_query("""
        SELECT SUM(Monto_Movimiento) AS total
        FROM Detalle_Cuentas_Por_Cobrar
        WHERE Fecha_Vencimiento < DATE('now')
    """)

    # 8. Product stock alerts
    productos_stock_bajo = db.execute("""
        SELECT B.Nombre AS Bodega, P.COD_Producto, P.Descripcion, I.Existencias, U.Abreviatura
        FROM Inventario_Bodega I
        JOIN Bodegas B ON B.ID_Bodega = I.ID_Bodega
        JOIN Productos P ON P.ID_Producto = I.ID_Producto
        LEFT JOIN Unidades_Medida U ON U.ID_Unidad = P.Unidad_Medida
        WHERE I.Existencias <= 5
        AND P.Estado = 1
        ORDER BY B.Nombre, I.Existencias ASC
    """)

    # 9. Upcoming vehicle maintenance
    proximos_mantenimientos = db.execute("""
        SELECT mv.*, v.Placa
        FROM Mantenimiento_Vehiculo mv
        JOIN Vehiculos v ON mv.ID_Vehiculo = v.ID_Vehiculo
        WHERE mv.Fecha >= DATE('now')
        ORDER BY mv.Fecha ASC
        LIMIT 5
    """)

    # 10. Sales by product type (for chart)
    ventas_por_tipo = db.execute("""
        SELECT tp.Descripcion AS tipo, SUM(df.Cantidad) AS cantidad, SUM(df.Total) AS total
        FROM Detalle_Facturacion df
        JOIN Productos p ON df.ID_Producto = p.ID_Producto
        JOIN Tipo_Producto tp ON p.Tipo = tp.ID_TipoProducto
        JOIN Facturacion f ON df.ID_Factura = f.ID_Factura
        WHERE strftime('%Y-%m', f.Fecha) = ?
        GROUP BY tp.ID_TipoProducto
    """, [current_month])

    return render_template("index.html",
        today=today,
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
    # Consulta para obtener TODAS las compras sin límite
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
        ORDER BY mi.ID_Movimiento DESC
    """)

    # Agregar diagnóstico
    print(f"Total de compras recuperadas: {len(compras)}")

    # Obtener datos para los formularios (sin cambios)
    proveedores = db.execute("SELECT ID_Proveedor AS id, Nombre FROM Proveedores")
    empresas = db.execute("SELECT ID_Empresa, Descripcion FROM Empresa")
    bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos ORDER BY Descripcion")

    # Consulta de inventario (sin cambios)
    inventario_query = """
        SELECT 
            ib.ID_Bodega,
            ib.ID_Producto,
            p.Descripcion,
            ib.Cantidad as stock,
            COALESCE(
                (SELECT dmi.Precio_Unitario 
                 FROM Detalle_Movimiento_Inventario dmi 
                 JOIN Movimientos_Inventario mi ON dmi.ID_Movimiento = mi.ID_Movimiento 
                 WHERE dmi.ID_Producto = ib.ID_Producto 
                   AND mi.ID_Bodega = ib.ID_Bodega 
                   AND mi.ID_TipoMovimiento = 1 
                 ORDER BY mi.Fecha DESC 
                 LIMIT 1), 0
            ) as precio_compra
        FROM Inventario_Bodega ib
        JOIN Productos p ON ib.ID_Producto = p.ID_Producto
        WHERE ib.Cantidad > 0
        ORDER BY ib.ID_Bodega, p.Descripcion
    """
    
    # Procesamiento de inventario (sin cambios)
    try:
        inventario_resultados = db.execute(inventario_query)
        inventario_por_bodega = {}
        for row in inventario_resultados:
            bodega_id = str(row['ID_Bodega'])
            producto_id = str(row['ID_Producto'])
            
            if bodega_id not in inventario_por_bodega:
                inventario_por_bodega[bodega_id] = {}
                
            inventario_por_bodega[bodega_id][producto_id] = {
                'descripcion': row['Descripcion'],
                'stock': row['stock'],
                'precio': float(row['precio_compra']) if row['precio_compra'] else 0
            }
    except Exception as e:
        print(f"Error en consulta de inventario: {e}")
        inventario_por_bodega = {}
    
    # Obtener productos de cada compra (sin cambios)
    for compra in compras:
        try:
            compra['productos'] = db.execute("""
                SELECT 
                    dmi.ID_Producto as id_producto,
                    p.Descripcion as descripcion,
                    dmi.Cantidad as cantidad,
                    dmi.Precio_Unitario as costo,
                    0 as iva,
                    0 as descuento,
                    COALESCE(ib.Cantidad, 0) as stock
                FROM Detalle_Movimiento_Inventario dmi
                JOIN Productos p ON dmi.ID_Producto = p.ID_Producto
                LEFT JOIN Inventario_Bodega ib ON ib.ID_Producto = dmi.ID_Producto 
                    AND ib.ID_Bodega = ?
                WHERE dmi.ID_Movimiento = ?
            """, compra['id_bodega'], compra['id'])
        except Exception as e:
            print(f"Error obteniendo productos de compra {compra['id']}: {e}")
            compra['productos'] = []

    return render_template("gestionar_compras.html",
                           compras=compras,
                           proveedores=proveedores,
                           empresas=empresas,
                           bodegas=bodegas,
                           productos=productos,
                           inventario_por_bodega=inventario_por_bodega)

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

            # Validación por campo
            if not fecha:
                flash("La fecha es obligatoria.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))
            if not proveedor_id:
                flash("Debe seleccionar un proveedor.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))
            if not id_bodega:
                flash("Debe seleccionar una bodega.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))
            if not id_empresa:
                flash("Debe seleccionar una empresa.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))

            try:
                proveedor_id = int(proveedor_id)
                id_bodega = int(id_bodega)
                id_empresa = int(id_empresa)
            except ValueError:
                flash("Los valores de proveedor, bodega y empresa deben ser numéricos.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))

            # Verificar existencia de registros foráneos
            if not db.execute("SELECT 1 FROM Proveedores WHERE ID_Proveedor = ?", proveedor_id):
                flash("El proveedor seleccionado no existe.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))
            if not db.execute("SELECT 1 FROM Bodegas WHERE ID_Bodega = ?", id_bodega):
                flash("La bodega seleccionada no existe.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))
            if not db.execute("SELECT 1 FROM Empresa WHERE ID_Empresa = ?", id_empresa):
                flash("La empresa seleccionada no existe.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))

            # Primero, obtener los detalles actuales para revertir los cambios en inventario
            detalles_actuales = db.execute("""
                SELECT ID_Producto, Cantidad FROM Detalle_Movimiento_Inventario
                WHERE ID_Movimiento = ?
            """, id_compra)

            # Revertir cambios en inventario
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

            # Eliminar detalles actuales
            db.execute("DELETE FROM Detalle_Movimiento_Inventario WHERE ID_Movimiento = ?", id_compra)

            # Actualizar movimiento principal
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

            # Procesar nuevos productos
            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]")
            descuentos = request.form.getlist("descuentos[]")

            if not productos:
                flash("Debe agregar al menos un producto a la compra.", "danger")
                return redirect(url_for("editar_compra", id_compra=id_compra))

            total_compra = 0
            for i in range(len(productos)):
                id_producto = productos[i]
                if not db.execute("SELECT 1 FROM Productos WHERE ID_Producto = ?", id_producto):
                    flash(f"El producto con ID {id_producto} no existe.", "danger")
                    return redirect(url_for("editar_compra", id_compra=id_compra))

                cantidad = float(cantidades[i] or 0)
                costo = float(costos[i] or 0)
                iva = float(ivas[i] or 0)
                descuento = float(descuentos[i] or 0)

                costo_total = (cantidad * costo) - descuento + iva
                total_compra += costo_total

                # Insertar nuevo detalle
                db.execute("""
                    INSERT INTO Detalle_Movimiento_Inventario (
                        ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                        Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, id_compra, compra[0]["ID_TipoMovimiento"], id_producto,
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

            # Manejar cuenta por pagar si es a crédito
            cuenta_pagar = db.execute("""
                SELECT * FROM Cuentas_Por_Pagar 
                WHERE Num_Documento = ? AND Tipo_Movimiento = ?
            """, n_factura, compra[0]["ID_TipoMovimiento"])

            if tipo_pago == 1:  # Crédito
                fecha_vencimiento = (datetime.strptime(fecha, '%Y-%m-%d') + timedelta(days=30)).date()
                
                if cuenta_pagar:
                    # Actualizar cuenta existente
                    db.execute("""
                        UPDATE Cuentas_Por_Pagar SET
                            Fecha = ?,
                            ID_Proveedor = ?,
                            Observacion = ?,
                            Fecha_Vencimiento = ?,
                            Monto_Movimiento = ?,
                            ID_Empresa = ?
                        WHERE ID_Cuenta = ?
                    """, fecha, proveedor_id, observacion, 
                        fecha_vencimiento.strftime("%Y-%m-%d"), 
                        total_compra, id_empresa, cuenta_pagar[0]["ID_Cuenta"])
                else:
                    # Crear nueva cuenta
                    db.execute("""
                        INSERT INTO Cuentas_Por_Pagar (
                            Fecha, ID_Proveedor, Num_Documento,
                            Observacion, Fecha_Vencimiento, Tipo_Movimiento,
                            Monto_Movimiento, IVA, Retencion, ID_Empresa
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                    """, fecha, proveedor_id, n_factura, observacion,
                        fecha_vencimiento.strftime("%Y-%m-%d"), compra[0]["ID_TipoMovimiento"],
                        total_compra, id_empresa)
            elif cuenta_pagar:
                # Eliminar cuenta si ya no es a crédito
                db.execute("DELETE FROM Cuentas_Por_Pagar WHERE ID_Cuenta = ?", cuenta_pagar[0]["ID_Cuenta"])

            flash("✅ Compra actualizada correctamente.", "success")
            return redirect(url_for("gestionar_compras"))

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            flash(f"❌ Error al actualizar la compra: {e}", "danger")
            return redirect(url_for("editar_compra", id_compra=id_compra))

    # GET (formulario de edición)
    proveedores = db.execute("SELECT ID_Proveedor AS id, Nombre FROM Proveedores")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion FROM Productos")
    bodegas = db.execute("SELECT ID_Bodega, Nombre FROM Bodegas")
    empresas = db.execute("SELECT ID_Empresa, Descripcion FROM Empresa")
    
    # Obtener detalles actuales de la compra
    detalles = db.execute("""
        SELECT d.*, p.Descripcion AS producto_desc 
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
            return redirect(url_for("gestionar_ventas"))

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

############################################################################
@app.route("/gestionar_ventas", methods=["GET"])
def gestionar_ventas():
    try:
        if not session.get("user_id"):
            flash("❌ Debes iniciar sesión", "danger")
            return redirect(url_for("login"))

        # Paginación
        page = request.args.get('page', 1, type=int)
        per_page = 20
        offset = (page - 1) * per_page

        # Consulta principal
        ventas = db.execute("""
            SELECT 
                f.ID_Factura, 
                strftime('%d/%m/%Y %H:%M', f.Fecha) as Fecha,
                c.Nombre AS Cliente,
                f.Credito_Contado,
                SUM(df.Total) AS Total,
                EXISTS(SELECT 1 FROM Pagos_Credito WHERE ID_Factura = f.ID_Factura) AS tiene_pagos
            FROM Facturacion f
            JOIN Clientes c ON c.ID_Cliente = f.IDCliente
            JOIN Detalle_Facturacion df ON df.ID_Factura = f.ID_Factura
            GROUP BY f.ID_Factura
            ORDER BY f.Fecha DESC
            LIMIT ? OFFSET ?
        """, per_page, offset)

        # Productos por venta
        detalles = db.execute("""
            SELECT 
                df.ID_Factura, 
                p.Descripcion, 
                df.Cantidad, 
                df.PrecioUnitario,
                df.Total AS Subtotal
            FROM Detalle_Facturacion df
            JOIN Productos p ON df.ID_Producto = p.ID_Producto
            WHERE df.ID_Factura IN (
                SELECT ID_Factura FROM Facturacion 
                ORDER BY Fecha DESC 
                LIMIT ? OFFSET ?
            )
        """, per_page, offset)

        # Procesamiento
        productos_por_venta = {}
        for d in detalles:
            productos_por_venta.setdefault(d["ID_Factura"], []).append(
                f"{d['Cantidad']} x {d['Descripcion']} (C${d['Subtotal']:.2f})"
            )

        for venta in ventas:
            venta["Productos"] = productos_por_venta.get(venta["ID_Factura"], [])
            venta["NumeroFactura"] = f"F-{venta['ID_Factura']:05d}"
            venta["TotalFormateado"] = f"C${venta['Total']:.2f}"
            venta["tiene_pagos"] = bool(venta["tiene_pagos"])

        return render_template("gestionar_ventas.html", ventas=ventas, page=page)

    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        flash("❌ Error al cargar ventas", "danger")
        return redirect(url_for("ventas"))

@app.route("/ventas/<int:venta_id>", methods=["GET"])
def obtener_detalle_venta(venta_id):
    try:
        if not venta_id or venta_id <= 0:
            return jsonify({"error": "ID inválido"}), 400

        venta = db.execute("""
            SELECT 
                f.ID_Factura, 
                strftime('%Y-%m-%d %H:%M:%S', f.Fecha) AS Fecha,
                c.Nombre AS Cliente,
                c.Telefono,
                c.Direccion,
                f.Credito_Contado,
                f.Observacion,
                SUM(df.Total) AS Total
            FROM Facturacion f
            JOIN Clientes c ON c.ID_Cliente = f.IDCliente
            JOIN Detalle_Facturacion df ON df.ID_Factura = f.ID_Factura
            WHERE f.ID_Factura = ?
            GROUP BY f.ID_Factura
        """, venta_id)

        if not venta:
            return jsonify({"error": "No encontrada"}), 404

        detalles = db.execute("""
            SELECT 
                p.Descripcion, 
                df.Cantidad, 
                df.PrecioUnitario,
                df.Total AS Subtotal
            FROM Detalle_Facturacion df
            JOIN Productos p ON df.ID_Producto = p.ID_Producto
            WHERE df.ID_Factura = ?
        """, venta_id)

        response = {
            "venta": venta[0],
            "productos": detalles,
            "status": "success"
        }
        return jsonify(response)

    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
######################################################################
@app.route("/productos_por_bodega/<int:id_bodega>")
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
            detalles_ids = request.form.getlist("detalles_ids[]")  # IDs de los detalles existentes

            # === VALIDACIONES ===
            if not fecha or not cliente_id or not tipo_pago or not id_bodega:
                flash("Todos los campos obligatorios deben estar completos.", "danger")
                return redirect(url_for("editar_venta", venta_id=venta_id))

            if not productos or len(productos) == 0:
                flash("Debe ingresar al menos un producto.", "danger")
                return redirect(url_for("editar_venta", venta_id=venta_id))

            if len(productos) != len(cantidades) or len(productos) != len(costos):
                flash("Error en los datos de productos.", "danger")
                return redirect(url_for("editar_venta", venta_id=venta_id))

            tipo_pago = int(tipo_pago)
            id_bodega = int(id_bodega)
            id_empresa = 1  # Ajusta según tu lógica
            total_venta = 0

            # === INICIO DE TRANSACCIÓN ===
            db.execute("BEGIN")

            # Obtener información de la venta original
            venta_original = db.execute("""
                SELECT * FROM Facturacion WHERE ID_Factura = ?
            """, venta_id)
            
            if not venta_original:
                db.execute("ROLLBACK")
                flash("La venta que intentas editar no existe.", "danger")
                return redirect(url_for("gestionar_ventas"))

            # Obtener el movimiento de inventario asociado
            movimiento_original = db.execute("""
                SELECT * FROM Movimientos_Inventario 
                WHERE N_Factura = ? AND ID_Empresa = ?
            """, f"F-{venta_id:05d}", id_empresa)
            
            if not movimiento_original:
                db.execute("ROLLBACK")
                flash("No se encontró el movimiento de inventario asociado a esta venta.", "danger")
                return redirect(url_for("gestionar_ventas"))

            movimiento_id = movimiento_original[0]["ID_Movimiento"]

            # 1. Revertir los cambios de la venta original
            # a. Revertir inventario
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

            # b. Eliminar detalles originales
            db.execute("DELETE FROM Detalle_Facturacion WHERE ID_Factura = ?", venta_id)
            db.execute("DELETE FROM Detalle_Movimiento_Inventario WHERE ID_Movimiento = ?", movimiento_id)
            
            # c. Eliminar cuenta por cobrar si era crédito
            if venta_original[0]["Credito_Contado"] == 1:
                db.execute("""
                    DELETE FROM Detalle_Cuentas_Por_Cobrar 
                    WHERE ID_Movimiento = ? AND Tipo_Movimiento = 2
                """, venta_id)

            # 2. Actualizar la factura principal
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

            # 4. Insertar los nuevos productos
            for i in range(len(productos)):
                id_producto = int(productos[i])
                cantidad = float(cantidades[i])
                costo = float(costos[i])
                iva = float(ivas[i])
                descuento = float(descuentos[i])

                # Validación: mínimo 50 cajillas
                if cantidad < 0:
                    nombre_prod = db.execute("SELECT Descripcion FROM Productos WHERE ID_Producto = ?", id_producto)[0]["Descripcion"]
                    db.execute("ROLLBACK")
                    flash(f"No se permite vender menos de 50 cajillas del producto '{nombre_prod}'.", "danger")
                    return redirect(url_for("editar_venta", venta_id=venta_id))
                
                # Validación: existencia en bodega
                existencia = db.execute("""
                    SELECT Existencias FROM Inventario_Bodega
                    WHERE ID_Bodega = ? AND ID_Producto = ?
                """, id_bodega, id_producto)
                if not existencia or existencia[0]["Existencias"] < cantidad:
                    nombre_prod = db.execute("SELECT Descripcion FROM Productos WHERE ID_Producto = ?", id_producto)[0]["Descripcion"]
                    db.execute("ROLLBACK")
                    flash(f"No hay suficiente stock del producto '{nombre_prod}' en la bodega seleccionada.", "danger")
                    return redirect(url_for("editar_venta", venta_id=venta_id))

                total = (cantidad * costo) - descuento + iva
                total_venta += total

                # Detalle de facturación
                db.execute("""
                    INSERT INTO Detalle_Facturacion (ID_Factura, ID_Producto, Cantidad, Costo, Descuento, IVA, Total)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, venta_id, id_producto, cantidad, costo, descuento, iva, total)

                # Movimiento de inventario
                db.execute("""
                    INSERT INTO Detalle_Movimiento_Inventario (
                        ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                        Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, movimiento_id, movimiento_original[0]["ID_TipoMovimiento"], id_producto,
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
                """, venta_id, fecha, cliente_id, f"F-{venta_id:05d}", observacion,
                     fecha_vencimiento.strftime("%Y-%m-%d"), 2, total_venta, id_empresa)

            db.execute("COMMIT")
            flash("Venta actualizada correctamente.", "success")
            return redirect(url_for("gestionar_ventas"))

        except Exception as e:
            print(traceback.format_exc())
            db.execute("ROLLBACK")
            flash(f"Error al actualizar la venta: {e}", "danger")
            return redirect(url_for("editar_venta", venta_id=venta_id))

    # === GET ===
    # Obtener datos de la venta existente
    venta = db.execute("""
        SELECT f.*, c.Nombre AS cliente_nombre 
        FROM Facturacion f
        JOIN Clientes c ON f.IDCliente = c.ID_Cliente
        WHERE f.ID_Factura = ?
    """, venta_id)
    
    if not venta:
        flash("La venta que intentas editar no existe.", "danger")
        return redirect(url_for("gestionar_ventas"))

    venta = venta[0]

    # Obtener detalles de la venta
    detalles = db.execute("""
        SELECT df.*, p.Descripcion AS producto_nombre
        FROM Detalle_Facturacion df
        JOIN Productos p ON df.ID_Producto = p.ID_Producto
        WHERE df.ID_Factura = ?
    """, venta_id)

    # Obtener datos para los selects
    clientes = db.execute("SELECT ID_Cliente AS id, Nombre AS nombre FROM Clientes")
    productos = db.execute("SELECT ID_Producto AS id, Descripcion AS descripcion FROM Productos")
    bodegas = db.execute("SELECT ID_Bodega AS id, Nombre AS nombre FROM Bodegas")

    n_factura = f"F-{venta_id:05d}"

    return render_template("editar_venta.html", 
                         venta=venta, 
                         detalles=detalles,
                         clientes=clientes, 
                         productos=productos, 
                         bodegas=bodegas, 
                         n_factura=n_factura)
#fin de ruta de ventas
#####################################################################################################
# ruta de cobros
@app.route("/cobros", methods=["GET"])
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

@app.route("/historial_pagos/<int:id_movimiento>")
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
    
@app.route("/registrar_cobro/<int:id_movimiento>", methods=["GET", "POST"])
def registrar_cobro(id_movimiento):
    if request.method == "POST":
        try:
            # Validación y captura de datos básicos
            monto = float(request.form["monto"])
            metodo = int(request.form["metodo_pago"])
            comentarios = request.form.get("comentarios", "").strip()

            # Captura de detalles específicos del método de pago (similar a cuentas por pagar)
            datos_especificos = {}
            
            # Efectivo
            if metodo == 1:
                datos_especificos = {
                    'tipo': 'efectivo',
                    'efectivo_recibido': float(request.form.get("efectivo_recibido", 0)),
                    'cambio': float(request.form.get("efectivo_recibido", 0)) - monto
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
    
@app.route("/cancelar_deuda/<int:id_movimiento>", methods=["POST"])
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

# ruta de pagos
@app.route("/pagos", methods=["GET"])
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
    
@app.route("/actualizar_saldos", methods=["GET"])
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


@app.route("/registrar_pago/<int:id_cuenta>", methods=["GET", "POST"])
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

# Ruta para ver el detalle de la cuenta con los pagos
@app.route("/detalle_cuenta/<int:id_cuenta>")
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
            "detalle_cuenta.html",
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


@app.route("/historial_pagos_pagar/<int:id_cuenta>")
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

# Ruta Factura impresion
def format_currency(value):
    return "{:,.2f}".format(value)


@app.route("/factura_alterna", methods=["GET", "POST"])
@login_required
def factura_alterna():
    if request.method == "POST":
        try:
            # === VALIDACIÓN DE FECHA (combinando ambos enfoques) ===
            fecha = request.form.get("fecha")
            if not fecha:
                flash("La fecha es requerida", "danger")
                return redirect(url_for("factura_alterna"))

            try:
                fecha_date = datetime.strptime(fecha, '%Y-%m-%d').date()
                if fecha_date > datetime.now().date():
                    flash("La fecha no puede ser futura", "danger")
                    return redirect(url_for("factura_alterna"))
            except ValueError:
                flash("Formato de fecha inválido (YYYY-MM-DD)", "danger")
                return redirect(url_for("factura_alterna"))

            # === OBTENER DATOS DEL FORMULARIO (combinando ambos) ===
            cliente_id = request.form.get("cliente")
            tipo_pago = request.form.get("tipo_pago")  # 0=Contado, 1=Crédito
            observacion = request.form.get("observacion", "").strip()
            id_bodega = request.form.get("id_bodega")
            
            # Soporte para ambos formatos de productos
            productos = request.form.getlist("productos[]")
            cantidades = request.form.getlist("cantidades[]")
            costos = request.form.getlist("precio_unitarios[]") or request.form.getlist("costos[]")
            ivas = request.form.getlist("ivas[]", [0]*len(productos))  # Default 0 si no existe
            descuentos = request.form.getlist("descuentos[]", [0]*len(productos))  # Default 0 si no existe

            # === VALIDACIONES COMBINADAS ===
            if not all([cliente_id, tipo_pago, id_bodega]):
                flash("Todos los campos obligatorios deben estar completos", "danger")
                return redirect(url_for("factura_alterna"))

            if not productos or len(productos) == 0:
                flash("Debe ingresar al menos un producto", "danger")
                return redirect(url_for("factura_alterna"))

            if len(productos) != len(cantidades) or len(productos) != len(costos):
                flash("Error en los datos de productos", "danger")
                return redirect(url_for("factura_alterna"))

            # === CONVERSIÓN DE TIPOS ===
            try:
                tipo_pago = int(tipo_pago)
                id_bodega = int(id_bodega)
                id_cliente = int(cliente_id)
                cantidades = [max(0.01, round(float(q), 2)) for q in cantidades]
                costos = [max(0.01, round(float(p), 2)) for p in costos]
                ivas = [float(i) for i in ivas]
                descuentos = [float(d) for d in descuentos]
            except (ValueError, TypeError) as ve:
                flash(f"Datos numéricos inválidos: {str(ve)}", "danger")
                return redirect(url_for("factura_alterna"))

            id_empresa = current_user.get('id_empresa') or 1  # Default 1 si no existe

            # === VERIFICACIÓN DE EXISTENCIAS ===
            cliente = db.execute("SELECT ID_Cliente FROM Clientes WHERE ID_Cliente = ?", id_cliente)
            if not cliente:
                flash("Cliente no encontrado", "danger")
                return redirect(url_for("factura_alterna"))

            bodega = db.execute("SELECT ID_Bodega FROM Bodegas WHERE ID_Bodega = ?", id_bodega)
            if not bodega:
                flash("Bodega no encontrada", "danger")
                return redirect(url_for("factura_alterna"))

            # Verificar productos y existencias
            productos_ids = [int(p) for p in productos]
            productos_db = db.execute(
                """SELECT p.ID_Producto, p.Descripcion, ib.Existencias 
                   FROM Productos p
                   LEFT JOIN Inventario_Bodega ib ON p.ID_Producto = ib.ID_Producto 
                   AND ib.ID_Bodega = ?
                   WHERE p.ID_Producto IN ({})""".format(','.join(['?']*len(productos_ids))),
                id_bodega, *productos_ids
            )

            if len(productos_db) != len(productos_ids):
                flash("Algunos productos no existen", "danger")
                return redirect(url_for("factura_alterna"))

            # === INICIO DE TRANSACCIÓN ===
            db.execute("BEGIN")

            # === INSERTAR FACTURA ALTERNA (manteniendo estructura original) ===
            db.execute(
                """INSERT INTO Factura_Alterna 
                   (Fecha, IDCliente, Credito_Contado, Observacion, ID_Empresa)
                   VALUES (?, ?, ?, ?, ?)""",
                fecha, id_cliente, tipo_pago, observacion, id_empresa
            )
            factura_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # === REGISTRAR MOVIMIENTO DE INVENTARIO (como en ventas) ===
            tipo_mov = db.execute("SELECT ID_TipoMovimiento FROM Catalogo_Movimientos WHERE Descripcion = 'Venta'")
            if not tipo_mov:
                db.execute("ROLLBACK")
                flash("El tipo de movimiento 'Venta' no está definido.", "danger")
                return redirect(url_for("factura_alterna"))

            tipo_movimiento = tipo_mov[0]["ID_TipoMovimiento"]

            db.execute(
                """INSERT INTO Movimientos_Inventario (
                    ID_TipoMovimiento, N_Factura, Contado_Credito, Fecha,
                    ID_Proveedor, Observacion, IVA, Retencion,
                    ID_Empresa, ID_Bodega
                ) VALUES (?, ?, ?, ?, NULL, ?, 0, 0, ?, ?)""",
                tipo_movimiento, f"FA-{factura_id:05d}", tipo_pago, fecha, observacion, id_empresa, id_bodega
            )
            movimiento_id = db.execute("SELECT last_insert_rowid() AS id")[0]["id"]

            # === PROCESAR PRODUCTOS (combinando ambas lógicas) ===
            total_venta = 0
            for i in range(len(productos)):
                id_producto = int(productos[i])
                cantidad = float(cantidades[i])
                costo = float(costos[i])
                iva = float(ivas[i])
                descuento = float(descuentos[i])
                total = (cantidad * costo) - descuento + iva
                total_venta += total

                # Validar existencia
                existencia = db.execute(
                    """SELECT Existencias FROM Inventario_Bodega
                       WHERE ID_Bodega = ? AND ID_Producto = ?""",
                    id_bodega, id_producto
                )
                
                if not existencia or existencia[0]["Existencias"] < cantidad:
                    nombre_prod = db.execute(
                        "SELECT Descripcion FROM Productos WHERE ID_Producto = ?", 
                        id_producto
                    )[0]["Descripcion"]
                    db.execute("ROLLBACK")
                    flash(f"No hay suficiente stock del producto '{nombre_prod}' en la bodega", "danger")
                    return redirect(url_for("factura_alterna"))

                # Insertar en Detalle_Factura_Alterna (estructura original)
                db.execute(
                    """INSERT INTO Detalle_Factura_Alterna 
                       (ID_Factura, ID_Producto, Cantidad, Costo, Total)
                       VALUES (?, ?, ?, ?, ?)""",
                    factura_id, id_producto, cantidad, costo, total
                )

                # Insertar en Detalle_Movimiento_Inventario (como en ventas)
                db.execute(
                    """INSERT INTO Detalle_Movimiento_Inventario (
                        ID_Movimiento, ID_TipoMovimiento, ID_Producto,
                        Cantidad, Costo, IVA, Descuento, Costo_Total, Saldo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    movimiento_id, tipo_movimiento, id_producto,
                    cantidad, costo, iva, descuento, total, -cantidad
                )

                # Actualizar inventario (como en ventas)
                db.execute(
                    """UPDATE Productos SET Existencias = Existencias - ?
                       WHERE ID_Producto = ?""",
                    cantidad, id_producto
                )

                db.execute(
                    """UPDATE Inventario_Bodega SET Existencias = Existencias - ?
                       WHERE ID_Bodega = ? AND ID_Producto = ?""",
                    cantidad, id_bodega, id_producto
                )

            # === REGISTRAR CUENTA POR COBRAR SI ES CRÉDITO (combinado) ===
            if tipo_pago == 1:
                fecha_vencimiento = fecha_date + timedelta(days=30)
                db.execute(
                    """INSERT INTO Detalle_Cuentas_Por_Cobrar (
                        ID_Movimiento, Fecha, ID_Cliente, Num_Documento, Observacion,
                        Fecha_Vencimiento, Tipo_Movimiento, Monto_Movimiento,
                        IVA, Retencion, ID_Empresa
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)""",
                    factura_id, fecha, id_cliente, f"FA-{factura_id:05d}", observacion,
                    fecha_vencimiento.strftime("%Y-%m-%d"), 2, total_venta, id_empresa
                )

            db.execute("COMMIT")
            flash(f"Factura alterna #{factura_id} registrada correctamente. Total: ${total_venta:.2f}", "success")
            return redirect(url_for("factura_alterna"))

        except Exception as e:
            db.execute("ROLLBACK")
            print(traceback.format_exc())
            flash(f"Error al registrar la factura alterna: {str(e)}", "danger")
            return redirect(url_for("factura_alterna"))

    # === MÉTODO GET ===
    try:
        id_empresa = current_user.get("id_empresa") or 1
        
        clientes = db.execute(
            "SELECT ID_Cliente AS id, Nombre AS nombre FROM Clientes"
        )
        
        productos = db.execute(
            "SELECT ID_Producto AS id, Descripcion AS descripcion FROM Productos"
        )
        
        bodegas = db.execute(
            "SELECT ID_Bodega AS id, Nombre AS nombre FROM Bodegas"
        )

        # Obtener próximo número de factura (como en ventas)
        last_seq = db.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", "Factura_Alterna")
        next_id = last_seq[0]["seq"] + 1 if last_seq else 1


        return render_template("factura_alterna.html",
                           clientes=clientes,
                           productos=productos,
                           bodegas=bodegas)

    except Exception as e:
        print(traceback.format_exc())
        flash("Error al cargar datos iniciales", "danger")
        return render_template("factura_alterna.html",
                           clientes=[],
                           productos=[],
                           bodegas=[])


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
            ORDER BY P.cod_producto
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