
CREATE TABLE Roles (
    ID_Rol INTEGER PRIMARY KEY AUTOINCREMENT,
    Nombre_Rol TEXT NOT NULL
)

CREATE TABLE Usuarios (
    ID_Usuario INTEGER PRIMARY KEY AUTOINCREMENT,
    NombreUsuario TEXT UNIQUE NOT NULL,
    ContrasenaHash TEXT NOT NULL,
    Rol_ID INTEGER,
    Estado INTEGER,
    Fecha_Creacion DATE,
    FOREIGN KEY (Rol_ID) REFERENCES Roles(ID_Rol)
)

CREATE TABLE Pagos_CuentasPagar (
    ID_Pago INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Movimiento INTEGER,
    Fecha DATETIME,
    Monto NUMERIC(12,2),
    ID_MetodoPago INTEGER,
    FOREIGN KEY (ID_Movimiento) REFERENCES Cuentas_Por_Pagar(ID_MOVIMIENTO),
    FOREIGN KEY (ID_MetodoPago) REFERENCES Metodos_Pago(ID_MetodoPago)
)

CREATE TABLE Bancos (
    ID_Banco INTEGER PRIMARY KEY AUTOINCREMENT,
    Nombre TEXT,
    Cuenta TEXT
)

CREATE TABLE Configuracion (
    ID_Config INTEGER PRIMARY KEY AUTOINCREMENT,
    NombreParametro TEXT,
    ValorParametro TEXT
)

CREATE TABLE Clientes (
    ID_Cliente INTEGER PRIMARY KEY AUTOINCREMENT,
    Nombre TEXT NOT NULL,
    Telefono TEXT,
    Direccion TEXT,
    RUC_CEDULA TEXT
)

CREATE TABLE Proveedores (
    ID_Proveedor INTEGER PRIMARY KEY AUTOINCREMENT,
    Nombre TEXT NOT NULL,
    Telefono TEXT,
    Direccion TEXT,
    RUC_CEDULA TEXT
)

CREATE TABLE Empresa (
    ID_Empresa INTEGER PRIMARY KEY AUTOINCREMENT,
    Descripcion TEXT
)

CREATE TABLE Catalogo_Movimientos (
    ID_TipoMovimiento INTEGER PRIMARY KEY AUTOINCREMENT,
    Descripcion TEXT,
    Adicion TEXT,
    Letra TEXT
)

CREATE TABLE Unidades_Medida (
    ID_Unidad INTEGER PRIMARY KEY AUTOINCREMENT,
    Descripcion TEXT NOT NULL,
    Abreviatura TEXT
)

CREATE TABLE Familia (
    ID_Familia INTEGER PRIMARY KEY AUTOINCREMENT,
    Descripcion TEXT NOT NULL
)

CREATE TABLE Tipo_Producto (
    ID_TipoProducto INTEGER PRIMARY KEY AUTOINCREMENT,
    Descripcion TEXT NOT NULL
)

CREATE TABLE Detalle_Movimiento_Inventario (
    ID_Detalle INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Movimiento INTEGER,
    ID_TipoMovimiento INTEGER,
    ID_Producto INTEGER,
    Cantidad INTEGER,
    Costo NUMERIC,
    IVA NUMERIC,
    Descuento NUMERIC,
    Costo_Total NUMERIC,
    Saldo NUMERIC,
    FOREIGN KEY (ID_Movimiento) REFERENCES Movimientos_Inventario(ID_Movimiento),
    FOREIGN KEY (ID_Producto) REFERENCES Productos(ID_Producto)
)

CREATE TABLE Gastos (
    ID_Movimiento INTEGER PRIMARY KEY AUTOINCREMENT,
    Fecha DATE,
    Observacion TEXT,
    Monto NUMERIC,
    ID_Empresa INTEGER,
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa)
)

CREATE TABLE Bodegas (
    ID_Bodega INTEGER PRIMARY KEY AUTOINCREMENT,
    Nombre TEXT NOT NULL,
    Ubicacion TEXT
)

CREATE TABLE Vehiculos (
    ID_Vehiculo INTEGER PRIMARY KEY AUTOINCREMENT,
    Placa TEXT NOT NULL,
    Marca TEXT,
    Modelo TEXT,
    Año INTEGER,
    Color TEXT,
    NumeroChasis TEXT,
    NumeroMotor TEXT,
    Estado INTEGER DEFAULT 1  -- 1=Activo, 0=Inactivo/Baja
)

CREATE TABLE Mantenimiento_Vehiculo (
    ID_Mantenimiento INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Vehiculo INTEGER,
    Fecha DATE,
    Tipo TEXT, -- Ej: Preventivo, Correctivo, Revisión, Cambio de Aceite, etc.
    Descripcion TEXT,
    Costo NUMERIC,
    Proveedor TEXT,
    Kilometraje NUMERIC,
    Observacion TEXT,
    FOREIGN KEY (ID_Vehiculo) REFERENCES Vehiculos(ID_Vehiculo)
)

CREATE TABLE Conductores (
    ID_Conductor INTEGER PRIMARY KEY AUTOINCREMENT,
    Nombre TEXT,
    Cedula TEXT,
    Telefono TEXT,
    Licencia TEXT
)

CREATE TABLE Vehiculo_Conductor (
    ID_Vehiculo INTEGER,
    ID_Conductor INTEGER,
    FechaAsignacion DATE,
    PRIMARY KEY (ID_Vehiculo, ID_Conductor, FechaAsignacion),
    FOREIGN KEY (ID_Vehiculo) REFERENCES Vehiculos(ID_Vehiculo),
    FOREIGN KEY (ID_Conductor) REFERENCES Conductores(ID_Conductor)
)

CREATE TABLE Rutas (
    ID_Ruta INTEGER PRIMARY KEY AUTOINCREMENT,
    Nombre TEXT NOT NULL,
    Descripcion TEXT
)

CREATE TABLE Vehiculo_Ruta (
    ID_Vehiculo INTEGER,
    ID_Ruta INTEGER,
    FechaAsignacion DATE,
    PRIMARY KEY (ID_Vehiculo, ID_Ruta, FechaAsignacion),
    FOREIGN KEY (ID_Vehiculo) REFERENCES Vehiculos(ID_Vehiculo),
    FOREIGN KEY (ID_Ruta) REFERENCES Rutas(ID_Ruta)
)

CREATE TABLE Gastos_Combustible (
    ID_Gasto INTEGER PRIMARY KEY AUTOINCREMENT,
    Fecha DATE NOT NULL,
    ID_Vehiculo INTEGER NOT NULL,
    Monto NUMERIC NOT NULL,
    Litros NUMERIC,
    Kilometraje NUMERIC,
    Observacion TEXT,
    ID_Bodega INTEGER,
    ID_Empresa INTEGER,
    FOREIGN KEY (ID_Vehiculo) REFERENCES Vehiculos(ID_Vehiculo),
    FOREIGN KEY (ID_Bodega) REFERENCES Bodegas(ID_Bodega),
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa)
)

CREATE TABLE Facturacion (
    ID_Factura INTEGER PRIMARY KEY AUTOINCREMENT,
    Fecha DATE NOT NULL,
    IDCliente INTEGER NOT NULL,
    Credito_Contado INTEGER,
    Observacion TEXT,
    ID_Empresa INTEGER NOT NULL,
    FOREIGN KEY (IDCliente) REFERENCES Clientes(ID_Cliente),
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa)
)

CREATE TABLE Cuentas_Por_Pagar (
    ID_Cuenta INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Movimiento INTEGER,
    Fecha DATE,
    ID_Proveedor INTEGER,
    Num_Documento TEXT,
    Observacion TEXT,
    Fecha_Vencimiento DATE,
    Tipo_Movimiento INTEGER,
    Monto_Movimiento NUMERIC,
    IVA NUMERIC,
    Retencion NUMERIC,
    ID_Empresa INTEGER,
    FOREIGN KEY (ID_Proveedor) REFERENCES Proveedores(ID_Proveedor),
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa)
)

CREATE TABLE Movimientos_Inventario (
    ID_Movimiento INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_TipoMovimiento INTEGER,
    N_Factura TEXT,
    Contado_Credito INTEGER,
    Fecha DATE,
    ID_Proveedor INTEGER,
    Observacion TEXT,
    IVA NUMERIC,
    Retencion NUMERIC,
    ID_Empresa INTEGER,
    ID_Bodega INTEGER,
    ID_Ruta INTEGER,
    UbicacionEntrega TEXT,
    FOREIGN KEY (ID_TipoMovimiento) REFERENCES Catalogo_Movimientos(ID_TipoMovimiento),
    FOREIGN KEY (ID_Proveedor) REFERENCES Proveedores(ID_Proveedor),
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa),
    FOREIGN KEY (ID_Bodega) REFERENCES Bodegas(ID_Bodega),
    FOREIGN KEY (ID_Ruta) REFERENCES Rutas(ID_Ruta)
)

CREATE TABLE Bitacora (
    ID_Bitacora INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Usuario INTEGER,
    Fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
    Modulo TEXT,
    Accion TEXT,
    IP_Acceso TEXT,
    FOREIGN KEY (ID_Usuario) REFERENCES Usuarios(ID_Usuario)
)

CREATE TABLE Detalle_Facturacion (
    ID_Detalle INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Factura INTEGER,
    ID_Producto INTEGER,
    Cantidad NUMERIC,
    Costo NUMERIC,
    Descuento NUMERIC,
    IVA NUMERIC,
    Total NUMERIC,
    FOREIGN KEY (ID_Factura) REFERENCES Facturacion(ID_Factura),
    FOREIGN KEY (ID_Producto) REFERENCES Productos(ID_Producto)
)

CREATE TABLE Inventario_Bodega (
    ID_Bodega INTEGER,
    ID_Producto INTEGER,
    Existencias NUMERIC DEFAULT 0,
    PRIMARY KEY (ID_Bodega, ID_Producto),
    FOREIGN KEY (ID_Bodega) REFERENCES Bodegas(ID_Bodega),
    FOREIGN KEY (ID_Producto) REFERENCES Productos(ID_Producto)
)

CREATE TABLE Productos (
    ID_Producto INTEGER PRIMARY KEY AUTOINCREMENT,
    COD_Producto TEXT,
    Descripcion TEXT NOT NULL,
    Unidad_Medida INTEGER,
    Existencias NUMERIC DEFAULT 0,
    Estado INTEGER DEFAULT 1,
    Familia INTEGER,
    Costo_Promedio NUMERIC,
    IVA INTEGER DEFAULT 0,
    Tipo INTEGER,
    Precio_Venta NUMERIC,
    ID_Empresa INTEGER,
    Fecha_Creacion DATE DEFAULT CURRENT_DATE,
    Usuario_Creador INTEGER, Stock_Minimo NUMERIC DEFAULT 5,
    FOREIGN KEY (Unidad_Medida) REFERENCES Unidades_Medida(ID_Unidad),
    FOREIGN KEY (Familia) REFERENCES Familia(ID_Familia),
    FOREIGN KEY (Tipo) REFERENCES Tipo_Producto(ID_TipoProducto),
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa)
)

CREATE VIEW Vista_Compras AS
SELECT 
    mi.ID_Movimiento AS ID_Compra,
    mi.Fecha,
    p.Nombre AS Proveedor,
    mi.N_Factura,
    mi.Observacion,
    SUM(dmi.Costo_Total) AS Total
FROM Movimientos_Inventario mi
JOIN Proveedores p ON p.ID_Proveedor = mi.ID_Proveedor
JOIN Detalle_Movimiento_Inventario dmi ON dmi.ID_Movimiento = mi.ID_Movimiento
WHERE mi.ID_TipoMovimiento = (SELECT ID_TipoMovimiento FROM Catalogo_Movimientos WHERE Descripcion = 'Compra')
GROUP BY mi.ID_Movimiento

CREATE TABLE Factura_Alterna (
    ID_Factura INTEGER PRIMARY KEY AUTOINCREMENT,
    Fecha DATE NOT NULL,
    IDCliente INTEGER NOT NULL,
    Credito_Contado INTEGER,
    Observacion TEXT,
    ID_Empresa INTEGER NOT NULL,
    FOREIGN KEY (IDCliente) REFERENCES Clientes(ID_Cliente),
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa)
)

CREATE TABLE Detalle_Factura_Alterna (
    ID_Detalle INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Factura INTEGER,
    ID_Producto INTEGER,
    Cantidad NUMERIC,
    Costo NUMERIC,
    Total NUMERIC,
    FOREIGN KEY (ID_Factura) REFERENCES Factura_Alterna(ID_Factura),
    FOREIGN KEY (ID_Producto) REFERENCES Productos(ID_Producto)
)

CREATE TABLE Detalles_Pago (
    ID_Detalle INTEGER PRIMARY KEY,
    ID_Pago INTEGER,
    Tipo_Metodo TEXT CHECK(Tipo_Metodo IN ('efectivo', 'transferencia', 'tarjeta')),
    Campo TEXT,  -- Ej: 'banco', 'ultimos_digitos'
    Valor TEXT,  -- Ej: 'BAC', '1234'
    FOREIGN KEY (ID_Pago) REFERENCES Pagos_CuentasCobrar(ID_Pago)
)

CREATE TABLE Metodos_Pago (
    ID_MetodoPago INTEGER PRIMARY KEY AUTOINCREMENT,
    Nombre TEXT NOT NULL
)

CREATE TABLE Detalle_Cuentas_Por_Cobrar (
    ID_Factura INTEGER PRIMARY KEY AUTOINCREMENT,
    Fecha DATE,
    ID_Cliente INTEGER NOT NULL,
    Num_Documento TEXT,
    Observacion TEXT,
    Fecha_Vencimiento DATE,
    Tipo_Movimiento INTEGER,
    Monto_Movimiento NUMERIC,
    IVA NUMERIC,
    Retencion NUMERIC,
    ID_Empresa INTEGER,
    FOREIGN KEY (ID_Cliente) REFERENCES Clientes(ID_Cliente),
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa)
)

CREATE TABLE Pagos_CuentasCobrar (
    ID_Pago INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Factura INTEGER,
    Fecha DATETIME,
    Monto NUMERIC(12,2),
    ID_MetodoPago INTEGER,
    Comentarios TEXT,
    FOREIGN KEY (ID_Factura) REFERENCES Facturacion(ID_Factura),
    FOREIGN KEY (ID_MetodoPago) REFERENCES Metodos_Pago(ID_MetodoPago)
)
--Aun no se ha implementado la tabla de Facturacion
CREATE TABLE Facturacion (
    ID_Factura INTEGER PRIMARY KEY AUTOINCREMENT,
    Fecha DATE NOT NULL,
    IDCliente INTEGER NOT NULL,
    Credito_Contado INTEGER,
    Observacion TEXT,
    Total_Factura NUMERIC NOT NULL,  -- ESTE CAMPO ES CLAVE
    ID_Empresa INTEGER NOT NULL,
    FOREIGN KEY (IDCliente) REFERENCES Clientes(ID_Cliente),
    FOREIGN KEY (ID_Empresa) REFERENCES Empresa(ID_Empresa)
);

