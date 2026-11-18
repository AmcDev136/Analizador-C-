# -*- coding: utf-8 -*-
"""
Analizador léxico de C++ con interfaz gráfica Tkinter.
Requiere Python 3.10 o superior. No necesita paquetes externos.
"""

from __future__ import annotations

import re
import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from pathlib import Path
from collections import Counter
from typing import Optional


# ---------------------------------------------------------------------------
# Analizador léxico
# ---------------------------------------------------------------------------

@dataclass
class Token:
    tipo: str
    lexema: str
    linea: int
    columna: int


@dataclass
class ErrorLexico:
    mensaje: str
    lexema: str
    linea: int
    columna: int


@dataclass
class ResultadoLexico:
    tokens: list[Token]
    errores: list[ErrorLexico]


class AnalizadorLexicoCPP:
    """Reconoce tokens habituales de C++ sin ejecutar ni compilar el programa."""

    PALABRAS_RESERVADAS = set("""
        alignas alignof and and_eq asm atomic_cancel atomic_commit atomic_noexcept
        auto bitand bitor bool break case catch char char8_t char16_t char32_t
        class compl concept const consteval constexpr constinit const_cast
        continue co_await co_return co_yield decltype default delete do double
        dynamic_cast else enum explicit export extern false float for friend goto
        if inline int long mutable namespace new noexcept not not_eq nullptr
        operator or or_eq private protected public register reinterpret_cast
        requires return short signed sizeof static static_assert static_cast
        struct switch synchronized template this thread_local throw true try
        typedef typeid typename union unsigned using virtual void volatile wchar_t
        while xor xor_eq
    """.split())

    LITERALES = {"true", "false", "nullptr"}

    OPERADORES = tuple(sorted({
        "%:%:", ">>=", "<<=", "<=>", "->*", "...",
        "++", "--", "->", ".*", "::", "&&", "||",
        "<=", ">=", "==", "!=", "+=", "-=", "*=", "/=",
        "%=", "&=", "|=", "^=", "<<", ">>",
        "+", "-", "*", "/", "%", "=", "<", ">", "!",
        "&", "|", "^", "~", "?", ":", "#"
    }, key=len, reverse=True))

    PUNTUACION = set("()[]{};,.")

    _DIGITS = r"(?:[0-9](?:[0-9']*[0-9])?)"
    _HEX_DIGITS = r"(?:[0-9a-fA-F](?:[0-9a-fA-F']*[0-9a-fA-F])?)"
    _BIN_DIGITS = r"(?:[01](?:[01']*[01])?)"
    _INT_SUFFIX = r"(?:(?:[uU](?:ll|LL|l|L)?|(?:ll|LL|l|L)[uU]?)|[zZ][uU]?)?"
    _FLOAT_SUFFIX = r"[fFlL]?"

    _RE_HEX_INT = re.compile(rf"0[xX]{_HEX_DIGITS}{_INT_SUFFIX}\Z")
    _RE_BIN_INT = re.compile(rf"0[bB]{_BIN_DIGITS}{_INT_SUFFIX}\Z")
    _RE_DEC_INT = re.compile(rf"(?:0|[1-9](?:[0-9']*[0-9])?){_INT_SUFFIX}\Z")
    _RE_DEC_FLOAT = re.compile(
        rf"(?:(?:{_DIGITS}\.(?:{_DIGITS})?|\.{_DIGITS})(?:[eE][+-]?{_DIGITS})?"
        rf"|{_DIGITS}[eE][+-]?{_DIGITS}){_FLOAT_SUFFIX}\Z"
    )
    _RE_HEX_FLOAT = re.compile(
        rf"0[xX](?:{_HEX_DIGITS}\.(?:{_HEX_DIGITS})?|{_HEX_DIGITS}|\.{_HEX_DIGITS})"
        rf"[pP][+-]?{_DIGITS}{_FLOAT_SUFFIX}\Z"
    )

    def __init__(self, codigo: str):
        self.codigo = codigo
        self.i = 0
        self.linea = 1
        self.columna = 1
        self.tokens: list[Token] = []
        self.errores: list[ErrorLexico] = []
        self.longitud = len(codigo)

    def _actual(self) -> str:
        return self.codigo[self.i] if self.i < self.longitud else ""

    def _mirar(self, desplazamiento: int = 1) -> str:
        pos = self.i + desplazamiento
        return self.codigo[pos] if pos < self.longitud else ""

    def _avanzar(self) -> str:
        if self.i >= self.longitud:
            return ""
        caracter = self.codigo[self.i]
        self.i += 1
        if caracter == "\n":
            self.linea += 1
            self.columna = 1
        else:
            self.columna += 1
        return caracter

    def _agregar_token(self, tipo: str, lexema: str, linea: int, columna: int):
        self.tokens.append(Token(tipo, lexema, linea, columna))

    def _agregar_error(self, mensaje: str, lexema: str, linea: int, columna: int):
        self.errores.append(ErrorLexico(mensaje, lexema, linea, columna))

    @staticmethod
    def _es_inicio_identificador(c: str) -> bool:
        return bool(c) and (c == "_" or c.isalpha() or ord(c) >= 128)

    @staticmethod
    def _es_parte_identificador(c: str) -> bool:
        return bool(c) and (c == "_" or c.isalnum() or ord(c) >= 128)

    def analizar(self) -> ResultadoLexico:
        while self.i < self.longitud:
            c = self._actual()

            if c.isspace():
                self._avanzar()
                continue

            inicio_linea, inicio_columna = self.linea, self.columna

            # Comentario de una línea.
            if c == "/" and self._mirar() == "/":
                self._leer_comentario_linea()
                continue

            # Comentario de bloque.
            if c == "/" and self._mirar() == "*":
                self._leer_comentario_bloque()
                continue

            # Cadenas raw: R"...", u8R"...", uR"...", UR"...", LR"..."
            prefijo_raw = self._detectar_prefijo_raw()
            if prefijo_raw is not None:
                self._leer_cadena_raw(prefijo_raw)
                continue

            # Cadenas y caracteres normales con prefijos opcionales.
            prefijo_literal = self._detectar_prefijo_literal()
            if prefijo_literal is not None:
                self._leer_literal(prefijo_literal)
                continue

            # Identificadores y palabras reservadas.
            if self._es_inicio_identificador(c):
                self._leer_identificador()
                continue

            # Literales numéricos, incluyendo .5 y formatos hex/binarios.
            if c.isdigit() or (c == "." and self._mirar().isdigit()):
                self._leer_numero()
                continue

            # Cabecera de #include, por ejemplo <iostream>.
            if c == "<" and self._hay_directiva_include_en_linea():
                if self._leer_cabecera_include():
                    continue

            # Operadores: se busca primero el más largo.
            operador = next(
                (op for op in self.OPERADORES if self.codigo.startswith(op, self.i)),
                None
            )
            if operador:
                for _ in operador:
                    self._avanzar()
                tipo = "Directiva" if operador == "#" and self._es_inicio_directiva(inicio_columna) else "Operador"
                self._agregar_token(tipo, operador, inicio_linea, inicio_columna)
                continue

            if c in self.PUNTUACION:
                self._avanzar()
                self._agregar_token("Delimitador", c, inicio_linea, inicio_columna)
                continue

            # Caracteres que no pertenecen a los tokens reconocidos.
            self._avanzar()
            self._agregar_error(
                f"Carácter no reconocido: {c!r}",
                c,
                inicio_linea,
                inicio_columna
            )

        return ResultadoLexico(self.tokens, self.errores)

    def _es_inicio_directiva(self, columna: int) -> bool:
        # El # es válido como inicio de directiva si antes solo hay espacios.
        inicio = self.codigo.rfind("\n", 0, self.i) + 1
        return self.codigo[inicio:max(inicio, self.i - 1)].strip() == ""

    def _leer_comentario_linea(self):
        linea, columna = self.linea, self.columna
        inicio = self.i
        while self.i < self.longitud and self._actual() != "\n":
            self._avanzar()
        self._agregar_token("Comentario", self.codigo[inicio:self.i], linea, columna)

    def _leer_comentario_bloque(self):
        linea, columna = self.linea, self.columna
        inicio = self.i
        self._avanzar()
        self._avanzar()
        while self.i < self.longitud:
            if self._actual() == "*" and self._mirar() == "/":
                self._avanzar()
                self._avanzar()
                self._agregar_token("Comentario", self.codigo[inicio:self.i], linea, columna)
                return
            self._avanzar()

        lexema = self.codigo[inicio:self.i]
        self._agregar_error("Comentario de bloque sin cerrar (falta */).", lexema, linea, columna)

    def _detectar_prefijo_raw(self) -> Optional[str]:
        for prefijo in ("u8R", "uR", "UR", "LR", "R"):
            if self.codigo.startswith(prefijo + '"', self.i):
                return prefijo
        return None

    def _leer_cadena_raw(self, prefijo: str):
        linea, columna = self.linea, self.columna
        inicio = self.i
        for _ in prefijo:
            self._avanzar()
        self._avanzar()  # comilla inicial
        inicio_delimitador = self.i

        while self.i < self.longitud and self._actual() != "(":
            c = self._actual()
            if c.isspace() or c in "\\)":
                self._avanzar()
                self._agregar_error("Delimitador inválido en cadena raw de C++.",
                                    self.codigo[inicio:self.i], linea, columna)
                return
            self._avanzar()

        if self.i >= self.longitud:
            self._agregar_error("Cadena raw incompleta: falta '(' y el delimitador de cierre.",
                                self.codigo[inicio:self.i], linea, columna)
            return

        delimitador = self.codigo[inicio_delimitador:self.i]
        if len(delimitador) > 16:
            self._avanzar()
            self._agregar_error("El delimitador de una cadena raw no puede superar 16 caracteres.",
                                self.codigo[inicio:self.i], linea, columna)
            return

        self._avanzar()  # (
        cierre = ")" + delimitador + '"'
        posicion_cierre = self.codigo.find(cierre, self.i)
        if posicion_cierre == -1:
            while self.i < self.longitud:
                self._avanzar()
            self._agregar_error("Cadena raw sin cerrar.", self.codigo[inicio:self.i], linea, columna)
            return

        while self.i < posicion_cierre + len(cierre):
            self._avanzar()
        self._agregar_token("Cadena", self.codigo[inicio:self.i], linea, columna)

    def _detectar_prefijo_literal(self) -> Optional[str]:
        for prefijo in ("u8", "u", "U", "L", ""):
            inicio = self.i + len(prefijo)
            if inicio < self.longitud and self.codigo.startswith(prefijo, self.i):
                if self.codigo[inicio] in ('"', "'"):
                    return prefijo
        return None

    def _leer_literal(self, prefijo: str):
        linea, columna = self.linea, self.columna
        inicio = self.i
        for _ in prefijo:
            self._avanzar()

        comilla = self._actual()
        tipo = "Cadena" if comilla == '"' else "Carácter"
        self._avanzar()
        cerrado = False

        while self.i < self.longitud:
            c = self._actual()

            if c == comilla:
                self._avanzar()
                cerrado = True
                break

            if c == "\n":
                break

            if c == "\\":
                self._avanzar()
                if self.i < self.longitud:
                    # Una secuencia escapada se consume como parte del literal.
                    self._avanzar()
                continue

            self._avanzar()

        lexema = self.codigo[inicio:self.i]
        if not cerrado:
            self._agregar_error(
                "Literal de cadena sin cerrar." if comilla == '"' else "Literal de carácter sin cerrar.",
                lexema, linea, columna
            )
        else:
            if tipo == "Carácter":
                contenido = lexema[len(prefijo) + 1:-1]
                if contenido == "":
                    self._agregar_error("Un literal de carácter no puede estar vacío.", lexema, linea, columna)
                    return
            self._agregar_token(tipo, lexema, linea, columna)

    def _leer_identificador(self):
        linea, columna = self.linea, self.columna
        inicio = self.i
        self._avanzar()
        while self._es_parte_identificador(self._actual()):
            self._avanzar()
        lexema = self.codigo[inicio:self.i]

        if lexema in self.LITERALES:
            tipo = "Literal booleano/nulo"
        elif lexema in self.PALABRAS_RESERVADAS:
            tipo = "Palabra reservada"
        else:
            tipo = "Identificador"

        self._agregar_token(tipo, lexema, linea, columna)

    def _leer_numero(self):
        linea, columna = self.linea, self.columna
        inicio = self.i

        # Consume un preprocessing-number aproximado para poder detectar
        # números mal formados como 12abc o 0xG de una sola vez.
        while self.i < self.longitud:
            c = self._actual()
            if c.isalnum() or c in "._'":
                self._avanzar()
                continue
            if c in "+-" and self.i > inicio and self.codigo[self.i - 1] in "eEpP":
                self._avanzar()
                continue
            break

        lexema = self.codigo[inicio:self.i]
        valido_entero = any(regex.fullmatch(lexema) for regex in (
            self._RE_HEX_INT, self._RE_BIN_INT, self._RE_DEC_INT
        ))
        valido_flotante = any(regex.fullmatch(lexema) for regex in (
            self._RE_DEC_FLOAT, self._RE_HEX_FLOAT
        ))

        if valido_entero:
            self._agregar_token("Entero", lexema, linea, columna)
        elif valido_flotante:
            self._agregar_token("Flotante", lexema, linea, columna)
        else:
            self._agregar_error("Literal numérico mal formado.", lexema, linea, columna)

    def _hay_directiva_include_en_linea(self) -> bool:
        inicio = self.codigo.rfind("\n", 0, self.i) + 1
        prefijo = self.codigo[inicio:self.i]
        return bool(re.match(r"^\s*#\s*include\s*$", prefijo))

    def _leer_cabecera_include(self) -> bool:
        linea, columna = self.linea, self.columna
        inicio = self.i
        self._avanzar()  # <
        while self.i < self.longitud and self._actual() not in ">\n":
            self._avanzar()
        if self._actual() == ">":
            self._avanzar()
            self._agregar_token("Cabecera", self.codigo[inicio:self.i], linea, columna)
            return True
        # No consumir una cabecera incompleta como si fuera válida.
        self._agregar_error("Cabecera de #include sin cerrar: falta '>'.",
                            self.codigo[inicio:self.i], linea, columna)
        return True


# ---------------------------------------------------------------------------
# Interfaz gráfica
# ---------------------------------------------------------------------------

class AplicacionAnalizador:
    BG = "#0B1120"
    PANEL = "#151F33"
    PANEL_2 = "#1B2740"
    BORDE = "#2A3854"
    TEXTO = "#E7EDF8"
    SUAVE = "#9AA9C2"
    AZUL = "#6EA8FE"
    VERDE = "#42D392"
    ROJO = "#FF7185"
    AMARILLO = "#F5C66A"
    EDITOR = "#111A2B"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Analizador léxico de C++")
        self.root.geometry("1500x940")
        self.root.minsize(1100, 720)
        self.root.configure(bg=self.BG)

        self.archivo_actual: Optional[Path] = None
        self.resultado: Optional[ResultadoLexico] = None
        self.tokens_visibles: list[Token] = []
        self.errores_visibles: list[ErrorLexico] = []

        self._configurar_estilos()
        self._crear_interfaz()
        self._insertar_ejemplo_inicial()
        self.root.bind("<F5>", lambda _e: self.analizar())
        self.root.bind("<Control-o>", lambda _e: self.abrir_archivo())
        self.root.bind("<Control-s>", lambda _e: self.exportar_reporte())

    def _configurar_estilos(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background=self.PANEL,
                        foreground=self.TEXTO,
                        fieldbackground=self.PANEL,
                        rowheight=27,
                        borderwidth=0,
                        font=("Consolas", 10))
        style.configure("Treeview.Heading",
                        background=self.PANEL_2,
                        foreground=self.TEXTO,
                        relief="flat",
                        font=("Segoe UI", 10, "bold"))
        style.map("Treeview",
                  background=[("selected", "#29477E")],
                  foreground=[("selected", "#FFFFFF")])
        style.configure("Vertical.TScrollbar",
                        background=self.PANEL_2,
                        troughcolor=self.BG,
                        bordercolor=self.BG,
                        arrowcolor=self.SUAVE)

    def _crear_interfaz(self):
        # Encabezado
        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=18, pady=(12, 5))
        tk.Label(header, text="Analizador léxico de C++",
                 bg=self.BG, fg=self.TEXTO,
                 font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(header,
                 text="Identificación de tokens, literales, operadores y errores léxicos.",
                 bg=self.BG, fg=self.SUAVE,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        # Barra de acciones
        toolbar = tk.Frame(self.root, bg=self.BG)
        toolbar.pack(fill="x", padx=14, pady=8)
        self._boton(toolbar, "📂  Abrir C++", self.abrir_archivo, "#1C2A45").pack(side="left", padx=3)
        self._boton(toolbar, "Ejemplos ▾", self.mostrar_ejemplos, "#1C2A45").pack(side="left", padx=3)
        self._boton(toolbar, "Limpiar", self.limpiar, "#1C2A45").pack(side="left", padx=3)
        self._boton(toolbar, "▶  Analizar léxico  (F5)", self.analizar, "#2458A6").pack(side="left", padx=(14, 3))
        self._boton(toolbar, "Exportar informe", self.exportar_reporte, "#1C2A45").pack(side="right", padx=3)

        # Estado de fases
        stages = tk.Frame(self.root, bg=self.BG)
        stages.pack(fill="x", padx=14, pady=(3, 10))
        self.stage_lexico = self._stage(stages, "✓", "Léxico", "Pendiente", self.VERDE, True)
        self.stage_sintactico = self._stage(stages, "🔒", "Sintáctico", "Requiere análisis léxico", self.SUAVE, False)
        self.stage_semantico = self._stage(stages, "🔒", "Semántico", "Fase bloqueada", self.SUAVE, False)
        self.stage_intermedio = self._stage(stages, "🔒", "Código intermedio", "Fase bloqueada", self.SUAVE, False)
        self.stage_ejecucion = self._stage(stages, "🔒", "Ejecución", "Fase bloqueada", self.SUAVE, False)

        # Área principal
        main = tk.PanedWindow(self.root, orient="horizontal", bg=self.BG,
                              sashwidth=7, sashrelief="flat", bd=0)
        main.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # Editor
        left = tk.Frame(main, bg=self.PANEL, highlightbackground=self.BORDE, highlightthickness=1)
        main.add(left, minsize=480, width=740)
        editor_header = tk.Frame(left, bg=self.PANEL_2, height=38)
        editor_header.pack(fill="x")
        editor_header.pack_propagate(False)
        tk.Label(editor_header, text="Código fuente",
                 bg=self.PANEL_2, fg=self.TEXTO,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=12)
        self.file_label = tk.Label(editor_header, text="sin_archivo.cpp",
                                   bg=self.PANEL_2, fg=self.SUAVE,
                                   font=("Segoe UI", 9))
        self.file_label.pack(side="left", padx=8)
        self.position_label = tk.Label(editor_header, text="Lín 1, Col 1",
                                       bg=self.PANEL_2, fg=self.SUAVE,
                                       font=("Segoe UI", 9))
        self.position_label.pack(side="right", padx=12)

        editor_body = tk.Frame(left, bg=self.EDITOR)
        editor_body.pack(fill="both", expand=True)
        self.line_numbers = tk.Text(editor_body, width=4, padx=8, pady=10,
                                    bg="#0E1727", fg="#627694",
                                    insertbackground="#627694",
                                    font=("Consolas", 11), relief="flat",
                                    state="disabled", takefocus=0,
                                    wrap="none")
        self.line_numbers.pack(side="left", fill="y")
        self.editor = tk.Text(editor_body, padx=10, pady=10,
                              bg=self.EDITOR, fg="#DCE7F7",
                              insertbackground="#FFFFFF",
                              selectbackground="#29477E",
                              font=("Consolas", 11), relief="flat",
                              undo=True, wrap="none",
                              tabs=("4c",))
        self.editor.pack(side="left", fill="both", expand=True)
        editor_scroll = ttk.Scrollbar(editor_body, orient="vertical", command=self._scroll_editor)
        editor_scroll.pack(side="right", fill="y")
        self.editor.configure(yscrollcommand=editor_scroll.set)
        self.editor.bind("<KeyRelease>", self._editor_cambio)
        self.editor.bind("<ButtonRelease-1>", self._actualizar_posicion)
        self.editor.bind("<MouseWheel>", self._actualizar_numeros)
        self.editor.tag_configure("kw", foreground="#82B4FF")
        self.editor.tag_configure("str", foreground="#D8A0E8")
        self.editor.tag_configure("comment", foreground="#6F8D79")
        self.editor.tag_configure("number", foreground="#E9C46A")
        self.editor.tag_configure("error_line", background="#3B202F")
        self.editor.tag_configure("error_mark", underline=True, foreground="#FF8292")

        # Panel derecho: detalle y pestañas
        right = tk.Frame(main, bg=self.BG)
        main.add(right, minsize=430)
        detail = tk.Frame(right, bg=self.PANEL, highlightbackground=self.BORDE, highlightthickness=1)
        detail.pack(fill="x", pady=(0, 8))
        tk.Label(detail, text="Proceso del análisis léxico",
                 bg=self.PANEL, fg=self.TEXTO,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(10, 5))
        self.detail_text = tk.Label(detail,
                                    text="Carga o escribe código C++ y presiona «Analizar léxico».",
                                    bg=self.PANEL, fg=self.SUAVE,
                                    justify="left", anchor="w",
                                    wraplength=650,
                                    font=("Segoe UI", 10))
        self.detail_text.pack(fill="x", padx=14, pady=(0, 12))

        tabs_frame = tk.Frame(right, bg=self.PANEL, highlightbackground=self.BORDE, highlightthickness=1)
        tabs_frame.pack(fill="both", expand=True)
        tabbar = tk.Frame(tabs_frame, bg=self.PANEL_2)
        tabbar.pack(fill="x")
        self.tab_buttons = {}
        for key, label in (("tokens", "Tokens"), ("errores", "Errores"), ("resumen", "Resumen")):
            b = tk.Button(tabbar, text=label, command=lambda k=key: self.cambiar_pestana(k),
                          bg=self.PANEL_2, fg=self.SUAVE, activebackground="#29477E",
                          activeforeground="white", relief="flat", bd=0,
                          padx=14, pady=9, font=("Segoe UI", 9, "bold"), cursor="hand2")
            b.pack(side="left")
            self.tab_buttons[key] = b

        self.tab_content = tk.Frame(tabs_frame, bg=self.PANEL)
        self.tab_content.pack(fill="both", expand=True)
        self._crear_tabla_tokens()
        self._crear_tabla_errores()
        self._crear_tabla_resumen()
        self.cambiar_pestana("tokens")

        # Pie de página
        footer = tk.Frame(self.root, bg=self.BG)
        footer.pack(fill="x", padx=16, pady=(0, 10))
        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100, value=0)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.footer_label = tk.Label(footer, text="Fase 1 de 5 · Léxico · Esperando código",
                                     bg=self.BG, fg=self.SUAVE, font=("Segoe UI", 9))
        self.footer_label.pack(side="left")
        self.stats_label = tk.Label(footer, text="Tokens: 0   ·   Errores: 0",
                                    bg=self.BG, fg=self.TEXTO, font=("Segoe UI", 9, "bold"))
        self.stats_label.pack(side="right", padx=(12, 0))

    def _boton(self, parent, text, command, color):
        return tk.Button(parent, text=text, command=command,
                         bg=color, fg=self.TEXTO,
                         activebackground="#30476D", activeforeground="white",
                         relief="flat", bd=0, padx=13, pady=8,
                         font=("Segoe UI", 9, "bold"), cursor="hand2")

    def _stage(self, parent, icon, title, subtitle, color, active):
        frame = tk.Frame(parent, bg=self.PANEL,
                         highlightbackground=self.BORDE, highlightthickness=1,
                         padx=12, pady=9)
        frame.pack(side="left", fill="both", expand=True, padx=2)
        icon_label = tk.Label(frame, text=icon, bg=self.PANEL, fg=color,
                              font=("Segoe UI", 17, "bold"))
        icon_label.pack(side="left", padx=(0, 10))
        text_frame = tk.Frame(frame, bg=self.PANEL)
        text_frame.pack(side="left", fill="x", expand=True)
        title_label = tk.Label(text_frame, text=title, bg=self.PANEL,
                               fg=self.TEXTO if active else self.SUAVE,
                               font=("Segoe UI", 10, "bold"))
        title_label.pack(anchor="w")
        subtitle_label = tk.Label(text_frame, text=subtitle, bg=self.PANEL,
                                  fg=self.SUAVE, font=("Consolas", 8))
        subtitle_label.pack(anchor="w", pady=(2, 0))
        return (frame, icon_label, title_label, subtitle_label)

    def _crear_tabla_tokens(self):
        self.tokens_frame = tk.Frame(self.tab_content, bg=self.PANEL)
        columns = ("numero", "tipo", "lexema", "linea", "columna")
        self.token_tree = ttk.Treeview(self.tokens_frame, columns=columns,
                                       show="headings", height=15)
        for col, title, width in (
            ("numero", "#", 42), ("tipo", "Tipo de token", 150),
            ("lexema", "Lexema", 220), ("linea", "Lín", 55),
            ("columna", "Col", 55)
        ):
            self.token_tree.heading(col, text=title)
            self.token_tree.column(col, width=width, minwidth=35,
                                   anchor="w" if col in ("tipo", "lexema") else "center")
        scroll = ttk.Scrollbar(self.tokens_frame, orient="vertical", command=self.token_tree.yview)
        self.token_tree.configure(yscrollcommand=scroll.set)
        self.token_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)

    def _crear_tabla_errores(self):
        self.errors_frame = tk.Frame(self.tab_content, bg=self.PANEL)
        columns = ("numero", "mensaje", "lexema", "linea", "columna")
        self.error_tree = ttk.Treeview(self.errors_frame, columns=columns,
                                       show="headings", height=15)
        for col, title, width in (
            ("numero", "#", 42), ("mensaje", "Descripción", 260),
            ("lexema", "Lexema", 120), ("linea", "Lín", 50),
            ("columna", "Col", 50)
        ):
            self.error_tree.heading(col, text=title)
            self.error_tree.column(col, width=width, minwidth=35,
                                   anchor="w" if col in ("mensaje", "lexema") else "center")
        scroll = ttk.Scrollbar(self.errors_frame, orient="vertical", command=self.error_tree.yview)
        self.error_tree.configure(yscrollcommand=scroll.set)
        self.error_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)
        self.error_tree.bind("<<TreeviewSelect>>", self._seleccionar_error)

    def _crear_tabla_resumen(self):
        self.summary_frame = tk.Frame(self.tab_content, bg=self.PANEL)
        self.summary_text = tk.Text(self.summary_frame, bg=self.PANEL, fg=self.TEXTO,
                                    font=("Segoe UI", 10), relief="flat",
                                    padx=18, pady=16, wrap="word", state="disabled")
        self.summary_text.pack(fill="both", expand=True)

    def cambiar_pestana(self, key):
        for child in self.tab_content.winfo_children():
            child.pack_forget()
        frame = {"tokens": self.tokens_frame, "errores": self.errors_frame,
                 "resumen": self.summary_frame}[key]
        frame.pack(fill="both", expand=True)
        for name, button in self.tab_buttons.items():
            button.configure(bg="#29477E" if name == key else self.PANEL_2,
                             fg="white" if name == key else self.SUAVE)

    def _insertar_ejemplo_inicial(self):
        ejemplo = """#include <iostream>
#include <string>
using namespace std;

// Ejemplo para probar el analizador léxico
int sumar(int a, int b) {
    int resultado = a + b;
    return resultado;
}

int main() {
    string mensaje = "Hola, C++";
    double promedio = 9.5;
    bool correcto = true;

    cout << mensaje << endl;
    cout << sumar(4, 5) << endl;
    return 0;
}
"""
        self.editor.insert("1.0", ejemplo)
        self._actualizar_numeros()

    def mostrar_ejemplos(self):
        menu = tk.Menu(self.root, tearoff=0, bg=self.PANEL_2, fg=self.TEXTO,
                       activebackground="#29477E", activeforeground="white")
        menu.add_command(label="C++ correcto", command=self._cargar_ejemplo_correcto)
        menu.add_command(label="Ejemplo con errores léxicos", command=self._cargar_ejemplo_errores)
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _cargar_ejemplo_correcto(self):
        self._reemplazar_editor("""#include <iostream>
using namespace std;

int main() {
    int edad = 20;
    double precio = 35.50;
    char inicial = 'Y';
    string nombre = "Estudiante";

    if (edad >= 18 && precio > 0) {
        cout << nombre << endl;
    }
    return 0;
}
""")
        self.file_label.configure(text="ejemplo_correcto.cpp")

    def _cargar_ejemplo_errores(self):
        self._reemplazar_editor("""#include <iostream>
int main() {
    int numero = 12abc;
    string texto = "Hola;
    /* comentario sin cerrar
    @
    return 0;
}
""")
        self.file_label.configure(text="ejemplo_errores.cpp")

    def _reemplazar_editor(self, codigo):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", codigo)
        self.resultado = None
        self._limpiar_resultados()
        self._actualizar_numeros()
        self._quitar_resaltado()

    def abrir_archivo(self):
        ruta = filedialog.askopenfilename(
            title="Abrir archivo de C++",
            filetypes=[
                ("Archivos C++", "*.cpp *.cc *.cxx *.c++ *.h *.hpp *.hh *.hxx"),
                ("Todos los archivos", "*.*")
            ]
        )
        if not ruta:
            return
        try:
            contenido = Path(ruta).read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                contenido = Path(ruta).read_text(encoding="latin-1")
            except OSError as exc:
                messagebox.showerror("No se pudo abrir el archivo", str(exc))
                return
        except OSError as exc:
            messagebox.showerror("No se pudo abrir el archivo", str(exc))
            return

        self._reemplazar_editor(contenido)
        self.archivo_actual = Path(ruta)
        self.file_label.configure(text=self.archivo_actual.name)
        self.footer_label.configure(text=f"Archivo cargado · {self.archivo_actual.name}")

    def limpiar(self):
        if not self.editor.get("1.0", "end-1c").strip():
            return
        if not messagebox.askyesno("Limpiar editor", "¿Deseas borrar el código fuente y los resultados?"):
            return
        self.editor.delete("1.0", "end")
        self.archivo_actual = None
        self.file_label.configure(text="sin_archivo.cpp")
        self.resultado = None
        self._limpiar_resultados()
        self._actualizar_numeros()
        self._quitar_resaltado()
        self.footer_label.configure(text="Fase 1 de 5 · Léxico · Esperando código")

    def analizar(self):
        codigo = self.editor.get("1.0", "end-1c")
        if not codigo.strip():
            messagebox.showwarning("Sin código", "Escribe o abre un archivo C++ antes de analizar.")
            return

        try:
            analizador = AnalizadorLexicoCPP(codigo)
            self.resultado = analizador.analizar()
        except Exception as exc:
            messagebox.showerror("Error interno", f"Ocurrió un problema durante el análisis:\n{exc}")
            return

        self.tokens_visibles = self.resultado.tokens
        self.errores_visibles = self.resultado.errores
        self._mostrar_resultados()
        self._resaltar_codigo()
        self.progress["value"] = 100 if not self.errores_visibles else max(
            10, int(100 * len(self.tokens_visibles) /
                    max(1, len(self.tokens_visibles) + len(self.errores_visibles)))
        )

        total = len(self.tokens_visibles)
        errores = len(self.errores_visibles)
        estado = "completado sin errores" if errores == 0 else f"completado con {errores} error(es)"
        self.footer_label.configure(text=f"Fase 1 de 5 · Léxico · {estado}")
        self.stats_label.configure(text=f"Tokens: {total}   ·   Errores: {errores}")
        self._actualizar_stage(total, errores)

        if errores:
            primero = self.errores_visibles[0]
            self.detail_text.configure(
                text=f"Se encontraron {errores} error(es) léxico(s). "
                     f"Primer error en línea {primero.linea}, columna {primero.columna}: "
                     f"{primero.mensaje}",
                fg=self.ROJO
            )
            self.cambiar_pestana("errores")
        else:
            self.detail_text.configure(
                text=f"Análisis léxico terminado correctamente. Se reconocieron {total} tokens y no se encontraron errores léxicos.",
                fg=self.VERDE
            )
            self.cambiar_pestana("tokens")

    def _actualizar_stage(self, total, errores):
        frame, icon, title, subtitle = self.stage_lexico
        if errores:
            icon.configure(text="×", fg=self.ROJO)
            subtitle.configure(text=f"{total} tokens · {errores} errores", fg=self.ROJO)
        else:
            icon.configure(text="✓", fg=self.VERDE)
            subtitle.configure(text=f"{total} tokens · 0 errores", fg=self.VERDE)

    def _mostrar_resultados(self):
        for item in self.token_tree.get_children():
            self.token_tree.delete(item)
        for item in self.error_tree.get_children():
            self.error_tree.delete(item)

        for n, token in enumerate(self.tokens_visibles, 1):
            lexema = token.lexema.replace("\n", "\\n").replace("\t", "\\t")
            if len(lexema) > 70:
                lexema = lexema[:67] + "..."
            self.token_tree.insert("", "end",
                                   values=(n, token.tipo, lexema, token.linea, token.columna))

        for n, error in enumerate(self.errores_visibles, 1):
            lexema = error.lexema.replace("\n", "\\n").replace("\t", "\\t")
            if len(lexema) > 45:
                lexema = lexema[:42] + "..."
            self.error_tree.insert("", "end",
                                   values=(n, error.mensaje, lexema, error.linea, error.columna))

        conteo = Counter(t.tipo for t in self.tokens_visibles)
        lineas = [
            "RESUMEN DEL ANÁLISIS LÉXICO",
            "",
            f"Total de tokens reconocidos: {len(self.tokens_visibles)}",
            f"Errores léxicos: {len(self.errores_visibles)}",
            "",
            "TOKENS POR CATEGORÍA"
        ]
        for tipo, cantidad in sorted(conteo.items()):
            lineas.append(f"  • {tipo}: {cantidad}")
        if self.errores_visibles:
            lineas += ["", "ERRORES DETECTADOS"]
            for error in self.errores_visibles:
                lineas.append(f"  • Línea {error.linea}, columna {error.columna}: {error.mensaje}")
        else:
            lineas += ["", "No se encontraron errores léxicos."]
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "\n".join(lineas))
        self.summary_text.configure(state="disabled")

    def _limpiar_resultados(self):
        for tree in (getattr(self, "token_tree", None), getattr(self, "error_tree", None)):
            if tree:
                for item in tree.get_children():
                    tree.delete(item)
        if hasattr(self, "summary_text"):
            self.summary_text.configure(state="normal")
            self.summary_text.delete("1.0", "end")
            self.summary_text.configure(state="disabled")
        self.progress["value"] = 0
        self.stats_label.configure(text="Tokens: 0   ·   Errores: 0")
        self.detail_text.configure(text="Carga o escribe código C++ y presiona «Analizar léxico».",
                                   fg=self.SUAVE)
        self._actualizar_stage(0, 0)

    def exportar_reporte(self):
        if self.resultado is None:
            messagebox.showinfo("Sin resultados", "Primero realiza el análisis léxico.")
            return
        ruta = filedialog.asksaveasfilename(
            title="Exportar informe léxico",
            defaultextension=".txt",
            filetypes=[("Informe de texto", "*.txt"), ("CSV de tokens", "*.csv")]
        )
        if not ruta:
            return
        destino = Path(ruta)
        try:
            if destino.suffix.lower() == ".csv":
                with destino.open("w", newline="", encoding="utf-8-sig") as archivo:
                    writer = csv.writer(archivo)
                    writer.writerow(["Tipo", "Lexema", "Línea", "Columna"])
                    for token in self.tokens_visibles:
                        writer.writerow([token.tipo, token.lexema, token.linea, token.columna])
                    if self.errores_visibles:
                        writer.writerow([])
                        writer.writerow(["ERRORES"])
                        writer.writerow(["Mensaje", "Lexema", "Línea", "Columna"])
                        for error in self.errores_visibles:
                            writer.writerow([error.mensaje, error.lexema, error.linea, error.columna])
            else:
                with destino.open("w", encoding="utf-8") as archivo:
                    archivo.write("INFORME DEL ANALIZADOR LÉXICO DE C++\n")
                    archivo.write("=" * 48 + "\n\n")
                    archivo.write(f"Tokens: {len(self.tokens_visibles)}\n")
                    archivo.write(f"Errores: {len(self.errores_visibles)}\n\n")
                    archivo.write("TOKENS\n")
                    archivo.write("-" * 48 + "\n")
                    for n, token in enumerate(self.tokens_visibles, 1):
                        archivo.write(f"{n:4}. {token.tipo:24} {token.lexema!r:35} "
                                      f"Línea {token.linea}, columna {token.columna}\n")
                    archivo.write("\nERRORES\n")
                    archivo.write("-" * 48 + "\n")
                    if not self.errores_visibles:
                        archivo.write("No se encontraron errores léxicos.\n")
                    for n, error in enumerate(self.errores_visibles, 1):
                        archivo.write(f"{n:4}. {error.mensaje} | {error.lexema!r} | "
                                      f"Línea {error.linea}, columna {error.columna}\n")
            messagebox.showinfo("Informe exportado", f"El informe se guardó en:\n{destino}")
        except OSError as exc:
            messagebox.showerror("No se pudo exportar", str(exc))

    def _resaltar_codigo(self):
        self._quitar_resaltado()
        if not self.resultado:
            return

        # Resaltado léxico por categoría.
        for token in self.resultado.tokens:
            if token.tipo == "Comentario":
                tag = "comment"
            elif token.tipo in ("Cadena", "Carácter", "Cabecera"):
                tag = "str"
            elif token.tipo in ("Entero", "Flotante", "Literal booleano/nulo"):
                tag = "number"
            elif token.tipo == "Palabra reservada":
                tag = "kw"
            else:
                continue
            start = f"{token.linea}.{token.columna - 1}"
            end = f"{token.linea}.{token.columna - 1 + len(token.lexema)}"
            try:
                self.editor.tag_add(tag, start, end)
            except tk.TclError:
                pass

        # Marca líneas con errores.
        for error in self.resultado.errores:
            start = f"{error.linea}.0"
            end = f"{error.linea}.end"
            try:
                self.editor.tag_add("error_line", start, end)
                col_start = f"{error.linea}.{max(0, error.columna - 1)}"
                col_end = f"{error.linea}.{max(0, error.columna - 1) + max(1, len(error.lexema))}"
                self.editor.tag_add("error_mark", col_start, col_end)
            except tk.TclError:
                pass

    def _quitar_resaltado(self):
        for tag in ("kw", "str", "comment", "number", "error_line", "error_mark"):
            self.editor.tag_remove(tag, "1.0", "end")

    def _seleccionar_error(self, _event=None):
        seleccion = self.error_tree.selection()
        if not seleccion:
            return
        indice = self.error_tree.index(seleccion[0])
        if indice >= len(self.errores_visibles):
            return
        error = self.errores_visibles[indice]
        self.editor.mark_set("insert", f"{error.linea}.{max(0, error.columna - 1)}")
        self.editor.see("insert")
        self.editor.focus_set()
        self._actualizar_posicion()

    def _editor_cambio(self, _event=None):
        self._actualizar_numeros()
        self._actualizar_posicion()
        # Los resultados anteriores ya no representan el texto actual.
        if self.resultado is not None:
            self.resultado = None
            self._limpiar_resultados()
            self._quitar_resaltado()
            self.footer_label.configure(text="Código modificado · vuelve a analizar")

    def _actualizar_numeros(self, _event=None):
        cantidad = int(self.editor.index("end-1c").split(".")[0])
        numeros = "\n".join(str(i) for i in range(1, cantidad + 1))
        self.line_numbers.configure(state="normal")
        self.line_numbers.delete("1.0", "end")
        self.line_numbers.insert("1.0", numeros)
        self.line_numbers.configure(state="disabled")
        self.line_numbers.yview_moveto(self.editor.yview()[0])

    def _scroll_editor(self, *args):
        self.editor.yview(*args)
        self.line_numbers.yview(*args)

    def _actualizar_posicion(self, _event=None):
        linea, columna = self.editor.index("insert").split(".")
        self.position_label.configure(text=f"Lín {linea}, Col {int(columna) + 1}")


def main():
    root = tk.Tk()
    AplicacionAnalizador(root)
    root.mainloop()


if __name__ == "__main__":
    main()
