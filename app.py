from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, Response, stream_with_context, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import os
import json
import time
import threading
import logging
from io import BytesIO

try:
    from fpdf import FPDF
except ImportError:
    print("FPDF no está instalado. Instalando...")
    os.system("pip install fpdf2")
    from fpdf import FPDF

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sabirus-warmi-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sabirus_warmi.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

db = SQLAlchemy(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== MODELOS ====================
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    es_admin_principal = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text)
    precio = db.Column(db.Float, nullable=False)
    precio_alquiler_dia = db.Column(db.Float, default=0)
    disponible_alquiler = db.Column(db.Boolean, default=False)
    stock = db.Column(db.Integer, default=0)
    stock_minimo = db.Column(db.Integer, default=5)
    proveedor = db.Column(db.String(100))
    imagen = db.Column(db.String(200))
    activo = db.Column(db.Boolean, default=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(100))
    direccion = db.Column(db.String(200))
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    ventas = db.relationship('Venta', backref='cliente', lazy=True, cascade='all, delete-orphan')
    alquileres = db.relationship('Alquiler', backref='cliente', lazy=True, cascade='all, delete-orphan')

class Venta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    total = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    metodo_pago = db.Column(db.String(50))
    detalles = db.relationship('DetalleVenta', backref='venta', lazy=True, cascade='all, delete-orphan')
    usuario = db.relationship('Usuario', backref='ventas')

class DetalleVenta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    venta_id = db.Column(db.Integer, db.ForeignKey('venta.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    producto = db.relationship('Producto', backref='detalles_venta')

class Alquiler(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    fecha_inicio = db.Column(db.DateTime, nullable=False)
    fecha_fin = db.Column(db.DateTime, nullable=False)
    fecha_devolucion_real = db.Column(db.DateTime)
    total = db.Column(db.Float, nullable=False)
    deposito = db.Column(db.Float, default=0)
    estado = db.Column(db.String(50), default='activo')
    metodo_pago = db.Column(db.String(50))
    notas = db.Column(db.Text)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    detalles = db.relationship('DetalleAlquiler', backref='alquiler', lazy=True, cascade='all, delete-orphan')
    usuario = db.relationship('Usuario', backref='alquileres')

class DetalleAlquiler(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alquiler_id = db.Column(db.Integer, db.ForeignKey('alquiler.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    precio_dia = db.Column(db.Float, nullable=False)
    dias = db.Column(db.Integer, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    producto = db.relationship('Producto', backref='detalles_alquiler')

class ReporteMensual(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    mes = db.Column(db.String(50), nullable=False)
    total_ventas = db.Column(db.Integer, default=0)
    total_ingresos = db.Column(db.Float, default=0)
    promedio_venta = db.Column(db.Float, default=0)
    total_alquileres = db.Column(db.Integer, default=0)
    ingresos_alquileres = db.Column(db.Float, default=0)
    
    productos_json = db.Column(db.Text)
    clientes_json = db.Column(db.Text)
    clientes_nuevos_json = db.Column(db.Text)
    productos_stock_bajo_json = db.Column(db.Text)
    ventas_por_dia_json = db.Column(db.Text)
    ventas_por_metodo_pago_json = db.Column(db.Text)
    productos_mas_reabastecidos_json = db.Column(db.Text)
    ventas_por_tipo_producto_json = db.Column(db.Text)
    alquileres_activos_json = db.Column(db.Text)
    productos_mas_alquilados_json = db.Column(db.Text)
    
    fecha_generacion = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== CLASE PDF ====================
class PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)
        
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'SABIRUS WARMI', 0, 1, 'C')
        self.set_font('Arial', 'I', 10)
        self.cell(0, 5, 'Reporte Mensual Completo', 0, 1, 'C')
        self.ln(5)
        
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')
        
    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.set_fill_color(240, 240, 240)
        self.cell(0, 8, title, 0, 1, 'L', True)
        self.ln(2)
        
    def chapter_body(self, body):
        self.set_font('Arial', '', 10)
        self.multi_cell(0, 5, body)
        self.ln()

# ==================== IA CON PRECARGA AUTOMÁTICA ====================
class AsistenteIA:
    def __init__(self):
        self.modelo = None
        self.cargando = False
        self.carga_completa = False
        self.error_carga = None
        self._lock = threading.Lock()
        
        self.rutas_modelo = [
            "modelo/gemma-2b-it-q4_k_m.gguf",
        ]
        
        logger.info("Iniciando precarga del modelo IA...")
        self._iniciar_carga_asincrona()
    
    def _iniciar_carga_asincrona(self):
        threading.Thread(target=self._cargar_modelo, daemon=True).start()
    
    def _cargar_modelo(self):
        with self._lock:
            if self.cargando or self.carga_completa:
                return
            self.cargando = True
        
        try:
            logger.info("Buscando modelo de IA...")
            
            try:
                from llama_cpp import Llama
            except ImportError:
                raise Exception("llama-cpp-python no está instalado")
            
            ruta_encontrada = None
            for ruta in self.rutas_modelo:
                if os.path.exists(ruta):
                    ruta_encontrada = ruta
                    logger.info(f"Modelo encontrado: {ruta}")
                    break
            
            if not ruta_encontrada:
                raise Exception(f"No se encontró el modelo en las rutas")
            
            logger.info("Cargando modelo...")
            
            self.modelo = Llama(
                model_path=ruta_encontrada,
                n_ctx=4096,
                n_threads=4,
                n_gpu_layers=0,
                n_batch=512,
                verbose=False,
                use_mlock=True,
                use_mmap=True
            )
            
            with self._lock:
                self.carga_completa = True
                self.cargando = False
            
            logger.info("Modelo IA cargado exitosamente")
            
        except Exception as e:
            with self._lock:
                self.error_carga = str(e)
                self.cargando = False
            
            logger.error(f"Error al cargar modelo IA: {e}")
    
    def esta_listo(self):
        return self.carga_completa and self.modelo is not None
    
    def obtener_estado(self):
        if self.carga_completa:
            return {"estado": "listo", "mensaje": "IA operativa"}
        elif self.cargando:
            return {"estado": "cargando", "mensaje": "Cargando modelo..."}
        elif self.error_carga:
            return {"estado": "error", "mensaje": f"Error: {self.error_carga}"}
        else:
            return {"estado": "inicial", "mensaje": "Iniciando..."}
    
    def obtener_contexto_completo(self):
        productos = Producto.query.filter_by(activo=True).all()
        productos_info = []
        for p in productos:
            productos_info.append({
                'id': p.id,
                'nombre': p.nombre,
                'tipo': p.tipo,
                'precio': p.precio,
                'precio_alquiler_dia': p.precio_alquiler_dia,
                'disponible_alquiler': p.disponible_alquiler,
                'stock': p.stock,
                'stock_minimo': p.stock_minimo,
                'proveedor': p.proveedor or 'No especificado',
                'descripcion': p.descripcion or 'Sin descripción'
            })
        
        clientes = Cliente.query.all()
        clientes_info = []
        for c in clientes:
            total_compras = len(c.ventas)
            total_gastado = sum(v.total for v in c.ventas)
            total_alquileres = len(c.alquileres)
            ultima_compra = max([v.fecha for v in c.ventas]) if c.ventas else None
            
            clientes_info.append({
                'id': c.id,
                'nombre': c.nombre,
                'telefono': c.telefono or 'No registrado',
                'email': c.email or 'No registrado',
                'total_compras': total_compras,
                'total_gastado': total_gastado,
                'total_alquileres': total_alquileres,
                'ultima_compra': ultima_compra.strftime('%d/%m/%Y') if ultima_compra else 'Nunca'
            })
        
        alquileres = Alquiler.query.order_by(Alquiler.fecha_registro.desc()).limit(30).all()
        alquileres_info = []
        for a in alquileres:
            productos_alquilados = []
            for d in a.detalles:
                productos_alquilados.append({
                    'producto': d.producto.nombre,
                    'tipo': d.producto.tipo,
                    'cantidad': d.cantidad,
                    'precio_dia': d.precio_dia,
                    'dias': d.dias,
                    'subtotal': d.subtotal
                })
            
            alquileres_info.append({
                'id': a.id,
                'cliente': a.cliente.nombre,
                'fecha_inicio': a.fecha_inicio.strftime('%d/%m/%Y'),
                'fecha_fin': a.fecha_fin.strftime('%d/%m/%Y'),
                'estado': a.estado,
                'total': a.total,
                'deposito': a.deposito,
                'productos': productos_alquilados
            })
        
        ventas = Venta.query.order_by(Venta.fecha.desc()).limit(50).all()
        ventas_info = []
        for v in ventas:
            productos_vendidos = []
            for d in v.detalles:
                productos_vendidos.append({
                    'producto': d.producto.nombre,
                    'tipo': d.producto.tipo,
                    'proveedor': d.producto.proveedor or 'No especificado',
                    'cantidad': d.cantidad,
                    'precio_unitario': d.precio_unitario,
                    'subtotal': d.subtotal
                })
            
            ventas_info.append({
                'id': v.id,
                'cliente': v.cliente.nombre,
                'total': v.total,
                'fecha': v.fecha.strftime('%d/%m/%Y %H:%M'),
                'metodo_pago': v.metodo_pago,
                'productos': productos_vendidos
            })
        
        total_ventas = Venta.query.count()
        total_ingresos = db.session.query(db.func.sum(Venta.total)).scalar() or 0
        promedio_venta = (total_ingresos / total_ventas) if total_ventas > 0 else 0
        
        total_alquileres = Alquiler.query.count()
        ingresos_alquileres = db.session.query(db.func.sum(Alquiler.total)).scalar() or 0
        alquileres_activos = Alquiler.query.filter_by(estado='activo').count()
        
        productos_mas_vendidos = db.session.query(
            Producto.nombre,
            Producto.tipo,
            Producto.proveedor,
            db.func.sum(DetalleVenta.cantidad).label('total_vendido')
        ).join(DetalleVenta).group_by(Producto.id).order_by(db.desc('total_vendido')).limit(10).all()
        
        productos_mas_alquilados = db.session.query(
            Producto.nombre,
            Producto.tipo,
            db.func.sum(DetalleAlquiler.cantidad).label('total_alquilado')
        ).join(DetalleAlquiler).group_by(Producto.id).order_by(db.desc('total_alquilado')).limit(10).all()
        
        clientes_frecuentes = db.session.query(
            Cliente.nombre,
            db.func.count(Venta.id).label('compras'),
            db.func.sum(Venta.total).label('gastado')
        ).join(Venta).group_by(Cliente.id).order_by(db.desc('compras')).limit(10).all()
        
        productos_stock_bajo = Producto.query.filter(
            Producto.activo == True,
            Producto.stock <= Producto.stock_minimo
        ).all()
        
        reportes = ReporteMensual.query.order_by(ReporteMensual.fecha_generacion.desc()).limit(6).all()
        reportes_info = []
        for r in reportes:
            reportes_info.append({
                'mes': r.mes,
                'total_ventas': r.total_ventas,
                'total_ingresos': r.total_ingresos,
                'total_alquileres': r.total_alquileres,
                'ingresos_alquileres': r.ingresos_alquileres,
                'promedio': (r.total_ingresos / r.total_ventas) if r.total_ventas > 0 else 0
            })
        
        contexto = {
            'productos': productos_info,
            'clientes': clientes_info,
            'ventas_recientes': ventas_info,
            'alquileres_recientes': alquileres_info,
            'estadisticas': {
                'total_ventas': total_ventas,
                'total_ingresos': total_ingresos,
                'promedio_venta': promedio_venta,
                'total_alquileres': total_alquileres,
                'ingresos_alquileres': ingresos_alquileres,
                'alquileres_activos': alquileres_activos,
                'total_productos': len(productos),
                'total_clientes': len(clientes)
            },
            'productos_mas_vendidos': [
                {'nombre': p[0], 'tipo': p[1], 'proveedor': p[2] or 'No especificado', 'cantidad': int(p[3])} 
                for p in productos_mas_vendidos
            ],
            'productos_mas_alquilados': [
                {'nombre': p[0], 'tipo': p[1], 'cantidad': int(p[2])} 
                for p in productos_mas_alquilados
            ],
            'clientes_frecuentes': [
                {'nombre': c[0], 'compras': c[1], 'gastado': float(c[2])} 
                for c in clientes_frecuentes
            ],
            'productos_stock_bajo': [
                {'nombre': p.nombre, 'stock': p.stock, 'minimo': p.stock_minimo, 'proveedor': p.proveedor or 'No especificado'}
                for p in productos_stock_bajo
            ],
            'reportes_mensuales': reportes_info
        }
        
        return contexto

    def formatear_contexto_texto(self, contexto):
        texto = "=== SISTEMA SABIRUS WARMI - INFORMACIÓN COMPLETA ===\n\n"
        
        texto += "ESTADÍSTICAS GENERALES:\n"
        texto += f"- Total de ventas: {contexto['estadisticas']['total_ventas']}\n"
        texto += f"- Ingresos por ventas: ${contexto['estadisticas']['total_ingresos']:.2f}\n"
        texto += f"- Promedio por venta: ${contexto['estadisticas']['promedio_venta']:.2f}\n"
        texto += f"- Total de alquileres: {contexto['estadisticas']['total_alquileres']}\n"
        texto += f"- Ingresos por alquileres: ${contexto['estadisticas']['ingresos_alquileres']:.2f}\n"
        texto += f"- Alquileres activos: {contexto['estadisticas']['alquileres_activos']}\n"
        texto += f"- Total de productos: {contexto['estadisticas']['total_productos']}\n"
        texto += f"- Total de clientes: {contexto['estadisticas']['total_clientes']}\n\n"
        
        texto += "PRODUCTOS DISPONIBLES:\n"
        for p in contexto['productos']:
            estado_stock = "⚠️ BAJO" if p['stock'] <= p['stock_minimo'] else "✅"
            alquiler_info = f" | 🏠 Alquiler: ${p['precio_alquiler_dia']:.2f}/día" if p['disponible_alquiler'] else ""
            texto += f"- [{p['id']}] {p['nombre']} ({p['tipo']})\n"
            texto += f"  Proveedor: {p['proveedor']}\n"
            texto += f"  💰 Venta: ${p['precio']:.2f}{alquiler_info}\n"
            texto += f"  📦 Stock: {p['stock']} unidades {estado_stock}\n"
            texto += f"  📝 {p['descripcion']}\n"
        texto += "\n"
        
        if contexto['productos_mas_vendidos']:
            texto += "🏆 TOP 10 PRODUCTOS MÁS VENDIDOS:\n"
            for i, p in enumerate(contexto['productos_mas_vendidos'], 1):
                texto += f"{i}. {p['nombre']} ({p['tipo']}) - Proveedor: {p['proveedor']}\n"
                texto += f"   {p['cantidad']} unidades vendidas\n"
            texto += "\n"
        
        if contexto['productos_mas_alquilados']:
            texto += "🏆 TOP 10 PRODUCTOS MÁS ALQUILADOS:\n"
            for i, p in enumerate(contexto['productos_mas_alquilados'], 1):
                texto += f"{i}. {p['nombre']} ({p['tipo']}): {p['cantidad']} veces alquilado\n"
            texto += "\n"
        
        if contexto['productos_stock_bajo']:
            texto += "⚠️ PRODUCTOS CON STOCK BAJO:\n"
            for p in contexto['productos_stock_bajo']:
                texto += f"- {p['nombre']} (Proveedor: {p['proveedor']}): {p['stock']} unidades (mínimo: {p['minimo']})\n"
            texto += "\n"
        
        texto += "👥 CLIENTES:\n"
        for c in contexto['clientes'][:20]:
            texto += f"- [{c['id']}] {c['nombre']}\n"
            texto += f"  💰 Compras: {c['total_compras']} | Gastado: ${c['total_gastado']:.2f}\n"
            texto += f"  🏠 Alquileres: {c['total_alquileres']}\n"
            texto += f"  📅 Última compra: {c['ultima_compra']} | 📞 {c['telefono']}\n"
        texto += "\n"
        
        texto += "🏠 ÚLTIMOS 10 ALQUILERES:\n"
        for a in contexto['alquileres_recientes'][:10]:
            texto += f"- Alquiler #{a['id']}: {a['cliente']} - ${a['total']:.2f}\n"
            texto += f"  📅 {a['fecha_inicio']} a {a['fecha_fin']} | Estado: {a['estado']}\n"
            texto += f"  💰 Depósito: ${a['deposito']:.2f}\n"
            texto += f"  Productos: "
            for p in a['productos']:
                texto += f"{p['producto']} ({p['cantidad']}x${p['precio_dia']:.2f}/día x{p['dias']}días), "
            texto += "\n"
        texto += "\n"
        
        texto += "🛒 ÚLTIMAS 10 VENTAS:\n"
        for v in contexto['ventas_recientes'][:10]:
            texto += f"- Venta #{v['id']}: {v['cliente']} - ${v['total']:.2f}\n"
            texto += f"  📅 {v['fecha']} | Pago: {v['metodo_pago']}\n"
            texto += f"  Productos: "
            for p in v['productos']:
                texto += f"{p['producto']} ({p['cantidad']}x${p['precio_unitario']:.2f}), "
            texto += "\n"
        texto += "\n"
        
        if contexto['reportes_mensuales']:
            texto += "📊 REPORTES MENSUALES:\n"
            for r in contexto['reportes_mensuales']:
                texto += f"- {r['mes']}: {r['total_ventas']} ventas (${r['total_ingresos']:.2f}), "
                texto += f"{r['total_alquileres']} alquileres (${r['ingresos_alquileres']:.2f})\n"
            texto += "\n"
        
        return texto

    def consultar_streaming(self, pregunta):
        try:
            contexto_json = self.obtener_contexto_completo()
            contexto_texto = self.formatear_contexto_texto(contexto_json)
            
            if not self.esta_listo():
                estado = self.obtener_estado()
                
                if estado['estado'] == 'cargando':
                    msg = "El modelo IA está cargando. Mientras tanto, aquí tienes una respuesta estructurada:\n\n"
                    for char in msg:
                        yield char
                        time.sleep(0.01)
                
                respuesta = self._respuesta_sin_ia(pregunta, contexto_json)
                for char in respuesta:
                    yield char
                    time.sleep(0.01)
                return
            
            prompt = f"""Eres un asistente experto del sistema Sabirus Warmi. Respondes preguntas sobre ventas y alquileres.

{contexto_texto}

INSTRUCCIONES:
- Responde SOLO con la información disponible
- Usa formato claro con emojis
- Sé directo y conciso (máximo 4-5 líneas)
- Si preguntan por productos, busca por ID [X]
- Para alquileres, incluye fechas y estado
- NO inventes información

PREGUNTA: {pregunta}

RESPUESTA:"""

            respuesta_completa = ""
            tokens_generados = 0
            max_tokens = 200
            
            for token in self.modelo(
                prompt,
                max_tokens=max_tokens,
                temperature=0.3,
                top_p=0.9,
                stream=True,
                stop=["PREGUNTA:", "###", "\n\n\n"]
            ):
                if tokens_generados >= max_tokens:
                    break
                    
                texto = token['choices'][0]['text']
                respuesta_completa += texto
                tokens_generados += 1
                
                if any(x in respuesta_completa.lower() for x in ["¿puedo ayudarte", "¿necesitas algo", "¿algo más"]):
                    break
                
                yield texto
                
        except Exception as e:
            logger.error(f"Error en consulta IA: {e}")
            yield f"❌ Error: {str(e)}"

    def _respuesta_sin_ia(self, pregunta, contexto):
        pregunta_lower = pregunta.lower()
        
        if any(x in pregunta_lower for x in ['alquiler', 'alquilar', 'rentar']):
            if contexto['alquileres_recientes']:
                alq = contexto['alquileres_recientes'][:5]
                resp = "🏠 **Últimos Alquileres:**\n"
                for a in alq:
                    resp += f"- #{a['id']}: {a['cliente']} | ${a['total']:.2f}\n"
                    resp += f"  📅 {a['fecha_inicio']} a {a['fecha_fin']} | {a['estado']}\n"
                return resp
            return "No hay alquileres registrados aún"
        
        for p in contexto['productos']:
            if p['nombre'].lower() in pregunta_lower:
                alquiler_txt = f"\n🏠 Alquiler: ${p['precio_alquiler_dia']:.2f}/día" if p['disponible_alquiler'] else "\n❌ No disponible para alquiler"
                return f"""📦 **{p['nombre']}** ({p['tipo']})
💰 Venta: ${p['precio']:.2f}{alquiler_txt}
🏢 Proveedor: {p['proveedor']}
📦 Stock: {p['stock']} unidades
📝 {p['descripcion']}"""
        
        if any(x in pregunta_lower for x in ['estadistica', 'total', 'cuanto']):
            est = contexto['estadisticas']
            return f"""📊 **Estadísticas:**
🛒 Ventas: {est['total_ventas']} (${est['total_ingresos']:.2f})
🏠 Alquileres: {est['total_alquileres']} (${est['ingresos_alquileres']:.2f})
⏰ Alquileres activos: {est['alquileres_activos']}
📦 Productos: {est['total_productos']}
👥 Clientes: {est['total_clientes']}"""
        
        return """Puedo ayudarte con:
- 📦 Información de productos
- 🏠 Alquileres (activos, históricos, precios)
- 🛒 Ventas y estadísticas
- 👥 Clientes
- ⚠️ Alertas de stock

¿Qué necesitas?"""

logger.info("Iniciando sistema Sabirus Warmi...")
asistente_ia = AsistenteIA()

# ==================== DECORADORES ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== RUTAS ====================
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('main'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        usuario = Usuario.query.filter_by(username=username, activo=True).first()
        
        if usuario and check_password_hash(usuario.password, password):
            session['user_id'] = usuario.id
            session['username'] = usuario.username
            session['nombre'] = usuario.nombre
            session['es_admin'] = usuario.es_admin_principal
            return redirect(url_for('main'))
        else:
            flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    try:
        session.clear()
        
        if request.method == 'POST':
            return jsonify({'success': True, 'message': 'Sesión cerrada correctamente'})
        
        flash('Sesión cerrada correctamente', 'success')
        return redirect(url_for('login'))
    
    except Exception as e:
        logger.error(f"Error al cerrar sesión: {e}")
        
        if request.method == 'POST':
            return jsonify({'success': False, 'error': str(e)}), 500
        
        flash('Error al cerrar sesión', 'danger')
        return redirect(url_for('login'))

@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html')

@app.route('/main')
@login_required
def main():
    return render_template('main.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ==================== API ====================
@app.route('/api/ia/estado')
@login_required
def api_ia_estado():
    estado = asistente_ia.obtener_estado()
    return jsonify(estado)

@app.route('/api/dashboard')
@login_required
def api_dashboard():
    total_productos = Producto.query.filter_by(activo=True).count()
    total_clientes = Cliente.query.count()
    total_ventas = Venta.query.count()
    total_alquileres = Alquiler.query.count()
    alquileres_activos = Alquiler.query.filter_by(estado='activo').count()
    productos_bajo_stock = Producto.query.filter(Producto.activo == True, Producto.stock <= Producto.stock_minimo).all()
    ventas_recientes = Venta.query.order_by(Venta.fecha.desc()).limit(5).all()
    alquileres_recientes = Alquiler.query.order_by(Alquiler.fecha_registro.desc()).limit(5).all()
    
    hoy = datetime.utcnow().date()
    ventas_hoy = Venta.query.filter(db.func.date(Venta.fecha) == hoy).all()
    total_vendido_hoy = sum(v.total for v in ventas_hoy)
    
    ingresos_alquileres = db.session.query(db.func.sum(Alquiler.total)).scalar() or 0
    
    estado_ia = asistente_ia.obtener_estado()
    
    return jsonify({
        'total_productos': total_productos,
        'total_clientes': total_clientes,
        'total_ventas': total_ventas,
        'total_alquileres': total_alquileres,
        'alquileres_activos': alquileres_activos,
        'ingresos_alquileres': ingresos_alquileres,
        'total_vendido_hoy': total_vendido_hoy,
        'productos_bajo_stock': [{'nombre': p.nombre, 'stock': p.stock, 'minimo': p.stock_minimo} for p in productos_bajo_stock],
        'ventas_recientes': [{'id': v.id, 'cliente': v.cliente.nombre, 'total': v.total, 'fecha': v.fecha.strftime('%d/%m/%Y %H:%M')} for v in ventas_recientes],
        'alquileres_recientes': [{'id': a.id, 'cliente': a.cliente.nombre, 'total': a.total, 'fecha_inicio': a.fecha_inicio.strftime('%d/%m/%Y'), 'fecha_fin': a.fecha_fin.strftime('%d/%m/%Y'), 'estado': a.estado} for a in alquileres_recientes],
        'estado_ia': estado_ia
    })

@app.route('/api/chat-ia', methods=['POST'])
@login_required
def api_chat_ia():
    pregunta = request.json.get('pregunta', '')
    
    def generar():
        try:
            for chunk in asistente_ia.consultar_streaming(pregunta):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Error en chat IA: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(stream_with_context(generar()), mimetype='text/event-stream')

@app.route('/api/productos', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def api_productos():
    if request.method == 'GET':
        productos = Producto.query.filter_by(activo=True).all()
        return jsonify([{
            'id': p.id, 
            'nombre': p.nombre, 
            'tipo': p.tipo, 
            'precio': p.precio,
            'precio_alquiler_dia': p.precio_alquiler_dia,
            'disponible_alquiler': p.disponible_alquiler,
            'stock': p.stock, 
            'stock_minimo': p.stock_minimo, 
            'descripcion': p.descripcion,
            'proveedor': p.proveedor,
            'imagen': p.imagen if p.imagen else None
        } for p in productos])
    
    elif request.method == 'POST':
        try:
            imagen_path = None
            
            if 'imagen' in request.files:
                file = request.files['imagen']
                if file and file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    imagen_path = filename
            
            nombre = request.form.get('nombre')
            tipo = request.form.get('tipo')
            precio = request.form.get('precio')
            precio_alquiler_dia = request.form.get('precio_alquiler_dia', 0)
            disponible_alquiler = request.form.get('disponible_alquiler') == 'true'
            stock = request.form.get('stock')
            stock_minimo = request.form.get('stock_minimo', 5)
            descripcion = request.form.get('descripcion', '')
            proveedor = request.form.get('proveedor', '')
            
            producto = Producto(
                nombre=nombre,
                tipo=tipo,
                precio=float(precio),
                precio_alquiler_dia=float(precio_alquiler_dia),
                disponible_alquiler=disponible_alquiler,
                stock=int(stock),
                stock_minimo=int(stock_minimo),
                descripcion=descripcion,
                proveedor=proveedor,
                imagen=imagen_path
            )
            
            db.session.add(producto)
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'id': producto.id,
                'producto': {
                    'id': producto.id,
                    'nombre': producto.nombre,
                    'tipo': producto.tipo,
                    'precio': producto.precio,
                    'precio_alquiler_dia': producto.precio_alquiler_dia,
                    'disponible_alquiler': producto.disponible_alquiler,
                    'stock': producto.stock,
                    'stock_minimo': producto.stock_minimo,
                    'descripcion': producto.descripcion,
                    'proveedor': producto.proveedor,
                    'imagen': producto.imagen
                }
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400
    
    elif request.method == 'PUT':
        data = request.json
        producto = db.session.get(Producto, data['id'])
        if producto:
            producto.nombre = data['nombre']
            producto.tipo = data['tipo']
            producto.precio = float(data['precio'])
            producto.precio_alquiler_dia = float(data.get('precio_alquiler_dia', 0))
            producto.disponible_alquiler = data.get('disponible_alquiler', False)
            producto.stock = int(data['stock'])
            producto.stock_minimo = int(data.get('stock_minimo', 5))
            producto.descripcion = data.get('descripcion', '')
            producto.proveedor = data.get('proveedor', '')
            if data.get('imagen'):
                producto.imagen = data['imagen']
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False}), 404
    
    elif request.method == 'DELETE':
        producto_id = request.json.get('id')
        producto = db.session.get(Producto, producto_id)
        if producto:
            producto.activo = False
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False}), 404

@app.route('/api/clientes', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def api_clientes():
    if request.method == 'GET':
        clientes = Cliente.query.all()
        return jsonify([{
            'id': c.id, 
            'nombre': c.nombre, 
            'telefono': c.telefono, 
            'email': c.email, 
            'direccion': c.direccion, 
            'total_compras': len(c.ventas),
            'total_alquileres': len(c.alquileres)
        } for c in clientes])
    
    elif request.method == 'POST':
        data = request.json
        cliente = Cliente(nombre=data['nombre'], telefono=data.get('telefono'), 
                         email=data.get('email'), direccion=data.get('direccion'))
        db.session.add(cliente)
        db.session.commit()
        return jsonify({'success': True, 'id': cliente.id})
    
    elif request.method == 'PUT':
        data = request.json
        cliente = db.session.get(Cliente, data['id'])
        if cliente:
            cliente.nombre = data['nombre']
            cliente.telefono = data.get('telefono')
            cliente.email = data.get('email')
            cliente.direccion = data.get('direccion')
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Cliente no encontrado'}), 404
    
    elif request.method == 'DELETE':
        try:
            cliente_id = request.json.get('id')
            cliente = db.session.get(Cliente, cliente_id)
            
            if not cliente:
                return jsonify({'success': False, 'error': 'Cliente no encontrado'}), 404
            
            # Contar ventas y alquileres antes de eliminar
            total_ventas = len(cliente.ventas)
            total_alquileres = len(cliente.alquileres)
            
            # Restaurar stock de productos vendidos
            for venta in cliente.ventas:
                for detalle in venta.detalles:
                    producto = detalle.producto
                    producto.stock += detalle.cantidad
            
            # Restaurar stock de productos alquilados
            for alquiler in cliente.alquileres:
                for detalle in alquiler.detalles:
                    producto = detalle.producto
                    producto.stock += detalle.cantidad
            
            # Eliminar cliente (las ventas y alquileres se eliminan automáticamente por CASCADE)
            db.session.delete(cliente)
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Cliente eliminado correctamente',
                'ventas_eliminadas': total_ventas,
                'alquileres_eliminados': total_alquileres
            })
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al eliminar cliente: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/alquileres', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def api_alquileres():
    if request.method == 'GET':
        alquileres = Alquiler.query.order_by(Alquiler.fecha_registro.desc()).all()
        
        alquileres_por_cliente = {}
        for a in alquileres:
            cliente_nombre = a.cliente.nombre
            if cliente_nombre not in alquileres_por_cliente:
                alquileres_por_cliente[cliente_nombre] = {
                    'cliente_id': a.cliente.id,
                    'cliente': cliente_nombre,
                    'alquileres': [],
                    'total_gastado': 0,
                    'total_alquileres': 0
                }
            
            productos_detalle = [{
                'nombre': d.producto.nombre,
                'tipo': d.producto.tipo,
                'cantidad': d.cantidad,
                'precio_dia': d.precio_dia,
                'dias': d.dias,
                'subtotal': d.subtotal
            } for d in a.detalles]
            
            alquileres_por_cliente[cliente_nombre]['alquileres'].append({
                'id': a.id,
                'total': a.total,
                'deposito': a.deposito,
                'fecha_inicio': a.fecha_inicio.strftime('%d/%m/%Y'),
                'fecha_fin': a.fecha_fin.strftime('%d/%m/%Y'),
                'fecha_devolucion_real': a.fecha_devolucion_real.strftime('%d/%m/%Y') if a.fecha_devolucion_real else None,
                'estado': a.estado,
                'metodo_pago': a.metodo_pago,
                'notas': a.notas,
                'productos': productos_detalle,
                'cantidad_productos': len(a.detalles)
            })
            
            alquileres_por_cliente[cliente_nombre]['total_gastado'] += a.total
            alquileres_por_cliente[cliente_nombre]['total_alquileres'] += 1
        
        return jsonify(list(alquileres_por_cliente.values()))
    
    elif request.method == 'POST':
        try:
            data = request.json
            
            fecha_inicio = datetime.strptime(data['fecha_inicio'], '%Y-%m-%d')
            fecha_fin = datetime.strptime(data['fecha_fin'], '%Y-%m-%d')
            
            if fecha_fin <= fecha_inicio:
                return jsonify({'success': False, 'error': 'La fecha de fin debe ser posterior a la de inicio'})
            
            dias_totales = (fecha_fin - fecha_inicio).days
            
            alquiler = Alquiler(
                cliente_id=data['cliente_id'],
                usuario_id=session['user_id'],
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                total=0,
                deposito=float(data.get('deposito', 0)),
                estado='activo',
                metodo_pago=data['metodo_pago'],
                notas=data.get('notas', '')
            )
            db.session.add(alquiler)
            db.session.flush()
            
            total = 0
            for item in data['productos']:
                producto = db.session.get(Producto, item['producto_id'])
                
                if not producto.disponible_alquiler:
                    db.session.rollback()
                    return jsonify({'success': False, 'error': f'{producto.nombre} no está disponible para alquiler'})
                
                if producto.stock < item['cantidad']:
                    db.session.rollback()
                    return jsonify({'success': False, 'error': f'Stock insuficiente: {producto.nombre}'})
                
                subtotal = item['cantidad'] * producto.precio_alquiler_dia * dias_totales
                detalle = DetalleAlquiler(
                    alquiler_id=alquiler.id,
                    producto_id=producto.id,
                    cantidad=item['cantidad'],
                    precio_dia=producto.precio_alquiler_dia,
                    dias=dias_totales,
                    subtotal=subtotal
                )
                db.session.add(detalle)
                producto.stock -= item['cantidad']
                total += subtotal
            
            alquiler.total = total
            db.session.commit()
            return jsonify({'success': True, 'alquiler_id': alquiler.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    elif request.method == 'PUT':
        try:
            data = request.json
            alquiler = db.session.get(Alquiler, data['id'])
            
            if not alquiler:
                return jsonify({'success': False, 'error': 'Alquiler no encontrado'}), 404
            
            if data.get('accion') == 'finalizar':
                if alquiler.estado != 'activo':
                    return jsonify({'success': False, 'error': 'El alquiler no está activo'})
                
                for detalle in alquiler.detalles:
                    producto = detalle.producto
                    producto.stock += detalle.cantidad
                
                alquiler.estado = 'finalizado'
                alquiler.fecha_devolucion_real = datetime.utcnow()
                
                db.session.commit()
                return jsonify({'success': True, 'message': 'Alquiler finalizado y stock restaurado'})
            
            return jsonify({'success': False, 'error': 'Acción no válida'})
            
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            alquiler_id = request.json.get('id')
            alquiler = db.session.get(Alquiler, alquiler_id)
            
            if not alquiler:
                return jsonify({'success': False, 'error': 'Alquiler no encontrado'}), 404
            
            for detalle in alquiler.detalles:
                producto = detalle.producto
                producto.stock += detalle.cantidad
            
            db.session.delete(alquiler)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Alquiler eliminado y stock restaurado'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/ventas', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_ventas():
    if request.method == 'GET':
        ventas = Venta.query.order_by(Venta.fecha.desc()).all()
        
        ventas_por_cliente = {}
        for v in ventas:
            cliente_nombre = v.cliente.nombre
            if cliente_nombre not in ventas_por_cliente:
                ventas_por_cliente[cliente_nombre] = {
                    'cliente_id': v.cliente.id,
                    'cliente': cliente_nombre,
                    'ventas': [],
                    'total_gastado': 0,
                    'total_compras': 0
                }
            
            productos_detalle = [{
                'nombre': d.producto.nombre,
                'tipo': d.producto.tipo,
                'cantidad': d.cantidad,
                'precio': d.precio_unitario,
                'subtotal': d.subtotal
            } for d in v.detalles]
            
            ventas_por_cliente[cliente_nombre]['ventas'].append({
                'id': v.id,
                'total': v.total,
                'fecha': v.fecha.strftime('%d/%m/%Y %H:%M'),
                'fecha_timestamp': v.fecha.timestamp(),
                'metodo_pago': v.metodo_pago,
                'productos': productos_detalle,
                'cantidad_productos': len(v.detalles)
            })
            
            ventas_por_cliente[cliente_nombre]['total_gastado'] += v.total
            ventas_por_cliente[cliente_nombre]['total_compras'] += 1
        
        return jsonify(list(ventas_por_cliente.values()))
    
    elif request.method == 'POST':
        try:
            data = request.json
            venta = Venta(cliente_id=data['cliente_id'], usuario_id=session['user_id'], 
                         total=0, metodo_pago=data['metodo_pago'])
            db.session.add(venta)
            db.session.flush()
            
            total = 0
            for item in data['productos']:
                producto = db.session.get(Producto, item['producto_id'])
                if producto.stock < item['cantidad']:
                    db.session.rollback()
                    return jsonify({'success': False, 'error': f'Stock insuficiente: {producto.nombre}'})
                
                subtotal = item['cantidad'] * producto.precio
                detalle = DetalleVenta(venta_id=venta.id, producto_id=producto.id, 
                                      cantidad=item['cantidad'], precio_unitario=producto.precio, subtotal=subtotal)
                db.session.add(detalle)
                producto.stock -= item['cantidad']
                total += subtotal
            
            venta.total = total
            db.session.commit()
            return jsonify({'success': True, 'venta_id': venta.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})
    
    elif request.method == 'DELETE':
        try:
            venta_id = request.json.get('id')
            venta = db.session.get(Venta, venta_id)
            
            if not venta:
                return jsonify({'success': False, 'error': 'Venta no encontrada'}), 404
            
            for detalle in venta.detalles:
                producto = detalle.producto
                producto.stock += detalle.cantidad
            
            db.session.delete(venta)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Venta eliminada y stock restaurado'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reportes')
@login_required
def api_reportes():
    total_ventas = Venta.query.count()
    total_ingresos = db.session.query(db.func.sum(Venta.total)).scalar() or 0
    
    total_alquileres = Alquiler.query.count()
    ingresos_alquileres = db.session.query(db.func.sum(Alquiler.total)).scalar() or 0
    alquileres_activos = Alquiler.query.filter_by(estado='activo').count()
    
    productos_mas_vendidos = db.session.query(
        Producto.nombre,
        Producto.tipo,
        Producto.proveedor,
        db.func.sum(DetalleVenta.cantidad).label('total')
    ).join(DetalleVenta).group_by(Producto.id).order_by(db.desc('total')).limit(10).all()
    
    productos_mas_alquilados = db.session.query(
        Producto.nombre,
        Producto.tipo,
        db.func.sum(DetalleAlquiler.cantidad).label('total')
    ).join(DetalleAlquiler).group_by(Producto.id).order_by(db.desc('total')).limit(10).all()
    
    clientes_frecuentes = db.session.query(
        Cliente.nombre,
        db.func.count(Venta.id).label('compras'),
        db.func.sum(Venta.total).label('gastado')
    ).join(Venta).group_by(Cliente.id).order_by(db.desc('compras')).limit(10).all()
    
    return jsonify({
        'total_ventas': total_ventas,
        'total_ingresos': total_ingresos,
        'total_alquileres': total_alquileres,
        'ingresos_alquileres': ingresos_alquileres,
        'alquileres_activos': alquileres_activos,
        'productos_mas_vendidos': [{'nombre': p[0], 'tipo': p[1], 'proveedor': p[2], 'cantidad': p[3]} for p in productos_mas_vendidos],
        'productos_mas_alquilados': [{'nombre': p[0], 'tipo': p[1], 'cantidad': p[2]} for p in productos_mas_alquilados],
        'clientes_frecuentes': [{'nombre': c[0], 'compras': c[1], 'gastado': c[2]} for c in clientes_frecuentes]
    })

@app.route('/api/reportes/historicos')
@login_required
def api_reportes_historicos():
    reportes = ReporteMensual.query.order_by(ReporteMensual.fecha_generacion.desc()).all()
    return jsonify([{
        'id': r.id,
        'mes': r.mes,
        'total_ventas': r.total_ventas,
        'total_ingresos': r.total_ingresos,
        'promedio_venta': r.promedio_venta,
        'total_alquileres': r.total_alquileres,
        'ingresos_alquileres': r.ingresos_alquileres,
        'fecha_generacion': r.fecha_generacion.strftime('%d/%m/%Y')
    } for r in reportes])

@app.route('/api/reportes/generar', methods=['POST'])
@login_required
def api_generar_reporte():
    try:
        ahora = datetime.utcnow()
        mes_id = ahora.strftime('%Y-%m')
        mes_nombre = ahora.strftime('%B %Y')
        
        reporte_existente = ReporteMensual.query.get(mes_id)
        if reporte_existente:
            return jsonify({'success': False, 'error': 'Ya existe un reporte para este mes'}), 400
        
        inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if ahora.month == 12:
            fin_mes = ahora.replace(year=ahora.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            fin_mes = ahora.replace(month=ahora.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        ventas_mes = Venta.query.filter(Venta.fecha >= inicio_mes, Venta.fecha < fin_mes).all()
        total_ventas = len(ventas_mes)
        total_ingresos = sum(v.total for v in ventas_mes)
        promedio_venta = (total_ingresos / total_ventas) if total_ventas > 0 else 0
        
        alquileres_mes = Alquiler.query.filter(Alquiler.fecha_registro >= inicio_mes, Alquiler.fecha_registro < fin_mes).all()
        total_alquileres = len(alquileres_mes)
        ingresos_alquileres = sum(a.total for a in alquileres_mes)
        
        productos_mes = db.session.query(
            Producto.nombre,
            Producto.tipo,
            Producto.proveedor,
            db.func.sum(DetalleVenta.cantidad).label('total')
        ).join(DetalleVenta).join(Venta).filter(
            Venta.fecha >= inicio_mes,
            Venta.fecha < fin_mes
        ).group_by(Producto.id).order_by(db.desc('total')).limit(10).all()
        
        productos_json = [{'nombre': p[0], 'tipo': p[1], 'proveedor': p[2], 'cantidad': int(p[3])} for p in productos_mes]
        
        productos_alquilados = db.session.query(
            Producto.nombre,
            Producto.tipo,
            db.func.sum(DetalleAlquiler.cantidad).label('total')
        ).join(DetalleAlquiler).join(Alquiler).filter(
            Alquiler.fecha_registro >= inicio_mes,
            Alquiler.fecha_registro < fin_mes
        ).group_by(Producto.id).order_by(db.desc('total')).limit(10).all()
        
        productos_mas_alquilados_json = [{'nombre': p[0], 'tipo': p[1], 'cantidad': int(p[2])} for p in productos_alquilados]
        
        alquileres_activos = Alquiler.query.filter(
            Alquiler.estado == 'activo',
            Alquiler.fecha_registro >= inicio_mes,
            Alquiler.fecha_registro < fin_mes
        ).all()
        
        alquileres_activos_json = [{
            'cliente': a.cliente.nombre,
            'total': a.total,
            'fecha_inicio': a.fecha_inicio.strftime('%d/%m/%Y'),
            'fecha_fin': a.fecha_fin.strftime('%d/%m/%Y')
        } for a in alquileres_activos]
        
        clientes_mes = db.session.query(
            Cliente.nombre,
            db.func.count(Venta.id).label('compras'),
            db.func.sum(Venta.total).label('gastado')
        ).join(Venta).filter(
            Venta.fecha >= inicio_mes,
            Venta.fecha < fin_mes
        ).group_by(Cliente.id).order_by(db.desc('compras')).limit(10).all()
        
        clientes_json = [{'nombre': c[0], 'compras': c[1], 'gastado': float(c[2])} for c in clientes_mes]
        
        clientes_nuevos = Cliente.query.filter(
            Cliente.fecha_registro >= inicio_mes,
            Cliente.fecha_registro < fin_mes
        ).all()
        
        clientes_nuevos_json = [{
            'nombre': c.nombre,
            'fecha_registro': c.fecha_registro.strftime('%d/%m/%Y'),
            'telefono': c.telefono or 'N/A',
            'email': c.email or 'N/A'
        } for c in clientes_nuevos]
        
        productos_stock_bajo = []
        for producto in Producto.query.filter_by(activo=True).all():
            ventas_producto = db.session.query(
                db.func.sum(DetalleVenta.cantidad)
            ).join(Venta).filter(
                DetalleVenta.producto_id == producto.id,
                Venta.fecha >= inicio_mes,
                Venta.fecha < fin_mes
            ).scalar() or 0
            
            if ventas_producto > 0 and producto.stock <= producto.stock_minimo:
                productos_stock_bajo.append({
                    'nombre': producto.nombre,
                    'tipo': producto.tipo,
                    'stock_actual': producto.stock,
                    'stock_minimo': producto.stock_minimo,
                    'veces_vendido': int(ventas_producto)
                })
        
        productos_stock_bajo_json = productos_stock_bajo
        
        ventas_por_dia = {}
        for venta in ventas_mes:
            dia = venta.fecha.strftime('%d/%m')
            if dia not in ventas_por_dia:
                ventas_por_dia[dia] = {'cantidad': 0, 'total': 0}
            ventas_por_dia[dia]['cantidad'] += 1
            ventas_por_dia[dia]['total'] += venta.total
        
        ventas_por_dia_json = [
            {'dia': dia, 'cantidad': datos['cantidad'], 'total': datos['total']}
            for dia, datos in sorted(ventas_por_dia.items())
        ]
        
        ventas_por_metodo = {}
        for venta in ventas_mes:
            metodo = venta.metodo_pago
            if metodo not in ventas_por_metodo:
                ventas_por_metodo[metodo] = {'cantidad': 0, 'total': 0}
            ventas_por_metodo[metodo]['cantidad'] += 1
            ventas_por_metodo[metodo]['total'] += venta.total
        
        ventas_por_metodo_pago_json = [
            {'metodo': metodo, 'cantidad': datos['cantidad'], 'total': datos['total']}
            for metodo, datos in ventas_por_metodo.items()
        ]
        
        productos_mas_reabastecidos_json = productos_json[:5]
        
        ventas_por_tipo = db.session.query(
            Producto.tipo,
            db.func.sum(DetalleVenta.cantidad).label('cantidad'),
            db.func.sum(DetalleVenta.subtotal).label('total')
        ).join(DetalleVenta).join(Venta).filter(
            Venta.fecha >= inicio_mes,
            Venta.fecha < fin_mes
        ).group_by(Producto.tipo).all()
        
        ventas_por_tipo_producto_json = [
            {'tipo': t[0], 'cantidad': int(t[1]), 'total': float(t[2])}
            for t in ventas_por_tipo
        ]
        
        reporte = ReporteMensual(
            id=mes_id,
            mes=mes_nombre,
            total_ventas=total_ventas,
            total_ingresos=total_ingresos,
            promedio_venta=promedio_venta,
            total_alquileres=total_alquileres,
            ingresos_alquileres=ingresos_alquileres,
            productos_json=json.dumps(productos_json),
            clientes_json=json.dumps(clientes_json),
            clientes_nuevos_json=json.dumps(clientes_nuevos_json),
            productos_stock_bajo_json=json.dumps(productos_stock_bajo_json),
            ventas_por_dia_json=json.dumps(ventas_por_dia_json),
            ventas_por_metodo_pago_json=json.dumps(ventas_por_metodo_pago_json),
            productos_mas_reabastecidos_json=json.dumps(productos_mas_reabastecidos_json),
            ventas_por_tipo_producto_json=json.dumps(ventas_por_tipo_producto_json),
            alquileres_activos_json=json.dumps(alquileres_activos_json),
            productos_mas_alquilados_json=json.dumps(productos_mas_alquilados_json)
        )
        
        db.session.add(reporte)
        db.session.commit()
        
        return jsonify({'success': True, 'reporte_id': mes_id})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al generar reporte: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reportes/<reporte_id>')
@login_required
def api_obtener_reporte(reporte_id):
    reporte = ReporteMensual.query.get(reporte_id)
    if not reporte:
        return jsonify({'error': 'Reporte no encontrado'}), 404
    
    return jsonify({
        'id': reporte.id,
        'mes': reporte.mes,
        'total_ventas': reporte.total_ventas,
        'total_ingresos': reporte.total_ingresos,
        'promedio_venta': reporte.promedio_venta,
        'total_alquileres': reporte.total_alquileres,
        'ingresos_alquileres': reporte.ingresos_alquileres,
        'productos_mas_vendidos': json.loads(reporte.productos_json) if reporte.productos_json else [],
        'productos_mas_alquilados': json.loads(reporte.productos_mas_alquilados_json) if reporte.productos_mas_alquilados_json else [],
        'alquileres_activos': json.loads(reporte.alquileres_activos_json) if reporte.alquileres_activos_json else [],
        'clientes_frecuentes': json.loads(reporte.clientes_json) if reporte.clientes_json else [],
        'clientes_nuevos': json.loads(reporte.clientes_nuevos_json) if reporte.clientes_nuevos_json else [],
        'productos_stock_bajo': json.loads(reporte.productos_stock_bajo_json) if reporte.productos_stock_bajo_json else [],
        'ventas_por_dia': json.loads(reporte.ventas_por_dia_json) if reporte.ventas_por_dia_json else [],
        'ventas_por_metodo_pago': json.loads(reporte.ventas_por_metodo_pago_json) if reporte.ventas_por_metodo_pago_json else [],
        'productos_mas_reabastecidos': json.loads(reporte.productos_mas_reabastecidos_json) if reporte.productos_mas_reabastecidos_json else [],
        'ventas_por_tipo_producto': json.loads(reporte.ventas_por_tipo_producto_json) if reporte.ventas_por_tipo_producto_json else [],
        'fecha_generacion': reporte.fecha_generacion.strftime('%d/%m/%Y')
    })

@app.route('/api/reportes/<reporte_id>', methods=['DELETE'])
@login_required
def api_eliminar_reporte(reporte_id):
    try:
        reporte = ReporteMensual.query.get(reporte_id)
        if not reporte:
            return jsonify({'success': False, 'error': 'Reporte no encontrado'}), 404
        
        db.session.delete(reporte)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Reporte eliminado correctamente'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al eliminar reporte: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reportes/<reporte_id>/descargar')
@login_required
def api_descargar_reporte(reporte_id):
    reporte = ReporteMensual.query.get(reporte_id)
    if not reporte:
        return jsonify({'error': 'Reporte no encontrado'}), 404
    
    pdf = PDF()
    pdf.add_page()
    
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, f'Mes: {reporte.mes}', 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 8, f'Fecha de generacion: {reporte.fecha_generacion.strftime("%d/%m/%Y %H:%M")}', 0, 1)
    pdf.ln(5)
    
    pdf.chapter_title('RESUMEN GENERAL')
    resumen = f'''Ventas: {reporte.total_ventas} ($ {reporte.total_ingresos:.2f})
Promedio por Venta: $ {reporte.promedio_venta:.2f}
Alquileres: {reporte.total_alquileres} ($ {reporte.ingresos_alquileres:.2f})'''
    pdf.chapter_body(resumen)
    
    productos = json.loads(reporte.productos_json) if reporte.productos_json else []
    if productos:
        pdf.chapter_title('PRODUCTOS MAS VENDIDOS')
        texto_productos = ''
        for i, p in enumerate(productos, 1):
            texto_productos += f"{i}. {p['nombre']} ({p['tipo']})\n"
            texto_productos += f"   Proveedor: {p.get('proveedor', 'No especificado')}\n"
            texto_productos += f"   Cantidad: {p['cantidad']} unidades\n\n"
        pdf.chapter_body(texto_productos)
    
    productos_alquilados = json.loads(reporte.productos_mas_alquilados_json) if reporte.productos_mas_alquilados_json else []
    if productos_alquilados:
        pdf.chapter_title('PRODUCTOS MAS ALQUILADOS')
        texto_alq = ''
        for i, p in enumerate(productos_alquilados, 1):
            texto_alq += f"{i}. {p['nombre']} ({p['tipo']}): {p['cantidad']} veces\n"
        pdf.chapter_body(texto_alq)
    
    alquileres_activos = json.loads(reporte.alquileres_activos_json) if reporte.alquileres_activos_json else []
    if alquileres_activos:
        pdf.chapter_title(f'ALQUILERES ACTIVOS ({len(alquileres_activos)})')
        texto_activos = ''
        for i, a in enumerate(alquileres_activos, 1):
            texto_activos += f"{i}. {a['cliente']} - $ {a['total']:.2f}\n"
            texto_activos += f"   {a['fecha_inicio']} a {a['fecha_fin']}\n\n"
        pdf.chapter_body(texto_activos)
    
    clientes = json.loads(reporte.clientes_json) if reporte.clientes_json else []
    if clientes:
        pdf.chapter_title('CLIENTES FRECUENTES DEL MES')
        texto_clientes = ''
        for i, c in enumerate(clientes, 1):
            texto_clientes += f"{i}. {c['nombre']}: {c['compras']} compras - $ {c['gastado']:.2f}\n"
        pdf.chapter_body(texto_clientes)
    
    clientes_nuevos = json.loads(reporte.clientes_nuevos_json) if reporte.clientes_nuevos_json else []
    if clientes_nuevos:
        pdf.chapter_title(f'NUEVOS CLIENTES REGISTRADOS ({len(clientes_nuevos)})')
        texto_nuevos = ''
        for i, c in enumerate(clientes_nuevos, 1):
            texto_nuevos += f"{i}. {c['nombre']} - Registrado: {c['fecha_registro']}\n"
            texto_nuevos += f"   Telefono: {c['telefono']} | Email: {c['email']}\n\n"
        pdf.chapter_body(texto_nuevos)
    
    productos_stock_bajo = json.loads(reporte.productos_stock_bajo_json) if reporte.productos_stock_bajo_json else []
    if productos_stock_bajo:
        pdf.chapter_title(f'PRODUCTOS CON STOCK BAJO ({len(productos_stock_bajo)})')
        texto_stock = ''
        for i, p in enumerate(productos_stock_bajo, 1):
            texto_stock += f"{i}. {p['nombre']} ({p['tipo']})\n"
            texto_stock += f"   Stock actual: {p['stock_actual']} | Minimo: {p['stock_minimo']}\n"
            texto_stock += f"   Veces vendido este mes: {p['veces_vendido']}\n\n"
        pdf.chapter_body(texto_stock)
    
    ventas_por_dia = json.loads(reporte.ventas_por_dia_json) if reporte.ventas_por_dia_json else []
    if ventas_por_dia:
        pdf.chapter_title('VENTAS POR DIA DEL MES')
        texto_dias = ''
        for v in ventas_por_dia:
            texto_dias += f"{v['dia']}: {v['cantidad']} ventas - $ {v['total']:.2f}\n"
        pdf.chapter_body(texto_dias)
    
    ventas_por_metodo = json.loads(reporte.ventas_por_metodo_pago_json) if reporte.ventas_por_metodo_pago_json else []
    if ventas_por_metodo:
        pdf.chapter_title('VENTAS POR METODO DE PAGO')
        texto_metodos = ''
        for v in ventas_por_metodo:
            texto_metodos += f"{v['metodo']}: {v['cantidad']} ventas - $ {v['total']:.2f}\n"
        pdf.chapter_body(texto_metodos)
    
    productos_reabastecidos = json.loads(reporte.productos_mas_reabastecidos_json) if reporte.productos_mas_reabastecidos_json else []
    if productos_reabastecidos:
        pdf.chapter_title('PRODUCTOS CON MAYOR DEMANDA')
        pdf.set_font('Arial', '', 9)
        pdf.multi_cell(0, 5, 'Estos productos requieren reabastecimiento frecuente')
        pdf.ln(2)
        pdf.set_font('Arial', '', 10)
        texto_demanda = ''
        for i, p in enumerate(productos_reabastecidos, 1):
            texto_demanda += f"{i}. {p['nombre']} ({p['tipo']})\n"
            texto_demanda += f"   Proveedor: {p.get('proveedor', 'No especificado')}\n"
            texto_demanda += f"   Cantidad: {p['cantidad']} unidades\n\n"
        pdf.chapter_body(texto_demanda)
    
    ventas_por_tipo = json.loads(reporte.ventas_por_tipo_producto_json) if reporte.ventas_por_tipo_producto_json else []
    if ventas_por_tipo:
        pdf.chapter_title('VENTAS POR CATEGORIA')
        texto_categorias = ''
        for v in ventas_por_tipo:
            texto_categorias += f"{v['tipo'].capitalize()}: {v['cantidad']} unidades - $ {v['total']:.2f}\n"
        pdf.chapter_body(texto_categorias)
    
    pdf_output = BytesIO()
    pdf_string = pdf.output(dest='S').encode('latin-1')
    pdf_output.write(pdf_string)
    pdf_output.seek(0)
    
    return send_file(
        pdf_output,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'reporte_completo_{reporte_id}.pdf'
    )

# ==================== INICIALIZACIÓN ====================
def init_db():
    with app.app_context():
        db.create_all()
        admin = Usuario.query.filter_by(username='admin').first()
        if not admin:
            admin = Usuario(username='admin', password=generate_password_hash('admin123'),
                          nombre='Administrador Principal', es_admin_principal=True)
            db.session.add(admin)
            db.session.commit()
            logger.info("✅ Admin creado - Usuario: admin, Contraseña: admin123")

if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/uploads', exist_ok=True)
    os.makedirs('modelo', exist_ok=True)
    
    init_db()
    
    logger.info("=" * 60)
    logger.info("SISTEMA SABIRUS WARMI CON ALQUILERES")
    logger.info("=" * 60)
    logger.info("Servidor: http://localhost:5000")
    logger.info("Usuario: admin | Contraseña: admin123")
    logger.info("Sistema IA: Cargando en segundo plano...")
    logger.info("Nuevas funciones: Alquileres de productos")
    logger.info("=" * 60)
    
    def verificar_ia():
        time.sleep(3)
        estado = asistente_ia.obtener_estado()
        logger.info(f"Estado IA: {estado['mensaje']}")
    
    threading.Thread(target=verificar_ia, daemon=True).start()
    
    app.run(debug=True, host='0.0.0.0', port=5000)