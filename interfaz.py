"""
Interfaz gráfica del compilador de C++ (Tkinter).

Fases: Léxico → Sintáctico → Semántico → Código intermedio → Ejecución.
Este proyecto implementa Léxico, Sintáctico y Semántico. El semántico está en
semantico.py y se conecta solo: la interfaz llama a
    analizar(arbol, tokens) -> dict(errores=[...], simbolos=[...], pasos=[...])
cuando no hay errores sintácticos y anima sus pasos (la tabla de símbolos se
llena conforme avanza). Ver LEEME.md.
"""
import importlib
import os
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

import lexico
import sintactico

DIR = os.path.dirname(os.path.abspath(__file__))

TEMAS = {
    "oscuro": dict(
        fondo="#0b1120", panel="#0f1729", panel2="#131d33", borde="#22304a",
        texto="#e6edf7", tenue="#8392ab", muy_tenue="#56637a", acento="#6d8dff",
        acento_bg="#1a2a55", ok="#3dd68c", err="#ff6b81", err_bg="#3b1520",
        err_borde="#c2475c", err_linea="#2a1420", sel="#24407a", editor="#0c1322",
        kw="#7c9cff", tipo="#4fc9e0", cadena="#e9a46a", numero="#f2c66d",
        comentario="#5d6e8c", ident="#d2defa", boton="#141e33", boton_hover="#1c2a47",
        boton_borde="#28385a", actual_bg="#f2c94c", actual_fg="#151000", info_bg="#14244a",
        info_borde="#3557b5", chip="#1a2540",
    ),
    "claro": dict(
        fondo="#eef1f6", panel="#ffffff", panel2="#f5f7fb", borde="#d6dce7",
        texto="#18202e", tenue="#5b677c", muy_tenue="#9aa5b8", acento="#3d63e0",
        acento_bg="#e3e9fd", ok="#1f9d5c", err="#d63650", err_bg="#fde8eb",
        err_borde="#e58a99", err_linea="#fff1f3", sel="#cfdcff", editor="#ffffff",
        kw="#2f55d4", tipo="#0b8aa3", cadena="#b5621b", numero="#a8740b",
        comentario="#8a96aa", ident="#1e2a40", boton="#ffffff", boton_hover="#eef2fb",
        boton_borde="#cfd6e3", actual_bg="#ffd84d", actual_fg="#151000", info_bg="#e9efff",
        info_borde="#9db3f2", chip="#eef2fa",
    ),
}

BIBLIOTECA = {"std", "cout", "cin", "cerr", "endl", "string", "vector", "map", "set",
              "size_t", "include", "define", "exception", "pair", "printf", "scanf"}

FASES = ["Léxico", "Sintáctico", "Semántico", "Código intermedio", "Ejecución"]


def elegir_fuente(candidatas, defecto):
    disponibles = set(tkfont.families())
    return next((f for f in candidatas if f in disponibles), defecto)


class Boton(tk.Label):
    """Botón plano que respeta el tema en cualquier sistema operativo."""

    def __init__(self, app, padre, texto, comando, primario=False):
        super().__init__(padre, text=texto, padx=14, pady=6, cursor="hand2",
                         font=app.f_ui, highlightthickness=1)
        self.app, self.comando, self.primario = app, comando, primario
        self.activo = True
        self.bind("<Enter>", lambda e: self.pintar(hover=True))
        self.bind("<Leave>", lambda e: self.pintar())
        self.bind("<Button-1>", lambda e: self.activo and self.comando())
        app.botones.append(self)

    def habilitar(self, si=True):
        self.activo = si
        self.pintar()

    def pintar(self, hover=False):
        T = self.app.T
        fondo = T["boton_hover"] if (hover and self.activo) else T["boton"]
        self.configure(bg=fondo, fg=T["texto"] if self.activo else T["muy_tenue"],
                       highlightbackground=T["boton_borde"], highlightcolor=T["boton_borde"],
                       cursor="hand2" if self.activo else "arrow")


class App:
    def __init__(self, root):
        self.root = root
        root.title("Compilador de C++")
        root.geometry("1500x930")
        root.minsize(1150, 720)
        self.tema = "oscuro"
        self.T = TEMAS[self.tema]
        self.temables = []      # (widget, {opción: rol})
        self.botones = []
        self.archivo = "programa.cpp"

        self.f_ui = (elegir_fuente(["Inter", "Segoe UI", "SF Pro Text", "Ubuntu", "DejaVu Sans"], "TkDefaultFont"), 10)
        fam = self.f_ui[0]
        self.f_ui_b = (fam, 10, "bold")
        self.f_titulo = (fam, 17, "bold")
        self.f_peq = (fam, 9)
        self.f_card = (fam, 11, "bold")
        mono = elegir_fuente(["JetBrains Mono", "Cascadia Code", "Consolas", "Menlo",
                              "DejaVu Sans Mono", "Courier New"], "TkFixedFont")
        self.f_mono = (mono, 11)
        self.f_mono_peq = (mono, 9)
        self.f_mono_b = (mono, 11, "bold")

        # estado de la ejecución
        self.gen = None
        self.pausado = False
        self.tick_id = None
        self.res = None
        self.fase_actual = -1
        self.paso_actual = 0
        self.total_pasos = 0
        self.estado_fases = ["pendiente"] * 5
        self.sub_fases = [""] * 5
        self.progreso_fases = [0.0] * 5
        self.estado_lineas = {}
        self.errores = []
        self.nodos_insertados = set()

        self.construir()
        self.aplicar_tema()
        self.atajos()
        self.cargar_ejemplo(os.path.join(DIR, "ejemplos", "correcto.cpp"))
        self.reiniciar_resultados()

    # ═══════════════════════════ construcción ═══════════════════════════
    def pinta(self, w, **roles):
        self.temables.append((w, roles))
        return w

    def construir(self):
        r = self.root
        self.pinta(r, bg="fondo")

        # ── encabezado ──
        cab = self.pinta(tk.Frame(r, padx=20, pady=12), bg="panel")
        cab.pack(fill="x")
        izq = self.pinta(tk.Frame(cab), bg="panel")
        izq.pack(side="left")
        self.pinta(tk.Label(izq, text="Compilador de C++", font=self.f_titulo), bg="panel", fg="texto").pack(anchor="w")
        self.pinta(tk.Label(izq, font=self.f_ui,
                            text="Léxico, sintáctico, semántico, código intermedio y ejecución, paso a paso con retraso ajustable."),
                   bg="panel", fg="tenue").pack(anchor="w")
        seg = self.pinta(tk.Frame(cab, highlightthickness=1), bg="panel2", highlightbackground="borde")
        seg.pack(side="right")
        self.b_claro = tk.Label(seg, text="☀  Claro", padx=12, pady=5, font=self.f_ui, cursor="hand2")
        self.b_oscuro = tk.Label(seg, text="☾  Oscuro", padx=12, pady=5, font=self.f_ui_b, cursor="hand2")
        self.b_claro.pack(side="left"); self.b_oscuro.pack(side="left")
        self.b_claro.bind("<Button-1>", lambda e: self.cambiar_tema("claro"))
        self.b_oscuro.bind("<Button-1>", lambda e: self.cambiar_tema("oscuro"))

        # ── barra de herramientas ──
        bar = self.pinta(tk.Frame(r, padx=14, pady=10), bg="fondo")
        bar.pack(fill="x")
        Boton(self, bar, "🗀  Abrir .cpp", self.abrir).pack(side="left", padx=(0, 6))
        self.b_ejemplos = Boton(self, bar, "Ejemplos  ▾", self.menu_ejemplos)
        self.b_ejemplos.pack(side="left", padx=6)
        Boton(self, bar, "🗑  Limpiar", self.limpiar).pack(side="left", padx=6)
        self.pinta(tk.Frame(bar, width=1, height=26), bg="borde").pack(side="left", padx=10)
        self.b_compilar = Boton(self, bar, "▷  Compilar (F5)", self.compilar)
        self.b_pausar = Boton(self, bar, "❙❙  Pausar (F6)", self.pausar)
        self.b_paso = Boton(self, bar, "▷❙  Paso (F10)", self.paso)
        self.b_terminar = Boton(self, bar, "▷▷  Terminar", self.terminar)
        self.b_detener = Boton(self, bar, "▢  Detener (Esc)", self.detener)
        for b in (self.b_compilar, self.b_pausar, self.b_paso, self.b_terminar, self.b_detener):
            b.pack(side="left", padx=4)
        self.b_exportar = Boton(self, bar, "⤓  Exportar informe", self.exportar)
        self.b_exportar.pack(side="right")

        # ── velocidad ──
        vel = self.pinta(tk.Frame(r, padx=16), bg="fondo")
        vel.pack(fill="x")
        self.pinta(tk.Label(vel, text="Velocidad · Avance:", font=self.f_ui), bg="fondo", fg="tenue").pack(side="left")
        self.modo = tk.StringVar(value="paso")
        for txt, val in (("por paso", "paso"), ("por fase", "fase")):
            self.pinta(tk.Radiobutton(vel, text=txt, value=val, variable=self.modo, font=self.f_ui,
                                      bd=0, highlightthickness=0),
                       bg="fondo", fg="texto", selectcolor="panel2", activebackground="fondo",
                       activeforeground="texto").pack(side="left", padx=(8, 0))
        self.pinta(tk.Label(vel, text="Retraso:", font=self.f_ui), bg="fondo", fg="tenue").pack(side="left", padx=(24, 6))
        self.retraso = tk.IntVar(value=200)
        self.escala = ttk.Scale(vel, from_=0, to=1000, orient="horizontal", length=170,
                                style="C.Horizontal.TScale", value=200,
                                command=lambda v: (self.retraso.set(int(float(v)) // 10 * 10),
                                                   self.l_ms.config(text=f"{self.retraso.get()} ms")))
        self.escala.pack(side="left")
        self.l_ms = self.pinta(tk.Label(vel, text="200 ms", font=self.f_mono_b, width=7), bg="fondo", fg="texto")
        self.l_ms.pack(side="left", padx=6)
        self.pinta(tk.Label(vel, text="(0 ms = sin pausa; se puede cambiar mientras compila)", font=self.f_ui),
                   bg="fondo", fg="tenue").pack(side="left")
        ley = self.pinta(tk.Frame(vel), bg="fondo")
        ley.pack(side="right")
        for txt, rol in (("fase hecha", "ok"), ("en curso", "acento"), ("error", "err")):
            self.pinta(tk.Label(ley, text="■", font=self.f_peq), bg="fondo", fg=rol).pack(side="left", padx=(10, 2))
            self.pinta(tk.Label(ley, text=txt, font=self.f_peq), bg="fondo", fg="tenue").pack(side="left")

        # ── tarjetas de fases ──
        cont = self.pinta(tk.Frame(r, highlightthickness=1), bg="panel", highlightbackground="borde")
        cont.pack(fill="x", padx=14, pady=10)
        self.cards = []
        for i, nombre in enumerate(FASES):
            if i:
                self.pinta(tk.Frame(cont, width=1), bg="borde").pack(side="left", fill="y", pady=12)
            c = tk.Frame(cont, padx=16, pady=10)
            c.pack(side="left", fill="both", expand=True)
            ico = tk.Canvas(c, width=40, height=40, highlightthickness=0)
            ico.pack(side="left", padx=(0, 12))
            txt = tk.Frame(c)
            txt.pack(side="left", fill="x", expand=True)
            t = tk.Label(txt, text=nombre, font=self.f_card, anchor="w")
            t.pack(fill="x")
            s = tk.Label(txt, text="", font=self.f_mono_peq, anchor="w")
            s.pack(fill="x")
            prog = tk.Canvas(txt, width=1, height=4, highlightthickness=0)
            prog.pack(fill="x", pady=(5, 0))
            self.cards.append(dict(frame=c, ico=ico, txt=txt, titulo=t, sub=s, prog=prog))
            prog.bind("<Configure>", lambda e, k=i: self.pintar_card(k))

        # ── barra de estado (se empaca antes para que nunca se recorte) ──
        est = self.pinta(tk.Frame(r, padx=16, pady=8), bg="fondo")
        est.pack(side="bottom", fill="x")
        self.c_prog = self.pinta(tk.Canvas(est, width=250, height=8, highlightthickness=0), bg="fondo")
        self.c_prog.pack(side="left")
        self.l_estado = self.pinta(tk.Label(est, text="Listo", font=self.f_ui), bg="fondo", fg="tenue")
        self.l_estado.pack(side="left", padx=14)
        self.l_err_total = self.pinta(tk.Label(est, text="Errores: 0", font=self.f_ui_b), bg="fondo", fg="err")
        self.l_err_total.pack(side="right")
        self.l_cuentas = self.pinta(tk.Label(est, text="", font=self.f_ui), bg="fondo", fg="texto")
        self.l_cuentas.pack(side="right")

        # ── zona principal ──
        cuerpo = self.pinta(tk.PanedWindow(r, orient="horizontal", sashwidth=10, bd=0), bg="fondo")
        cuerpo.pack(fill="both", expand=True, padx=14)
        cuerpo.add(self.construir_editor(cuerpo), minsize=420, stretch="always")
        cuerpo.add(self.construir_derecha(cuerpo), minsize=520, stretch="always")
        self.root.after(50, lambda: cuerpo.sash_place(0, int(self.root.winfo_width() * 0.48), 0))


    def construir_editor(self, padre):
        f = self.pinta(tk.Frame(padre, highlightthickness=1), bg="editor", highlightbackground="borde")
        cab = self.pinta(tk.Frame(f, padx=12, pady=8), bg="panel")
        cab.pack(fill="x")
        self.pinta(tk.Label(cab, text="Código fuente", font=self.f_ui_b), bg="panel", fg="texto").pack(side="left")
        self.l_archivo = self.pinta(tk.Label(cab, text=self.archivo, font=self.f_ui), bg="panel", fg="tenue")
        self.l_archivo.pack(side="left", padx=10)
        self.l_cursor = self.pinta(tk.Label(cab, text="Lín 1, Col 1", font=self.f_ui), bg="panel", fg="tenue")
        self.l_cursor.pack(side="right")
        self.pinta(tk.Label(cab, text="L  S  M", font=self.f_mono_peq), bg="panel", fg="tenue").pack(side="right", padx=20)
        self.pinta(tk.Frame(f, height=1), bg="borde").pack(fill="x")

        cuerpo = self.pinta(tk.Frame(f), bg="editor")
        cuerpo.pack(fill="both", expand=True)
        self.gutter = self.pinta(tk.Canvas(cuerpo, width=96, highlightthickness=0), bg="editor")
        self.gutter.pack(side="left", fill="y")
        sb = ttk.Scrollbar(cuerpo, orient="vertical")
        sb.pack(side="right", fill="y")
        self.texto = self.pinta(tk.Text(cuerpo, font=self.f_mono, wrap="none", undo=True, bd=0,
                                        highlightthickness=0, padx=8, pady=6, spacing1=3, spacing3=3,
                                        tabs=("4c",)),
                                bg="editor", fg="ident", insertbackground="texto", selectbackground="sel")
        self.texto.pack(side="left", fill="both", expand=True)

        def yscroll(*a):
            sb.set(*a)
            self.redibujar_gutter()
        self.texto.configure(yscrollcommand=yscroll)
        sb.configure(command=self.texto.yview)
        self.texto.bind("<KeyRelease>", self.al_editar)
        self.texto.bind("<ButtonRelease-1>", lambda e: self.actualizar_cursor())
        self.texto.bind("<Configure>", lambda e: self.redibujar_gutter())
        self.texto.bind("<<Paste>>", lambda e: self.root.after(10, self.al_editar))
        self._resaltado_id = None
        return f

    def construir_derecha(self, padre):
        f = self.pinta(tk.Frame(padre), bg="fondo")
        # ── panel de proceso ──
        pr = self.pinta(tk.Frame(f, padx=16, pady=12, highlightthickness=1), bg="panel", highlightbackground="borde")
        pr.pack(fill="x", pady=(0, 10))
        self.l_titulo_proc = self.pinta(tk.Label(pr, text="Proceso del análisis", font=self.f_ui_b),
                                        bg="panel", fg="texto")
        self.l_titulo_proc.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        for col, txt in enumerate(("Verificación actual", "Esperado → Encontrado", "Posición")):
            self.pinta(tk.Label(pr, text=txt, font=self.f_ui), bg="panel", fg="tenue").grid(row=1, column=col, sticky="w")
        self.l_verif = self.pinta(tk.Label(pr, text="—", font=self.f_mono_b, padx=10, pady=4,
                                           highlightthickness=1),
                                  bg="panel2", fg="texto", highlightbackground="borde")
        self.l_verif.grid(row=2, column=0, sticky="w", pady=(2, 8))
        self.l_esp = self.pinta(tk.Label(pr, text="—", font=self.f_mono_b), bg="panel", fg="texto")
        self.l_esp.grid(row=2, column=1, sticky="w", padx=(0, 10))
        self.l_pos = self.pinta(tk.Label(pr, text="—", font=self.f_ui_b), bg="panel", fg="texto")
        self.l_pos.grid(row=2, column=2, sticky="w")
        for c, w in ((0, 3), (1, 3), (2, 2)):
            pr.columnconfigure(c, weight=w)
        fila = self.pinta(tk.Frame(pr), bg="panel")
        fila.grid(row=3, column=0, columnspan=3, sticky="w")
        self.l_pila_t = self.pinta(tk.Label(fila, text="Pila de reglas:", font=self.f_ui), bg="panel", fg="tenue")
        self.l_pila_t.pack(side="left")
        self.f_chips = self.pinta(tk.Frame(fila), bg="panel")
        self.f_chips.pack(side="left", padx=6)
        self.caja_msg = tk.Label(pr, text="", font=self.f_ui, justify="left", anchor="w", padx=12, pady=8,
                                 highlightthickness=1, wraplength=640)
        self.caja_msg.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.caja_msg.bind("<Configure>", lambda e: self.caja_msg.config(wraplength=e.width - 30))

        # ── pestañas ──
        tabs_f = self.pinta(tk.Frame(f, highlightthickness=1), bg="panel", highlightbackground="borde")
        tabs_f.pack(fill="both", expand=True)
        pie = self.pinta(tk.Frame(tabs_f, padx=14, pady=10), bg="panel2")
        pie.pack(side="bottom", fill="x")
        self.pinta(tk.Frame(tabs_f, height=1), bg="borde").pack(side="bottom", fill="x")
        self.pinta(tk.Label(pie, text="💡", font=self.f_ui), bg="panel2", fg="ok").pack(side="left", anchor="n")
        self.l_ayuda = self.pinta(tk.Label(pie, text="", font=self.f_ui, justify="left", anchor="w",
                                           wraplength=640), bg="panel2", fg="texto")
        self.l_ayuda.pack(side="left", fill="x", expand=True, padx=8)
        pie.bind("<Configure>", lambda e: self.l_ayuda.config(wraplength=e.width - 60))
        self.nb = ttk.Notebook(tabs_f, style="C.TNotebook")
        self.nb.pack(fill="both", expand=True)

        def tabla(columnas, anchos, ancla=None):
            fr = tk.Frame(self.nb)
            self.pinta(fr, bg="panel")
            tv = ttk.Treeview(fr, columns=columnas, show="headings", style="C.Treeview")
            for c, w in zip(columnas, anchos):
                tv.heading(c, text=c, anchor="w")
                tv.column(c, width=w, stretch=(w > 150), anchor="w")
            s = ttk.Scrollbar(fr, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=s.set)
            s.pack(side="right", fill="y")
            tv.pack(fill="both", expand=True)
            return fr, tv

        # árbol
        fa = self.pinta(tk.Frame(self.nb), bg="panel")
        self.arbol = ttk.Treeview(fa, columns=("pos",), style="C.Treeview")
        self.arbol.heading("#0", text="Nodo", anchor="w")
        self.arbol.heading("pos", text="Lín:Col", anchor="w")
        self.arbol.column("#0", width=420, stretch=True)
        self.arbol.column("pos", width=90, stretch=False)
        sa = ttk.Scrollbar(fa, orient="vertical", command=self.arbol.yview)
        self.arbol.configure(yscrollcommand=sa.set)
        sa.pack(side="right", fill="y")
        self.arbol.pack(fill="both", expand=True)
        self.arbol.bind("<<TreeviewSelect>>", self.al_elegir_nodo)
        self.nb.add(fa, text="Árbol sintáctico")

        ft, self.t_tokens = tabla(("#", "Tipo", "Lexema", "Lín", "Col"), (50, 130, 260, 60, 60))
        self.t_tokens.bind("<<TreeviewSelect>>", self.al_elegir_token)
        self.nb.add(ft, text="Tokens")

        fs, self.t_simbolos = tabla(("Nombre", "Categoría", "Tipo", "Ámbito", "Lín"), (120, 120, 190, 170, 50))
        self.nb.add(fs, text="Símbolos")

        fe, self.t_errores = tabla(("#", "Fase", "Mensaje", "Lín", "Col"), (40, 100, 420, 55, 55))
        self.t_errores.bind("<<TreeviewSelect>>", self.al_elegir_error)
        self.nb.add(fe, text="Errores")

        # Código intermedio: panel de solo lectura donde se muestra el C3D generado.
        fi = self.pinta(tk.Frame(self.nb), bg="panel")
        self.t_intermedio = self.pinta(
            tk.Text(fi, font=self.f_mono, bd=0, highlightthickness=0, padx=12,
                    pady=10, wrap="none", state="disabled"),
            bg="editor", fg="texto", selectbackground="sel")
        si_v = ttk.Scrollbar(fi, orient="vertical", command=self.t_intermedio.yview)
        si_h = ttk.Scrollbar(fi, orient="horizontal", command=self.t_intermedio.xview)
        self.t_intermedio.configure(yscrollcommand=si_v.set, xscrollcommand=si_h.set)
        si_v.pack(side="right", fill="y")
        si_h.pack(side="bottom", fill="x")
        self.t_intermedio.pack(fill="both", expand=True)
        self.nb.add(fi, text="Intermedio")

        fc = self.pinta(tk.Frame(self.nb), bg="panel")
        self.pinta(tk.Label(fc, text="La ejecución / traducción a ensamblador se integrará en una fase posterior.",
                            font=self.f_ui), bg="panel", fg="tenue").pack(pady=40)
        self.nb.add(fc, text="Consola", state="disabled")

        fb = self.pinta(tk.Frame(self.nb), bg="panel")
        self.bitacora = self.pinta(tk.Text(fb, font=self.f_mono_peq, bd=0, highlightthickness=0, padx=10,
                                           pady=8, wrap="none", state="disabled"),
                                   bg="panel", fg="texto", selectbackground="sel")
        sbb = ttk.Scrollbar(fb, orient="vertical", command=self.bitacora.yview)
        self.bitacora.configure(yscrollcommand=sbb.set)
        sbb.pack(side="right", fill="y")
        self.bitacora.pack(fill="both", expand=True)
        self.nb.add(fb, text="Bitácora")

        return f

    def atajos(self):
        r = self.root
        r.bind("<F5>", lambda e: self.compilar())
        r.bind("<F6>", lambda e: self.pausar())
        r.bind("<F10>", lambda e: (self.paso(), "break")[1])
        r.bind("<Escape>", lambda e: self.detener())
        r.bind("<Control-o>", lambda e: self.abrir())

    # ═══════════════════════════ tema ═══════════════════════════
    def cambiar_tema(self, nombre):
        self.tema = nombre
        self.T = TEMAS[nombre]
        self.aplicar_tema()

    def aplicar_tema(self):
        T = self.T
        for w, roles in self.temables:
            try:
                w.configure(**{k: T[v] for k, v in roles.items()})
            except tk.TclError:
                pass
        for b in self.botones:
            b.pintar()
        sel, nosel = (self.b_oscuro, self.b_claro) if self.tema == "oscuro" else (self.b_claro, self.b_oscuro)
        sel.configure(bg=T["panel"], fg=T["texto"], font=self.f_ui_b)
        nosel.configure(bg=T["panel2"], fg=T["tenue"], font=self.f_ui)

        st = ttk.Style()
        st.theme_use("clam")
        st.configure("C.TNotebook", background=T["panel"], borderwidth=0, tabmargins=(6, 6, 6, 0))
        st.configure("C.TNotebook.Tab", background=T["panel2"], foreground=T["tenue"], padding=(11, 6),
                     font=self.f_ui, borderwidth=1, bordercolor=T["borde"], lightcolor=T["panel2"],
                     darkcolor=T["panel2"])
        st.map("C.TNotebook.Tab",
               background=[("selected", T["panel"]), ("disabled", T["panel2"])],
               foreground=[("selected", T["texto"]), ("disabled", T["muy_tenue"])],
               lightcolor=[("selected", T["acento"])])
        st.configure("C.Treeview", background=T["panel"], fieldbackground=T["panel"], foreground=T["texto"],
                     rowheight=26, font=self.f_mono_peq, borderwidth=0, bordercolor=T["borde"])
        st.map("C.Treeview", background=[("selected", T["sel"])], foreground=[("selected", T["texto"])])
        st.configure("C.Treeview.Heading", background=T["panel2"], foreground=T["texto"], font=self.f_ui_b,
                     borderwidth=0, relief="flat", padding=(6, 5))
        st.map("C.Treeview.Heading", background=[("active", T["boton_hover"])])
        st.configure("C.Horizontal.TScale", background=T["acento"], troughcolor=T["borde"],
                     bordercolor=T["fondo"], lightcolor=T["acento"], darkcolor=T["acento"], gripcount=0)
        st.configure("Vertical.TScrollbar", background=T["panel2"], troughcolor=T["panel"],
                     bordercolor=T["panel"], arrowcolor=T["tenue"], lightcolor=T["panel2"], darkcolor=T["panel2"])
        for tv in (self.t_errores,):
            tv.tag_configure("Léxico", foreground=T["tipo"])
            tv.tag_configure("Sintáctico", foreground=T["kw"])
            tv.tag_configure("Semántico", foreground="#b48cff")
        self.arbol.tag_configure("raiz", font=self.f_ui_b)

        tx = self.texto
        for tag, rol in (("kw", "kw"), ("tipo", "tipo"), ("cadena", "cadena"), ("numero", "numero"),
                         ("comentario", "comentario")):
            tx.tag_configure(tag, foreground=T[rol])
        tx.tag_configure("kw", font=self.f_mono_b)
        tx.tag_configure("err_linea", background=T["err_linea"])
        try:
            tx.tag_configure("err_sub", underline=True, underlinefg=T["err"])
        except tk.TclError:
            tx.tag_configure("err_sub", underline=True, foreground=T["err"])
        tx.tag_configure("actual", background=T["actual_bg"], foreground=T["actual_fg"])
        tx.tag_configure("sel_nodo", background=T["sel"])
        tx.tag_raise("err_linea"); tx.tag_raise("sel_nodo"); tx.tag_raise("err_sub"); tx.tag_raise("actual")
        tx.tag_raise("sel")
        self.menu = tk.Menu(self.root, tearoff=0, bg=T["panel"], fg=T["texto"], activebackground=T["sel"],
                            activeforeground=T["texto"], bd=0, font=self.f_ui)
        for i in range(5):
            self.pintar_card(i)
        self.redibujar_gutter()
        self.pintar_progreso()
        self.mensaje(getattr(self, "_ultimo_msg", ("", "neutro"))[0], getattr(self, "_ultimo_msg", ("", "neutro"))[1])

    # ═══════════════════════════ tarjetas de fase ═══════════════════════════
    def pintar_card(self, i):
        T, c = self.T, self.cards[i]
        estado = self.estado_fases[i]
        activa = estado == "curso" or (i == self.fase_actual and estado == "error" and self.gen)
        fondo = T["acento_bg"] if activa else T["panel"]
        for w in (c["frame"], c["txt"], c["ico"], c["prog"]):
            w.configure(bg=fondo)
        bloqueada = estado in ("bloqueada", "pendiente", "externa")
        c["titulo"].configure(bg=fondo, fg=T["muy_tenue"] if bloqueada and not activa else T["texto"])
        c["sub"].configure(bg=fondo, fg=T["tenue"], text=self.sub_fases[i],
                           font=self.f_peq if bloqueada else self.f_mono_peq)
        ic = c["ico"]
        ic.delete("all")
        color = {"ok": T["ok"], "error": T["err"], "curso": T["acento"]}.get(estado, T["muy_tenue"])
        ic.create_oval(3, 3, 37, 37, outline=color, width=2,
                       fill=T["err_bg"] if estado == "error" else "")
        if estado == "ok":
            ic.create_line(12, 20, 18, 26, 28, 14, fill=color, width=2.5, capstyle="round", joinstyle="round")
        elif estado == "error":
            ic.create_line(14, 14, 26, 26, fill=color, width=2.5, capstyle="round")
            ic.create_line(26, 14, 14, 26, fill=color, width=2.5, capstyle="round")
        elif estado == "curso":
            ic.create_arc(10, 10, 30, 30, start=90, extent=-360 * max(self.progreso_fases[i], 0.03),
                          outline=color, width=3, style="arc")
        else:  # candado
            ic.create_rectangle(14, 19, 26, 28, outline=color, width=1.6)
            ic.create_arc(15.5, 12, 24.5, 24, start=0, extent=180, outline=color, width=1.6, style="arc")
        pg = c["prog"]
        pg.delete("all")
        if estado in ("curso", "error") and i == self.fase_actual:
            w = max(pg.winfo_width(), 10)
            pg.create_rectangle(0, 0, w * 0.55, 4, fill=T["borde"], width=0)
            pg.create_rectangle(0, 0, w * 0.55 * self.progreso_fases[i], 4,
                                fill=T["err"] if estado == "error" else T["acento"], width=0)
        # barra inferior de la tarjeta activa
        c["frame"].configure(highlightthickness=0)
        if activa:
            c["frame"].configure(highlightthickness=2, highlightbackground=T["acento"], highlightcolor=T["acento"])

    def set_fase(self, i, estado, sub=None):
        self.estado_fases[i] = estado
        if sub is not None:
            self.sub_fases[i] = sub
        self.pintar_card(i)

    # ═══════════════════════════ editor ═══════════════════════════
    def redibujar_gutter(self):
        g, tx, T = self.gutter, self.texto, self.T
        g.delete("all")
        idx = tx.index("@0,0")
        while True:
            info = tx.dlineinfo(idx)
            if info is None:
                break
            y = info[1] + info[3] / 2
            linea = int(idx.split(".")[0])
            g.create_text(30, y, text=str(linea), anchor="e", fill=T["muy_tenue"], font=self.f_mono_peq)
            est = self.estado_lineas.get(linea, [None, None, None])
            for k in range(3):
                x = 46 + k * 14
                e = est[k]
                if e == "ok":
                    g.create_rectangle(x, y - 4, x + 8, y + 4, fill=T["ok"], width=0)
                elif e == "err":
                    g.create_rectangle(x, y - 4, x + 8, y + 4, fill=T["err"], width=0)
                elif e == "curso":
                    g.create_rectangle(x, y - 4, x + 8, y + 4, fill=T["acento"], width=0)
                elif self.res is not None:
                    g.create_oval(x + 1, y - 3, x + 7, y + 3, outline=T["muy_tenue"], width=1)
            siguiente = tx.index(f"{idx} +1line")
            if siguiente == idx:
                break
            idx = siguiente
        g.create_line(95, 0, 95, g.winfo_height(), fill=T["borde"])

    def al_editar(self, evento=None):
        self.actualizar_cursor()
        if evento is not None and evento.keysym in ("Up", "Down", "Left", "Right", "Home", "End",
                                                     "Prior", "Next", "Shift_L", "Shift_R",
                                                     "Control_L", "Control_R", "F5", "F6", "F10", "Escape"):
            return
        if self.gen is None and self.texto.edit_modified():
            # el código cambió: las marcas anteriores ya no aplican
            for t in ("err_linea", "err_sub", "actual", "sel_nodo"):
                self.texto.tag_remove(t, "1.0", "end")
            self.estado_lineas.clear()
            self.texto.edit_modified(False)
        if self._resaltado_id:
            self.root.after_cancel(self._resaltado_id)
        self._resaltado_id = self.root.after(250, self.resaltar_sintaxis)
        self.redibujar_gutter()

    def actualizar_cursor(self):
        l, c = self.texto.index("insert").split(".")
        self.l_cursor.config(text=f"Lín {l}, Col {int(c) + 1}")

    def resaltar_sintaxis(self):
        tx = self.texto
        codigo = tx.get("1.0", "end-1c")
        for t in ("kw", "tipo", "cadena", "numero", "comentario"):
            tx.tag_remove(t, "1.0", "end")
        toks, _ = lexico.analizar(codigo)
        for t in toks:
            if t.tipo == "EOF":
                continue
            tag = None
            if t.tipo == "RESERVADA":
                tag = "tipo" if t.lexema in lexico.TIPOS_PREDEFINIDOS or t.lexema == "void" else "kw"
            elif t.tipo in ("CADENA", "CARACTER"):
                tag = "cadena"
            elif t.tipo in ("ENTERO", "REAL"):
                tag = "numero"
            elif t.tipo == "CABECERA":
                tag = "cadena"
            elif t.tipo == "DIRECTIVA":
                tag = "kw"
            elif t.tipo == "IDENTIFICADOR" and t.lexema in BIBLIOTECA:
                tag = "tipo"
            if tag:
                tx.tag_add(tag, f"1.0+{t.inicio}c", f"1.0+{t.fin}c")
        # comentarios (el léxico los descarta)
        i = 0
        while True:
            pos = tx.search(r"//|/\*", f"1.0+{i}c", stopindex="end", regexp=True)
            if not pos:
                break
            if "cadena" in tx.tag_names(pos):
                i = len(tx.get("1.0", pos)) + 1
                continue
            if tx.get(pos, f"{pos}+2c") == "//":
                fin = f"{pos} lineend"
            else:
                fin = tx.search(r"\*/", pos, stopindex="end", regexp=True)
                fin = f"{fin}+2c" if fin else "end"
            tx.tag_add("comentario", pos, fin)
            i = len(tx.get("1.0", fin))

    def poner_codigo(self, codigo, nombre):
        self.texto.delete("1.0", "end")
        self.texto.insert("1.0", codigo)
        self.texto.edit_reset()
        self.texto.edit_modified(False)
        self.archivo = nombre
        self.l_archivo.config(text=nombre)
        self.resaltar_sintaxis()
        self.reiniciar_resultados()

    def indice(self, linea, col):
        return f"{linea}.{max(col - 1, 0)}"

    def indice_visible(self, linea, col):
        ini = self.indice(linea, col)
        if self.texto.get(ini) in ("\n", "") and col > 1:
            ini = self.texto.index(f"{ini}-1c")
        return ini

    def marcar_actual(self, linea, col, largo):
        tx = self.texto
        tx.tag_remove("actual", "1.0", "end")
        ini = self.indice_visible(linea, col)
        tx.tag_add("actual", ini, f"{ini}+{max(largo, 1)}c")
        tx.see(ini)
        self.redibujar_gutter()

    def subrayar_error(self, linea, col):
        tx = self.texto
        ini = self.indice(linea, col)
        if tx.get(ini) in ("\n", "") and col > 1:
            ini = f"{ini}-1c"
        car = tx.get(ini)
        fin = f"{ini} wordend" if (car.isalnum() or car == "_") else f"{ini}+1c"
        tx.tag_add("err_sub", ini, fin)
        tx.tag_add("err_linea", f"{linea}.0", f"{linea}.0 lineend+1c")

    # ═══════════════════════════ panel de proceso ═══════════════════════════
    def mensaje(self, texto, tipo="neutro"):
        self._ultimo_msg = (texto, tipo)
        T = self.T
        if not texto:
            self.caja_msg.configure(text="", bg=T["panel"], highlightbackground=T["panel"])
            return
        colores = {"error": (T["err_bg"], T["err_borde"]), "info": (T["info_bg"], T["info_borde"]),
                   "ok": (T["panel2"], T["ok"]), "neutro": (T["panel2"], T["borde"])}[tipo]
        self.caja_msg.configure(text=texto, bg=colores[0], fg=T["texto"], highlightbackground=colores[1],
                                highlightcolor=colores[1])

    def chips(self, items):
        for w in self.f_chips.winfo_children():
            w.destroy()
        T = self.T
        if len(items) > 3:
            items = ["…"] + items[-3:]
        for k, it in enumerate(items):
            if k:
                tk.Label(self.f_chips, text="›", bg=T["panel"], fg=T["tenue"], font=self.f_ui).pack(side="left", padx=2)
            ultimo = k == len(items) - 1
            tk.Label(self.f_chips, text=it, padx=8, pady=1, font=self.f_ui_b if ultimo else self.f_ui,
                     bg=T["acento_bg"] if ultimo else T["chip"], fg=T["texto"],
                     highlightthickness=1, highlightbackground=T["acento"] if ultimo else T["borde"]
                     ).pack(side="left")

    def proceso(self, verif, esperado, encontrado, linea, col, pila):
        self.l_verif.config(text=verif)
        self.l_esp.config(text=f"{esperado}  →  {encontrado}")
        self.l_pos.config(text=f"Línea {linea}, columna {col}" if linea else "—")
        self.chips(pila)

    def ayuda(self, texto):
        self.l_ayuda.config(text=texto)

    def log(self, texto):
        b = self.bitacora
        b.configure(state="normal")
        b.insert("end", f"{time.strftime('%H:%M:%S')}  {texto}\n")
        b.see("end")
        b.configure(state="disabled")

    def pintar_progreso(self):
        c, T = self.c_prog, self.T
        c.delete("all")
        c.create_rectangle(0, 0, 250, 8, fill=T["borde"], width=0)
        if self.fase_actual >= 0:
            frac = (self.fase_actual + (self.paso_actual / self.total_pasos if self.total_pasos else 1)) / 5
            if self.gen is None and self.fase_actual >= 0:
                frac = min(1.0, (sum(1 for e in self.estado_fases if e in ("ok", "error"))) / 5)
            color = T["err"] if "error" in self.estado_fases else T["acento"]
            c.create_rectangle(0, 0, 250 * frac, 8, fill=color, width=0)

    def actualizar_estado(self):
        if self.fase_actual >= 0 and self.gen is not None:
            self.l_estado.config(text=f"Fase {self.fase_actual + 1} de 5 · {FASES[self.fase_actual]} · "
                                      f"paso {self.paso_actual} de {self.total_pasos}"
                                      + ("  (en pausa)" if self.pausado else ""))
        if self.res:
            sim = self.res.get("simbolos")
            self.l_cuentas.config(text=f"Tokens: {len(self.t_tokens.get_children())}   ·   "
                                       f"Nodos: {len(self.nodos_insertados)}   ·   "
                                       f"Símbolos: {len(self.t_simbolos.get_children()) if sim is not None else '–'}   ·   ")
        self.l_err_total.config(text=f"Errores: {len(self.errores)}")
        self.titulos_pestanas()
        self.pintar_progreso()

    def titulos_pestanas(self):
        self.nb.tab(0, text=f"Árbol sintáctico  {len(self.nodos_insertados)}")
        self.nb.tab(1, text=f"Tokens  {len(self.t_tokens.get_children())}")
        sim = self.res.get("simbolos") if self.res else None
        self.nb.tab(2, text=f"Símbolos  {len(self.t_simbolos.get_children())}" if sim is not None else "Símbolos")
        self.nb.tab(3, text=f"Errores  {len(self.errores)}")

    # ═══════════════════════════ resultados ═══════════════════════════
    def reiniciar_resultados(self):
        self.cancelar_tick()
        self.gen = None
        self.res = None
        self.pausado = False
        self.fase_actual = -1
        self.paso_actual = self.total_pasos = 0
        self.errores = []
        self.nodos_insertados = set()
        self.estado_lineas = {}
        for tv in (self.arbol, self.t_tokens, self.t_simbolos, self.t_errores):
            tv.delete(*tv.get_children())
        self.bitacora.configure(state="normal")
        self.bitacora.delete("1.0", "end")
        self.bitacora.configure(state="disabled")
        self.t_intermedio.configure(state="normal")
        self.t_intermedio.delete("1.0", "end")
        self.t_intermedio.insert("1.0", "El código intermedio aparecerá aquí después de una compilación sin errores.\n")
        self.t_intermedio.configure(state="disabled")
        for t in ("err_linea", "err_sub", "actual", "sel_nodo"):
            self.texto.tag_remove(t, "1.0", "end")
        subs = ["listo para analizar", "requiere 0 errores léxicos", "requiere 0 errores sintácticos",
                "requiere 0 errores semánticos", "requiere código intermedio"]
        for i in range(5):
            self.progreso_fases[i] = 0
            self.set_fase(i, "pendiente" if i == 0 else "bloqueada", subs[i])
        self.l_titulo_proc.config(text="Proceso del análisis")
        self.proceso("—", "—", "—", 0, 0, [])
        self.mensaje("Presiona Compilar (F5) para analizar el código, o Paso (F10) para avanzar token por token.",
                     "neutro")
        self.ayuda("Al seleccionar un error se marca en el código y aquí aparece cómo corregirlo.")
        self.l_estado.config(text="Listo")
        self.b_pausar.config(text="❙❙  Pausar (F6)")
        self.actualizar_botones()
        self.actualizar_estado()
        self.redibujar_gutter()

    def actualizar_botones(self):
        corriendo = self.gen is not None
        self.b_pausar.habilitar(corriendo)
        self.b_terminar.habilitar(corriendo)
        self.b_detener.habilitar(corriendo)
        self.b_compilar.habilitar(True)
        self.b_exportar.habilitar(self.res is not None)

    def agregar_error(self, err):
        self.errores.append(err)
        n = len(self.errores)
        self.t_errores.insert("", "end", iid=str(n - 1), tags=(err["fase"],),
                              values=(n, err["fase"], err["mensaje"], err["linea"], err["columna"]))
        self.subrayar_error(err["linea"], err["columna"])
        k = FASES.index(err["fase"]) if err["fase"] in FASES else 2
        est = self.estado_lineas.setdefault(err["linea"], [None, None, None])
        if k < 3:
            est[k] = "err"
        self.log(f"[{err['fase']}] ERROR {err['linea']}:{err['columna']} — {err['mensaje']}")

    def marcar_lineas(self, fase, hasta, final=False):
        """Marca como revisadas las líneas con código hasta 'hasta'."""
        ult = int(self.texto.index("end-1c").split(".")[0])
        for l in range(1, min(hasta, ult) + 1):
            est = self.estado_lineas.setdefault(l, [None, None, None])
            if est[fase] not in ("err",):
                est[fase] = "ok" if (l < hasta or final) else "curso"

    # ═══════════════════════════ ejecución ═══════════════════════════
    def preparar(self):
        codigo = self.texto.get("1.0", "end-1c")
        self.reiniciar_resultados()
        tokens, errores_lex = lexico.analizar(codigo)
        self.res = {"codigo": codigo, "tokens": tokens, "lex_errores": errores_lex,
                    "sint": None, "sem": None, "simbolos": None}
        if not errores_lex:
            self.res["sint"] = sintactico.analizar(tokens)
        self.gen = self.ejecucion()
        self.log(f"Compilación iniciada: {self.archivo} ({codigo.count(chr(10)) + 1} líneas)")
        self.actualizar_botones()

    def compilar(self):
        self.preparar()
        self.pausado = False
        self.programar(0)

    def pausar(self):
        if self.gen is None:
            return
        self.pausado = not self.pausado
        self.b_pausar.config(text="▷  Continuar (F6)" if self.pausado else "❙❙  Pausar (F6)")
        self.actualizar_estado()
        if not self.pausado:
            self.programar(0)
        else:
            self.cancelar_tick()

    def paso(self):
        if self.gen is None:
            self.preparar()
        self.pausado = True
        self.cancelar_tick()
        self.b_pausar.config(text="▷  Continuar (F6)")
        while True:
            m = self.avanzar()
            if m != "fase":
                break
        self.actualizar_estado()

    def terminar(self):
        if self.gen is None:
            return
        self.cancelar_tick()
        while self.avanzar() is not None:
            pass

    def detener(self):
        if self.gen is None:
            return
        self.cancelar_tick()
        self.gen = None
        f = self.fase_actual
        if f >= 0 and self.estado_fases[f] == "curso":
            self.set_fase(f, "bloqueada", f"detenido en paso {self.paso_actual} de {self.total_pasos}")
        self.log("Compilación detenida por el usuario")
        self.l_estado.config(text="Detenido")
        self.mensaje("Compilación detenida. Presiona Compilar (F5) para empezar de nuevo.", "neutro")
        self.texto.tag_remove("actual", "1.0", "end")
        self.b_pausar.config(text="❙❙  Pausar (F6)")
        self.actualizar_botones()
        self.actualizar_estado()

    def cancelar_tick(self):
        if self.tick_id:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None

    def programar(self, ms):
        self.cancelar_tick()
        self.tick_id = self.root.after(ms, self.tick)

    def avanzar(self):
        """Ejecuta un paso del generador. Devuelve 'paso', 'fase' o None al terminar."""
        if self.gen is None:
            return None
        try:
            return next(self.gen)
        except StopIteration:
            self.finalizar()
            return None

    def tick(self):
        self.tick_id = None
        if self.gen is None or self.pausado:
            return
        retraso = self.retraso.get()
        if self.modo.get() == "fase":
            while True:
                m = self.avanzar()
                if m in ("fase", None):
                    break
        elif retraso == 0:
            fin = time.perf_counter() + 0.03
            while time.perf_counter() < fin:
                if self.avanzar() is None:
                    break
        else:
            self.avanzar()
        self.actualizar_estado()
        if self.gen is not None and not self.pausado:
            self.programar(max(retraso, 1) if self.modo.get() == "paso" else max(retraso, 300))

    def iniciar_fase(self, i, total, titulo):
        self.fase_actual = i
        self.paso_actual = 0
        self.total_pasos = total
        self.progreso_fases[i] = 0
        self.set_fase(i, "curso", f"paso 0 de {total}")
        self.l_titulo_proc.config(text=titulo)
        self.log(f"── Fase {i + 1}: {FASES[i]} ({total} pasos) ──")
        for k in range(5):
            self.pintar_card(k)

    def avanzar_contador(self, i, errores):
        self.paso_actual += 1
        self.progreso_fases[i] = self.paso_actual / max(self.total_pasos, 1)
        txt = f"paso {self.paso_actual} de {self.total_pasos}"
        if errores:
            txt += f" · {errores} error{'es' if errores != 1 else ''}"
        self.set_fase(i, "error" if errores else "curso", txt)

    def ejecucion(self):
        r = self.res
        tokens = r["tokens"]

        # ─────────── Fase 1: léxico ───────────
        eventos = [("tok", t) for t in tokens if t.tipo != "EOF"] + [("err", e) for e in r["lex_errores"]]
        eventos.sort(key=lambda ev: (ev[1].linea, ev[1].columna) if ev[0] == "tok"
                     else (ev[1]["linea"], ev[1]["columna"]))
        self.iniciar_fase(0, len(eventos), "Proceso del análisis léxico")
        n_err = 0
        for tipo, x in eventos:
            if tipo == "tok":
                n = len(self.t_tokens.get_children()) + 1
                self.t_tokens.insert("", "end", iid=f"t{n}", values=(n, getattr(x, "categoria", "") or x.tipo, x.lexema,
                                                                    x.linea, x.columna))
                self.t_tokens.see(f"t{n}")
                self.marcar_actual(x.linea, x.columna, len(x.lexema))
                cat = getattr(x, "categoria", "") or x.tipo
                self.proceso("Reconocer token", "patrón", f"{cat} '{x.lexema}'", x.linea, x.columna,
                             ["Léxico", cat])
                self.mensaje(f"Se reconoce el lexema '{x.lexema}' como {cat.lower()}.", "info")
                self.marcar_lineas(0, x.linea)
                self.log(f"[Léxico] {x.linea}:{x.columna}  {cat:<18} '{x.lexema}'")
            else:
                n_err += 1
                self.agregar_error(x)
                self.marcar_actual(x["linea"], x["columna"], 1)
                self.proceso("Error léxico", "lexema válido", "carácter inválido", x["linea"], x["columna"],
                             ["Léxico", "Error"])
                self.mensaje(f"Error: {x['mensaje']}.", "error")
                self.ayuda(f"Cómo corregirlo: {x['sugerencia']}")
            self.avanzar_contador(0, n_err)
            yield "paso"
        self.marcar_lineas(0, 10 ** 6, final=True)
        ntok = len(tokens) - 1
        self.set_fase(0, "error" if n_err else "ok",
                      f"{ntok} tokens · {n_err} error{'es' if n_err != 1 else ''}")
        self.redibujar_gutter()
        yield "fase"
        if n_err:
            self.set_fase(1, "bloqueada", "requiere 0 errores léxicos")
            return

        # ─────────── Fase 2: sintáctico ───────────
        s = r["sint"]
        orden = self.orden_nodos(s.arbol)
        ptr = 0
        self.iniciar_fase(1, len(s.pasos), "Proceso del análisis sintáctico")
        n_err = 0
        for p in s.pasos:
            tok = p["token"]
            while ptr < len(orden) and orden[ptr][0].tok_ini <= p["indice"]:
                self.insertar_nodo(*orden[ptr])
                ptr += 1
            if p["tipo"] == "match":
                self.marcar_actual(tok.linea, tok.columna, len(tok.lexema))
                self.proceso(p["regla"], p["esperado"], f"'{p['encontrado']}'", tok.linea, tok.columna, p["pila"])
                self.mensaje(f"Coincide: en «{p['regla']}» se esperaba {p['esperado']} "
                             f"y se encontró '{p['encontrado']}'.", "info")
                self.marcar_lineas(1, tok.linea)
                self.log(f"[Sintáctico] {tok.linea}:{tok.columna}  {p['regla']:<26} ✓ {p['encontrado']}")
            else:
                n_err += 1
                err = s.errores[n_err - 1]
                self.agregar_error(err)
                self.marcar_actual(err["linea"], err["columna"], 1)
                self.proceso(p["regla"], p["esperado"], p["encontrado"], err["linea"], err["columna"], p["pila"])
                self.mensaje(f"Error: {p['mensaje']}.", "error")
                self.ayuda(f"Cómo corregirlo: {p['sugerencia'] or 'revisa la estructura de la instrucción.'}")
                self.t_errores.selection_set(str(len(self.errores) - 1))
            self.avanzar_contador(1, n_err)
            yield "paso"
        for x in orden[ptr:]:
            self.insertar_nodo(*x)
        self.marcar_lineas(1, 10 ** 6, final=True)
        self.set_fase(1, "error" if n_err else "ok",
                      f"{len(s.nodos)} nodos · {n_err} error{'es' if n_err != 1 else ''}")
        self.redibujar_gutter()
        yield "fase"
        if n_err:
            self.set_fase(2, "bloqueada", "requiere 0 errores sintácticos")
            return

        # ─────────── Fase 3: semántico (módulo externo) ───────────
        sem = self.cargar_modulo("semantico")
        if sem is None or not hasattr(sem, "analizar"):
            self.set_fase(2, "externa", "módulo por integrar (semantico.py)")
            self.set_fase(3, "bloqueada", "requiere análisis semántico")
            self.log("Semántico: no se encontró semantico.py — se detiene aquí")
            return
        try:
            rs = sem.analizar(s.arbol, tokens) or {}
        except Exception as ex:  # el módulo del equipo falló
            self.set_fase(2, "error", "el módulo lanzó una excepción")
            self.mensaje(f"semantico.analizar() lanzó {type(ex).__name__}: {ex}", "error")
            return
        r["sem"] = rs
        r["simbolos"] = rs.get("simbolos", [])
        pasos = rs.get("pasos") or []
        errores = rs.get("errores", [])
        self.iniciar_fase(2, max(len(pasos), 1), "Proceso del análisis semántico")
        self.nb.select(2)
        mostrados = set()

        def mostrar_simbolo(k):
            # la tabla de símbolos se llena conforme el semántico registra cada nombre
            if k in mostrados or not 0 <= k < len(r["simbolos"]):
                return
            mostrados.add(k)
            sm = r["simbolos"][k]
            self.t_simbolos.insert("", "end", iid=f"s{k}", values=tuple(
                sm.get(c, "") for c in ("nombre", "categoria", "tipo", "ambito", "linea")))
            self.t_simbolos.see(f"s{k}")

        if not any("simbolo" in p for p in pasos):      # módulo sin pasos de registro: todo de una vez
            for k in range(len(r["simbolos"])):
                mostrar_simbolo(k)
        pend = list(errores)
        for p in pasos:
            l, c = p.get("linea", 0), p.get("columna", 0)
            if l:
                self.marcar_actual(l, c, p.get("largo", 1))
                self.marcar_lineas(2, l)
            self.proceso(p.get("regla", "Verificación"), p.get("esperado", "—"), p.get("encontrado", "—"),
                         l, c, p.get("pila", ["Semántico"]))
            if "simbolo" in p:
                mostrar_simbolo(p["simbolo"])
            if p.get("error"):
                e = pend.pop(0) if pend else {"fase": "Semántico", "mensaje": p.get("mensaje", ""),
                                              "linea": l, "columna": c, "sugerencia": ""}
                self.agregar_error(e)
                self.mensaje(f"Error: {e['mensaje']}", "error")
                self.ayuda(f"Cómo corregirlo: {e.get('sugerencia', '')}")
            else:
                self.mensaje(p.get("mensaje", ""), "info")
                self.log(f"[Semántico] {l}:{c}  {p.get('regla', ''):<26} ✓ {p.get('encontrado', '')}")
            self.avanzar_contador(2, len([e for e in self.errores if e["fase"] == "Semántico"]))
            yield "paso"
        for k in range(len(r["simbolos"])):
            mostrar_simbolo(k)
        for e in pend:
            self.agregar_error(e)
        n_sem = len([e for e in self.errores if e["fase"] == "Semántico"])
        self.marcar_lineas(2, 10 ** 6, final=True)
        self.set_fase(2, "error" if n_sem else "ok",
                      f"{len(r['simbolos'])} símbolos · {n_sem} error{'es' if n_sem != 1 else ''}")
        yield "fase"
        if n_sem:
            self.set_fase(3, "bloqueada", "requiere 0 errores semánticos")
            self.set_fase(4, "bloqueada", "requiere código intermedio")
            return

        # ─────────── Fase 4: generación de código intermedio ───────────
        ci = self.cargar_modulo("codigo_intermedio")
        if ci is None or not hasattr(ci, "generar"):
            self.set_fase(3, "externa", "no se encontró codigo_intermedio.py")
            self.set_fase(4, "bloqueada", "requiere código intermedio")
            return
        try:
            ri = ci.generar(s.arbol) or {}
        except Exception as ex:
            self.set_fase(3, "error", "falló la generación")
            self.mensaje(f"codigo_intermedio.generar() lanzó {type(ex).__name__}: {ex}", "error")
            return
        r["intermedio"] = ri
        instrucciones = ri.get("codigo", [])
        # Mostrar el resultado completo en su propia pestaña, además de animarlo en la bitácora.
        self.t_intermedio.configure(state="normal")
        self.t_intermedio.delete("1.0", "end")
        texto_intermedio = ri.get("texto") or "\n".join(instrucciones)
        self.t_intermedio.insert("1.0", texto_intermedio if texto_intermedio else "(No se generaron instrucciones.)")
        self.t_intermedio.configure(state="disabled")
        self.nb.tab(4, state="normal")
        self.iniciar_fase(3, max(len(instrucciones), 1), "Generación de código intermedio (tres direcciones)")
        for i, instruccion in enumerate(instrucciones, 1):
            self.proceso("Generar instrucción", "operación de tres direcciones", instruccion.strip(), 0, 0,
                         ["Código intermedio", f"Instrucción {i}"])
            self.log(f"[Código intermedio] {instruccion}")
            self.mensaje(instruccion.strip(), "info")
            self.avanzar_contador(3, 0)
            yield "paso"
        self.set_fase(3, "ok", f"{len(instrucciones)} instrucciones · {ri.get('temporales', 0)} temporales")
        self.set_fase(4, "bloqueada", "pendiente: traducción a ensamblador / ejecución")
        yield "fase"

    def cargar_modulo(self, nombre):
        if not os.path.exists(os.path.join(DIR, nombre + ".py")):
            return None
        mod = importlib.import_module(nombre)
        return importlib.reload(mod)

    def finalizar(self):
        self.gen = None
        self.cancelar_tick()
        self.texto.tag_remove("actual", "1.0", "end")
        n = len(self.errores)
        ult = max((i for i, e in enumerate(self.estado_fases) if e in ("ok", "error")), default=0)
        self.fase_actual = ult
        if n:
            self.l_estado.config(text=f"Terminado con {n} error{'es' if n != 1 else ''} · fase {ult + 1} de 5 · {FASES[ult]}")
            self.nb.select(3)
            self.t_errores.selection_set("0")
            self.t_errores.focus("0")
        else:
            self.l_estado.config(text=f"Terminado sin errores · fases completadas: {ult + 1} de 5")
            self.proceso("Análisis completo", "EOF", "fin de archivo", 0, 0, ["Programa"])
            if self.estado_fases[3] == "ok":
                self.mensaje("✓ Compilación correcta. El código intermedio de tres direcciones ya está generado.", "ok")
                self.nb.select(4)
                self.ayuda("Aquí puedes revisar y copiar las instrucciones intermedias. La siguiente fase será traducirlas a ensamblador.")
            elif self.estado_fases[2] == "ok":
                self.mensaje("✓ El código no tiene errores léxicos, sintácticos ni semánticos. "
                             "Revisa la tabla de símbolos generada.", "ok")
                self.nb.select(2)
                self.ayuda("Sin errores. En Símbolos está cada nombre declarado con su categoría, tipo y ámbito; "
                           "en Árbol sintáctico puedes seleccionar un nodo para ubicarlo en el código.")
            else:
                self.mensaje("✓ El código es sintácticamente correcto. Revisa el árbol sintáctico generado.", "ok")
                self.nb.select(0)
                self.ayuda("Sin errores. Puedes expandir el árbol y seleccionar un nodo para ubicarlo en el código.")
        self.log(f"Compilación terminada: {n} error(es)")
        self.b_pausar.config(text="❙❙  Pausar (F6)")
        self.pausado = False
        for i in range(5):
            self.pintar_card(i)
        self.actualizar_botones()
        self.actualizar_estado()
        self.redibujar_gutter()

    # ═══════════════════════════ árbol ═══════════════════════════
    def orden_nodos(self, raiz):
        lista = []

        def rec(n, padre, prof):
            lista.append((n, padre, prof))
            for h in n.hijos:
                rec(h, n, prof + 1)
        rec(raiz, None, 0)
        lista.sort(key=lambda x: x[0].tok_ini)  # estable: conserva el preorden
        self.padres = {n.id: p for n, p, _ in lista}
        return lista

    def insertar_nodo(self, n, padre, prof):
        if n.id in self.nodos_insertados:
            return
        if padre is not None and padre.id not in self.nodos_insertados:
            self.insertar_nodo(padre, self.padres.get(padre.id), prof - 1)
        iid = f"n{n.id}"
        self.arbol.insert(f"n{padre.id}" if padre else "", "end", iid=iid, text="  " + n.etiqueta(),
                          values=(f"{n.linea}:{n.columna}",), open=prof < 30,
                          tags=("raiz",) if padre is None else ())
        self.nodos_insertados.add(n.id)
        self.arbol.see(iid)

    # ═══════════════════════════ selección ═══════════════════════════
    def al_elegir_error(self, e=None):
        sel = self.t_errores.selection()
        if not sel or self.gen is not None:
            return
        err = self.errores[int(sel[0])]
        tx = self.texto
        tx.tag_remove("actual", "1.0", "end")
        ini = self.indice_visible(err["linea"], err["columna"])
        tx.tag_add("actual", ini, f"{ini}+1c")
        tx.mark_set("insert", ini)
        tx.see(ini)
        self.actualizar_cursor()
        lex = err["fase"] == "Léxico"
        self.proceso(err.get("regla") or ("Error léxico" if lex else err["fase"]),
                     err.get("esperado", "token válido" if lex else "—"),
                     err.get("encontrado", "lexema inválido" if lex else "—"),
                     err["linea"], err["columna"], [err["fase"]] + ([err["regla"]] if err.get("regla") else []))
        self.l_titulo_proc.config(text=f"Proceso del análisis {err['fase'].lower()}")
        self.mensaje(f"Error: {err['mensaje']}.", "error")
        self.ayuda(f"Cómo corregirlo: {err.get('sugerencia') or 'revisa la instrucción marcada.'} "
                   f"Al seleccionar un error se marca en el código.")

    def al_elegir_nodo(self, e=None):
        sel = self.arbol.selection()
        if not sel or self.gen is not None:
            return
        lc = self.arbol.set(sel[0], "pos")
        try:
            l, c = map(int, lc.split(":"))
        except ValueError:
            return
        tx = self.texto
        tx.tag_remove("sel_nodo", "1.0", "end")
        tx.tag_add("sel_nodo", f"{l}.0", f"{l}.0 lineend")
        tx.see(f"{l}.0")

    def al_elegir_token(self, e=None):
        sel = self.t_tokens.selection()
        if not sel or self.gen is not None:
            return
        _, _, lex, l, c = self.t_tokens.item(sel[0], "values")
        self.texto.tag_remove("actual", "1.0", "end")
        ini = self.indice(int(l), int(c))
        self.texto.tag_add("actual", ini, f"{ini}+{len(str(lex))}c")
        self.texto.see(ini)

    # ═══════════════════════════ archivo ═══════════════════════════
    def abrir(self):
        ruta = filedialog.askopenfilename(filetypes=[("Código C++", "*.cpp *.cc *.cxx *.h *.hpp"), ("Todos", "*.*")])
        if ruta:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                self.poner_codigo(f.read(), os.path.basename(ruta))

    def cargar_ejemplo(self, ruta):
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                self.poner_codigo(f.read(), os.path.basename(ruta))

    def menu_ejemplos(self):
        m = self.menu
        m.delete(0, "end")
        carpeta = os.path.join(DIR, "ejemplos")
        for nom in sorted(os.listdir(carpeta)) if os.path.isdir(carpeta) else []:
            if nom.endswith((".cpp", ".h", ".hpp")):
                m.add_command(label=nom, command=lambda r=os.path.join(carpeta, nom): self.cargar_ejemplo(r))
        b = self.b_ejemplos
        m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height() + 2)

    def limpiar(self):
        self.poner_codigo("", "programa.cpp")

    def exportar(self):
        if not self.res:
            return
        ruta = filedialog.asksaveasfilename(defaultextension=".txt",
                                            initialfile=os.path.splitext(self.archivo)[0] + "_informe.txt",
                                            filetypes=[("Texto", "*.txt")])
        if not ruta:
            return
        r = self.res
        L = [f"INFORME DE COMPILACIÓN — {self.archivo}", time.strftime("%Y-%m-%d %H:%M"), "=" * 70, "",
             "FASES"]
        for i, nom in enumerate(FASES):
            L.append(f"  {nom:<18} {self.estado_fases[i]:<10} {self.sub_fases[i]}")
        L += ["", f"ERRORES ({len(self.errores)})"]
        for k, e in enumerate(self.errores, 1):
            L.append(f"  {k}. [{e['fase']}] línea {e['linea']}, col {e['columna']}: {e['mensaje']}")
            if e.get("sugerencia"):
                L.append(f"       → {e['sugerencia']}")
        if r.get("simbolos"):
            L += ["", f"TABLA DE SÍMBOLOS ({len(r['simbolos'])})",
                  f"  {'Nombre':<20} {'Categoría':<22} {'Tipo':<30} {'Ámbito':<26} Lín"]
            for s in r["simbolos"]:
                L.append(f"  {str(s.get('nombre', '')):<20} {str(s.get('categoria', '')):<22} "
                         f"{str(s.get('tipo', '')):<30} {str(s.get('ambito', '')):<26} {s.get('linea', '')}")
        L += ["", f"TOKENS ({len(r['tokens']) - 1})"]
        for k, t in enumerate(r["tokens"][:-1], 1):
            L.append(f"  {k:>4}  {t.tipo:<14} {t.lexema:<30} {t.linea}:{t.columna}")
        if r["sint"]:
            L += ["", "ÁRBOL SINTÁCTICO", r["sint"].arbol.como_texto()]
        L += ["", "BITÁCORA", self.bitacora.get("1.0", "end")]
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("\n".join(L))
        messagebox.showinfo("Exportar informe", f"Informe guardado en:\n{ruta}")


def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
